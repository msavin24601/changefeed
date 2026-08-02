# changefeed

Daily Telegram digest of new Claude Code and Cursor releases.

- Claude Code: parses the official Atom feed at
  [`feed.xml`](https://github.com/anthropics/claude-code/blob/main/feed.xml)
  in the `anthropics/claude-code` repo (one entry per release).
- Cursor: parses the official RSS feed at
  [`cursor.com/changelog/rss.xml`](https://www.cursor.com/changelog/rss.xml).

A small `data/state.json` file (committed back to the repo by the workflow)
tracks the last entry seen for each source, so you're only notified about
what's new. The very first run just baselines silently — it won't dump the
whole history on you.

## Setup

### 1. Create a Telegram bot

1. Open Telegram and message [@BotFather](https://t.me/BotFather).
2. Send `/newbot` and follow the prompts (pick any name/username).
3. BotFather replies with a token that looks like
   `123456789:AAExampleTokenValueHere`. Save it — this is `TELEGRAM_BOT_TOKEN`.

### 2. Get your chat ID

1. Send any message to your new bot (e.g. "hi").
2. Visit `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser,
   replacing `<TOKEN>` with your bot token.
3. Find `"chat":{"id":...}` in the JSON response — that number is
   `TELEGRAM_CHAT_ID`.

### 3. Push this repo to GitHub

If you're starting from this folder locally:

```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```

### 4. Add repo secrets

In the GitHub repo: **Settings → Secrets and variables → Actions → New
repository secret**. Add:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

### 5. Enable and run

Actions run automatically once enabled, daily at 08:00 UTC (edit the cron
expression in [`.github/workflows/digest.yml`](.github/workflows/digest.yml)
to change the time). You can also trigger a run immediately from the
**Actions** tab via "Run workflow" to test it end-to-end.

## Running locally

```bash
pip install -r requirements.txt
python changefeed.py --dry-run   # prints what would be sent, doesn't touch Telegram or state.json
python changefeed.py             # requires TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID env vars, updates data/state.json
```
