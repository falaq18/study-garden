# Arushi's study garden 🌱

A cosy pixel dashboard for a 10-week personal curriculum (Oct 26, 2026 to Jan 3, 2027).

- `index.html` is the whole site (no build step).
- `links.json` is refreshed every morning at 7 am IST by `.github/workflows/daily-links.yml`, which runs `scripts/fetch_links.py`.
- `calendar.ics`, `curriculum.pdf` and `curriculum.epub` are the downloads linked in the footer.

## Moving this repo to Arushi's own account
Settings → General → Danger Zone → **Transfer ownership** → type the new username.
Then in the new repo: Settings → Pages → Deploy from branch → `main` / root.
The site will live at `https://<new-username>.github.io/study-garden/`.

## How the news is picked

No AI and no paid APIs. Each morning `scripts/fetch_links.py`:
1. Reads top-story feeds from outlets across the political spectrum (each tagged L / C / R from Media Bias/Fact Check and Biasly; the raters disagree, so these are rough buckets). Outlets that block the runner are read through Google News.
2. Groups headlines about the same story (rare words weigh more than common ones).
3. Ranks stories: stories picked by outlets on different sides come first, then by independent outlets, how many publishers Google News finds, editor placement, freshness and a small boost for policy, economy, courts and diplomacy. Live blogs, galleries, promos and celebrity items are pushed down.
4. Audits itself against Wikipedia's "Current events" page and appends the result to `audit-log.jsonl`. `raw-headlines.json` keeps every headline seen, for tuning.
