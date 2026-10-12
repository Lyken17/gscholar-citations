# Google Scholar citation tracker

Fetch the **Citations → All** total for [this Google Scholar profile](https://scholar.google.com/citations?user=y0LVrtgAAAAJ) once a day with GitHub Actions.

The workflow is scheduled for **00:17 UTC / 08:17 China time**. It reads the summary table, saves the count, and commits the data to the repository's default branch using the built-in `GITHUB_TOKEN`. No extra packages or secrets are required.

## Enable on GitHub

1. Push these files to a GitHub repository's default branch.
2. Make sure Actions is enabled for the repository. The workflow requests `contents: write`; any organization policy or branch protection must allow the Actions bot to push data commits to the default branch.
3. Open **Actions → Fetch Google Scholar citations → Run workflow** for the first fetch. Scheduled runs follow automatically.

Scheduled workflows only run from the default branch and can be delayed by GitHub. See [GitHub's schedule documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

## Output

Files are created after the first successful fetch:

- `data/citations.csv`: `date,total_citations`, with one observation per UTC date. A same-day rerun updates that day's count; a new day adds a row even when the count is unchanged.
- `data/latest.json`: `scholar_id`, `profile_url`, `total_citations` (an integer), and `fetched_at` (a UTC timestamp).

The latest JSON also appears in the workflow run summary. The CSV records observed totals; Scholar can revise its count downward, so decreases are preserved.

## Run locally

Use Python 3.12 or newer, with no dependencies to install:

```sh
python3 scripts/fetch_citations.py
python3 -m unittest discover -s tests -v
```

To write elsewhere:

```sh
python3 scripts/fetch_citations.py --output-dir /tmp/citation-data
```

The profile ID and URL are defined in `scripts/fetch_citations.py`. If changing profiles, start a separate history file so observations from different profiles are not mixed. Edit the cron expression in `.github/workflows/citations.yml` to change the daily schedule.

## Fetch failures

Google Scholar may block automated requests, including requests from GitHub-hosted runners. **Live collection is currently blocked; no successful citation snapshot has been recorded.**

Verification on October 12, 2026 found HTTP 403 on all three tested hosted runner types: [Ubuntu](https://github.com/Lyken17/gscholar-citations/actions/runs/38258976732), [macOS](https://github.com/Lyken17/gscholar-citations/actions/runs/38259662315), and [Windows](https://github.com/Lyken17/gscholar-citations/actions/runs/38262906223). Chromium and browser-compatible HTTP clients also received 403. Bounded public-proxy tests did not return a valid citation summary, and the initially reachable proxy later timed out. The temporary diagnostic workflow was removed after these tests.

Changing the runner or request headers did not resolve the live failure. Collection needs a network that Google Scholar allows, or a supported data service. The fetcher and daily schedule are implemented, but successful live retrieval and data commits remain unverified.

The script retries temporary network errors, HTTP 429, and selected server errors up to three requests, with 20- and 40-second delays. A forbidden response, CAPTCHA, missing table, or invalid number makes the job fail before writing data. Existing observations are preserved and no zero is substituted for a failed fetch. Check the failed run's logs and use **Run workflow** to retry later.
