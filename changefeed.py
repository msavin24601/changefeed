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

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"claude_code": {"last_id": None}, "cursor": {"last_link": None}}


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


def fetch_cursor_entries():
    """Return [(title, link, description), ...] newest first, as published in the feed."""
    resp = requests.get(CURSOR_RSS_URL, timeout=30)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)

    entries = []
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        description = html.unescape((item.findtext("description") or "").strip())
        entries.append((title, link, description))
    return entries


def new_claude_code_entries(entries, last_id):
    if last_id is None:
        return []  # first run: baseline only, don't spam history
    new = []
    for entry_id, title, link, bullets in entries:
        if entry_id == last_id:
            break
        new.append((entry_id, title, link, bullets))
    return new


def new_cursor_entries(entries, last_link):
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
    resp.raise_for_status()


def format_claude_code_message(title, link, bullets):
    lines = [f"<b>{html.escape(title)}</b>"]
    for bullet in bullets:
        lines.append(f"- {html.escape(bullet)}")
    lines.append(link)
    return "\n".join(lines)


def format_cursor_message(title, link, description):
    lines = [f"<b>Cursor: {html.escape(title)}</b>"]
    if description:
        lines.append(html.escape(description))
    lines.append(link)
    return "\n".join(lines)


def main():
    dry_run = "--dry-run" in sys.argv

    state = load_state()

    claude_code_entries = fetch_claude_code_entries()
    cursor_entries = fetch_cursor_entries()

    new_cc = new_claude_code_entries(claude_code_entries, state["claude_code"]["last_id"])
    new_cursor = new_cursor_entries(cursor_entries, state["cursor"]["last_link"])

    messages = []
    # Send oldest-first so the digest reads chronologically
    for entry_id, title, link, bullets in reversed(new_cc):
        messages.append(format_claude_code_message(title, link, bullets))
    for title, link, description in reversed(new_cursor):
        messages.append(format_cursor_message(title, link, description))

    if not messages:
        print("No new entries.")
    elif dry_run:
        print(f"Would send {len(messages)} message(s):\n")
        for m in messages:
            print(m)
            print("---")
    else:
        for m in messages:
            send_telegram_message(m)
        print(f"Sent {len(messages)} message(s).")

    if claude_code_entries:
        state["claude_code"]["last_id"] = claude_code_entries[0][0]
    if cursor_entries:
        state["cursor"]["last_link"] = cursor_entries[0][1]

    if not dry_run:
        save_state(state)


if __name__ == "__main__":
    main()
