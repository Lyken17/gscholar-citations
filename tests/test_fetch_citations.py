import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from scripts.fetch_citations import (
    PROFILE_URL,
    SCHOLAR_ID,
    FetchError,
    fetch_total_citations,
    main,
    parse_total_citations,
    save_count,
)

# Representative Scholar markup; all-time and recent counts deliberately differ.
PROFILE_HTML = """
<table><tr><td class="gsc_rsb_std">999999</td></tr></table>
<table id="gsc_rsb_st">
  <thead><tr><th></th><th>All</th><th>Since 2021</th></tr></thead>
  <tbody>
    <tr><td><a href="#">Citations</a></td>
      <td class="gsc_rsb_std"><span>12,345</span></td>
      <td class="gsc_rsb_std">6789</td></tr>
    <tr><td>h-index</td><td>54</td><td>43</td></tr>
    <tr><td>i10-index</td><td>87</td><td>76</td></tr>
  </tbody>
</table>
"""


class ParseTests(unittest.TestCase):
    def test_reads_all_time_citations_from_summary_table(self):
        self.assertEqual(parse_total_citations(PROFILE_HTML), 12345)

    def test_tracks_all_column_if_columns_are_reordered(self):
        html = PROFILE_HTML.replace(
            "<th>All</th><th>Since 2021</th>",
            "<th>Since 2021</th><th>All</th>",
        )
        self.assertEqual(parse_total_citations(html), 6789)

    def test_accepts_zero(self):
        self.assertEqual(parse_total_citations(PROFILE_HTML.replace("12,345", "0")), 0)

    def test_rejects_missing_or_invalid_counts(self):
        for html in (
            "<html><body>Verify you are human</body></html>",
            PROFILE_HTML.replace("Citations", "h-index"),
            PROFILE_HTML.replace("All", "Recent"),
            PROFILE_HTML.replace("12,345", ""),
            PROFILE_HTML.replace("12,345", "1,2"),
            PROFILE_HTML.replace("12,345", "-5"),
        ):
            with self.subTest(html=html), self.assertRaises(FetchError):
                parse_total_citations(html)


class FetchTests(unittest.TestCase):
    @patch("scripts.fetch_citations.time.sleep")
    @patch("scripts.fetch_citations.urlopen")
    def test_retries_rate_limits_then_reads_count(self, urlopen, sleep):
        response = urlopen.return_value.__enter__.return_value
        response.headers.get_content_charset.return_value = "utf-8"
        response.read.return_value = PROFILE_HTML.encode("utf-8")
        urlopen.side_effect = [
            HTTPError(PROFILE_URL, 429, "Too Many Requests", {}, None),
            urlopen.return_value,
        ]
        with redirect_stderr(io.StringIO()):
            self.assertEqual(fetch_total_citations(), 12345)
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(20)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, PROFILE_URL)
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 30)

    @patch("scripts.fetch_citations.time.sleep")
    @patch("scripts.fetch_citations.urlopen")
    def test_fails_on_forbidden_without_retrying(self, urlopen, sleep):
        urlopen.side_effect = HTTPError(PROFILE_URL, 403, "Forbidden", {}, None)
        with self.assertRaisesRegex(FetchError, "HTTP 403"):
            fetch_total_citations()
        urlopen.assert_called_once()
        sleep.assert_not_called()

    @patch("scripts.fetch_citations.time.sleep")
    @patch("scripts.fetch_citations.urlopen", side_effect=URLError("network unavailable"))
    def test_network_retries_are_bounded(self, urlopen, sleep):
        with redirect_stderr(io.StringIO()), self.assertRaises(FetchError):
            fetch_total_citations()
        self.assertEqual(urlopen.call_count, 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [20, 40])


class PersistenceTests(unittest.TestCase):
    def test_keeps_one_observation_per_utc_day_and_updates_latest(self):
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory) / "data"
            first = datetime(2026, 10, 12, 8, 17, tzinfo=timezone(timedelta(hours=8)))
            save_count(100, output_dir, first)
            save_count(102, output_dir, first + timedelta(hours=1))
            save_count(103, output_dir, first + timedelta(days=1))
            with (output_dir / "citations.csv").open(newline="") as source:
                self.assertEqual(list(csv.DictReader(source)), [
                    {"date": "2026-10-12", "total_citations": "102"},
                    {"date": "2026-10-13", "total_citations": "103"},
                ])
            latest = json.loads((output_dir / "latest.json").read_text())
            self.assertEqual(latest["total_citations"], 103)
            self.assertEqual(latest["scholar_id"], SCHOLAR_ID)
            self.assertEqual(latest["fetched_at"], "2026-10-13T00:17:00Z")

    def test_unchanged_count_is_still_recorded_each_day(self):
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            first = datetime(2026, 10, 12, tzinfo=timezone.utc)
            save_count(100, output_dir, first)
            save_count(100, output_dir, first + timedelta(days=1))
            with (output_dir / "citations.csv").open(newline="") as source:
                self.assertEqual(len(list(csv.DictReader(source))), 2)

    def test_failed_fetch_preserves_existing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            save_count(100, output_dir, datetime(2026, 10, 12, tzinfo=timezone.utc))
            before = {path.name: path.read_bytes() for path in output_dir.iterdir()}
            with patch("scripts.fetch_citations.fetch_total_citations",
                       side_effect=FetchError("CAPTCHA")), redirect_stderr(io.StringIO()):
                self.assertEqual(main(["--output-dir", directory]), 1)
            self.assertEqual(
                {path.name: path.read_bytes() for path in output_dir.iterdir()}, before
            )

    def test_successful_cli_writes_data(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("scripts.fetch_citations.fetch_total_citations", return_value=12345), \
                 redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--output-dir", directory]), 0)
            self.assertEqual(
                json.loads((Path(directory) / "latest.json").read_text())["total_citations"],
                12345,
            )


if __name__ == "__main__":
    unittest.main()
