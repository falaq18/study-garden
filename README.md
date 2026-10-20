# Arushi's study garden 🌱

A cosy pixel dashboard for a 10-week personal curriculum (Oct 26, 2026 to Jan 3, 2027).

- `index.html` is the whole site (no build step).
- `links.json` is refreshed every morning at 7 am IST by `.github/workflows/daily-links.yml`, which runs `scripts/fetch_links.py`.
- `calendar.ics`, `curriculum.pdf` and `curriculum.epub` are the downloads linked in the footer.

## Moving this repo to Arushi's own account
Settings → General → Danger Zone → **Transfer ownership** → type the new username.
Then in the new repo: Settings → Pages → Deploy from branch → `main` / root.
The site will live at `https://<new-username>.github.io/study-garden/`.
