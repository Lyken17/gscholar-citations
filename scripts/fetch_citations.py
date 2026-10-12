#!/usr/bin/env python3
"""Fetch and record the all-time citation count for one Google Scholar profile."""

import argparse
import csv
import json
import re
import sys
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SCHOLAR_ID = "y0LVrtgAAAAJ"
PROFILE_URL = f"https://scholar.google.com/citations?user={SCHOLAR_ID}&hl=en"


class FetchError(RuntimeError):
    """The response cannot be used as a citation count."""


class CitationTableParser(HTMLParser):
    """Collect cells only from Scholar's summary statistics table."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.table_depth = 0
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            if self.table_depth:
                self.table_depth += 1
            elif dict(attrs).get("id") == "gsc_rsb_st":
                self.table_depth = 1
        if self.table_depth == 1:
            if tag == "tr":
                self.row = []
            elif tag in ("td", "th") and self.row is not None:
                self.cell = []

    def handle_data(self, data):
        if self.table_depth == 1 and self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if self.table_depth == 1:
            if tag in ("td", "th") and self.cell is not None:
                self.row.append("".join(self.cell).strip())
                self.cell = None
            elif tag == "tr" and self.row is not None:
                self.rows.append(self.row)
                self.row = None
        if tag == "table" and self.table_depth:
            self.table_depth -= 1


def parse_total_citations(html):
    parser = CitationTableParser()
    parser.feed(html)
    parser.close()

    all_column = None
    for row in parser.rows:
        if "All" in row:
            all_column = row.index("All")
            break

    if all_column is not None:
        for row in parser.rows:
            if row and row[0] == "Citations" and len(row) > all_column:
                value = row[all_column]
                if re.fullmatch(r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)", value):
                    return int(value.replace(",", ""))
                raise FetchError(f"Invalid all-time citation count: {value!r}")

    raise FetchError(
        "Google Scholar's Citations / All value was not found. "
        "The response may be a CAPTCHA or the page layout may have changed."
    )


def fetch_total_citations():
    request = Request(
        PROFILE_URL,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    for attempt in range(1, 4):
        try:
            with urlopen(request, timeout=30) as response:
                encoding = response.headers.get_content_charset() or "utf-8"
                html = response.read().decode(encoding)
            return parse_total_citations(html)
        except HTTPError as error:
            if error.code not in (408, 429, 500, 502, 503, 504) or attempt == 3:
                raise FetchError(
                    f"Google Scholar returned HTTP {error.code}. "
                    "Access may be blocked; existing citation data was not changed."
                ) from error
        except (URLError, TimeoutError, HTTPException) as error:
            if attempt == 3:
                raise FetchError(f"Could not reach Google Scholar: {error}") from error
        print(f"Request failed; retrying ({attempt}/2)...", file=sys.stderr)
        time.sleep(20 * attempt)


def save_count(total_citations, output_dir, fetched_at):
    """Keep one observation per UTC day, replacing it on a same-day rerun."""
    fetched_at = fetched_at.astimezone(timezone.utc)
    day = fetched_at.date().isoformat()
    history_path = output_dir / "citations.csv"
    counts = {}
    if history_path.exists():
        with history_path.open(newline="", encoding="utf-8") as source:
            reader = csv.DictReader(source)
            if reader.fieldnames != ["date", "total_citations"]:
                raise ValueError(f"Unexpected CSV columns in {history_path}")
            for row in reader:
                counts[row["date"]] = int(row["total_citations"])
    counts[day] = total_citations

    output_dir.mkdir(parents=True, exist_ok=True)
    with history_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(["date", "total_citations"])
        writer.writerows(sorted(counts.items()))

    latest = {
        "scholar_id": SCHOLAR_ID,
        "profile_url": PROFILE_URL,
        "total_citations": total_citations,
        "fetched_at": fetched_at.isoformat().replace("+00:00", "Z"),
    }
    (output_dir / "latest.json").write_text(
        json.dumps(latest, indent=2) + "\n", encoding="utf-8"
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("data"))
    args = parser.parse_args(argv)
    try:
        total = fetch_total_citations()
        save_count(total, args.output_dir, datetime.now(timezone.utc))
    except (FetchError, OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print(f"{SCHOLAR_ID}: {total} total citations")
    print(f"Saved citation history and latest count to {args.output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
