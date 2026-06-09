# Hot App Summer × Replay QA Leaderboard

Automated bug-scan leaderboard for [Hot App Summer](https://hotappsummer.netlify.app) submissions, powered by [Replay QA](https://loop-qa.replay.io).

## How it works

1. **`scraper.py`** runs daily at 8am, fetches new submissions from the Hot App Summer API, creates Replay QA projects for each app, and polls for scan results.
2. Results are written to `state.json` and embedded into `public/index.html` as inline JSON so the leaderboard works on any static host.
3. **`public/`** is the deployable site — push to Netlify (or any static host) to publish.

## Project structure

```
public/
  index.html   # Leaderboard UI (self-contained, data embedded inline)
  data.json    # Latest scan results (also embedded in index.html)
scraper.py     # Daily automation script
state.json     # Scraper state — not committed (see .gitignore)
```

## Setup

```bash
# Install dependencies
pip install requests

# Set your Replay QA token
export REPLAY_TOKEN=your_token_here

# Run manually
python3 scraper.py
```

## Deploy

The `public/` folder is the site root. Connect this repo to Netlify and set the publish directory to `public`.
