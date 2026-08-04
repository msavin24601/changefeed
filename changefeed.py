#!/usr/bin/env python3
"""Fetch Claude Code and Cursor changelogs, send new entries to Telegram."""

import html
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

STATE_PATH = Path(__file__).parent / "data" / "state.json"

CLAUDE_CODE_FEED_URL = (
    "https://raw.githubusercontent.com/anthropics/claude-code/main/feed.xml"
)
CURSOR_RSS_URL = "https://www.cursor.com/changelog/rss.xml"
GITHUB_RSS_URL = "https://github.blog/changelog/feed/"

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Telegram's hard limit is 4096 characters per message; leave headroom.
MAX_MESSAGE_LEN = 4000


def load_state():
    state = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}
    state.setdefault("claude_code", {}).setdefault("last_id", None)
    state.setdefault("cursor", {}).setdefault("last_link", None)
    state.setdefault("github", {}).setdefault("last_link", None)
    return state


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n")


def fetch_claude_code_entries():
    """Return [(id, title, link, [bullet, ...]), ...] newest first."""
    resp = requests.get(CLAUDE_CODE_FEED_URL, timeout=30)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)

    entries = []
    for entry in root.findall("atom:entry", ATOM_NS):
        entry_id = entry.findtext("atom:id", default="", namespaces=ATOM_NS).strip()
        title = entry.findtext("atom:title", default="", namespaces=ATOM_NS).strip()
        link_el = entry.find("atom:link", ATOM_NS)
        link = link_el.get("href") if link_el is not None else ""
        content = entry.findtext("atom:content", default="", namespaces=ATOM_NS)
        bullets = [
            re.sub(r"^[•\-]\s*", "", html.unescape(p)).strip()
            for p in re.findall(r"<p>(.*?)</p>", content, flags=re.DOTALL)
        ]
        entries.append((entry_id, title, link, bullets))
    return entries


def clean_rss_description(raw):
    text = html.unescape(raw or "")
    text = re.sub(r"<[^>]+>", " ", text)  # strip HTML tags
    text = re.sub(r"\s+", " ", text).strip()
    # Strip WordPress's "The post X appeared first on Y." boilerplate (github.blog feed)
    text = re.sub(r"\s*The post .* appeared first on .*\.$", "", text).strip()
    return text


def fetch_rss_entries(url):
    """Return [(title, link, description), ...] newest first, for a standard RSS 2.0 feed."""
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)

    entries = []
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        description = clean_rss_description(item.findtext("description"))
        entries.append((title, link, description))
    return entries


def fetch_cursor_entries():
    return fetch_rss_entries(CURSOR_RSS_URL)


def fetch_github_entries():
    return fetch_rss_entries(GITHUB_RSS_URL)


def new_claude_code_entries(entries, last_id):
    if last_id is None:
        return []  # first run: baseline only, don't spam history
    new = []
    for entry_id, title, link, bullets in entries:
        if entry_id == last_id:
            break
        new.append((entry_id, title, link, bullets))
    return new


def new_rss_entries(entries, last_link):
    if last_link is None:
        return []
    new = []
    for title, link, description in entries:
        if link == last_link:
            break
        new.append((title, link, description))
    return new


def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    resp = requests.post(
        url,
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    if not resp.ok:
        raise RuntimeError(f"Telegram API error {resp.status_code}: {resp.text}")


def split_long_text(text, max_len):
    """Split text into chunks <= max_len, breaking at whitespace where possible."""
    chunks = []
    while len(text) > max_len:
        split_at = text.rfind(" ", 0, max_len)
        if split_at <= 0:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip()
    if text:
        chunks.append(text)
    return chunks or [""]


def chunk_lines(header, lines, footer, max_len=MAX_MESSAGE_LEN):
    """Group header+lines+footer into Telegram-sized messages.

    The header repeats on every chunk (so each message stands alone); the
    footer (link) is appended only to the last chunk.
    """
    chunks = []
    current = [header]
    current_len = len(header)
    for line in lines:
        line_len = len(line) + 1  # + newline
        if current_len + line_len > max_len and len(current) > 1:
            chunks.append(current)
            current = [header]
            current_len = len(header)
        current.append(line)
        current_len += line_len
    chunks.append(current)
    chunks[-1].append(footer)
    return ["\n".join(c) for c in chunks]


def format_claude_code_message(title, link, bullets):
    """Return a list of Telegram-ready message chunks for one release."""
    header = f"<b>{html.escape(title)}</b>"
    lines = []
    for bullet in bullets:
        line = f"- {html.escape(bullet)}"
        lines.extend(split_long_text(line, MAX_MESSAGE_LEN - len(header) - 1))
    return chunk_lines(header, lines, link)


def format_rss_message(source_label, title, link, description):
    """Return a list of Telegram-ready message chunks for one feed item."""
    header = f"<b>{html.escape(source_label)}: {html.escape(title)}</b>"
    lines = split_long_text(html.escape(description), MAX_MESSAGE_LEN - len(header) - 1) if description else []
    return chunk_lines(header, lines, link)


def main():
    dry_run = "--dry-run" in sys.argv

    state = load_state()

    claude_code_entries = fetch_claude_code_entries()
    cursor_entries = fetch_cursor_entries()
    github_entries = fetch_github_entries()

    new_cc = new_claude_code_entries(claude_code_entries, state["claude_code"]["last_id"])
    new_cursor = new_rss_entries(cursor_entries, state["cursor"]["last_link"])
    new_github = new_rss_entries(github_entries, state["github"]["last_link"])

    cc_messages = []
    for entry_id, title, link, bullets in reversed(new_cc):
        cc_messages.extend(format_claude_code_message(title, link, bullets))

    cursor_messages = []
    for title, link, description in reversed(new_cursor):
        cursor_messages.extend(format_rss_message("Cursor", title, link, description))

    github_messages = []
    for title, link, description in reversed(new_github):
        github_messages.extend(format_rss_message("GitHub", title, link, description))

    # Each source is sent and checkpointed independently: a failure in one
    # (e.g. Telegram rejects a message) doesn't block or re-send the others.
    sources = [
        ("claude_code", claude_code_entries, cc_messages, "last_id", lambda e: e[0]),
        ("cursor", cursor_entries, cursor_messages, "last_link", lambda e: e[1]),
        ("github", github_entries, github_messages, "last_link", lambda e: e[1]),
    ]

    sent_total = 0
    had_failure = False
    for source_key, entries, messages, state_field, id_of in sources:
        try:
            if dry_run:
                for m in messages:
                    print(m)
                    print("---")
            else:
                for m in messages:
                    send_telegram_message(m)
                    sent_total += 1
            if entries:
                state[source_key][state_field] = id_of(entries[0])
        except Exception as exc:
            had_failure = True
            print(f"Failed to send {source_key} digest: {exc}", file=sys.stderr)

    total_messages = len(cc_messages) + len(cursor_messages) + len(github_messages)
    if total_messages == 0:
        print("No new entries.")
    elif dry_run:
        print(f"Would send {total_messages} message(s) (see above).")
    else:
        print(f"Sent {sent_total}/{total_messages} message(s).")

    if not dry_run:
        save_state(state)

    if had_failure:
        sys.exit(1)


if __name__ == "__main__":
    main()
