#!/usr/bin/env python3
"""
AutoTrader notifier – GitHub-Actions edition (secrets-based)

• Reads SEARCH_URL + credentials from environment variables (GitHub secrets)
• Detects *brand-new* listings, sends Gmail + Twilio alerts
• Archives full HTML + images of each new listing under ./archives/<id>/
• Remembers seen IDs in seen_listings.json to avoid duplicates
"""

import json
import os
import re
import smtplib
import sys
import time
from email.message import EmailMessage
from pathlib import Path
from typing import List

import requests
from bs4 import BeautifulSoup
from twilio.rest import Client

# ---------- CONFIG ---------- #
SEARCH_URL      = os.getenv("SEARCH_URL")
GMAIL_USER      = os.getenv("GMAIL_USER")
GMAIL_PASSWORD  = os.getenv("GMAIL_APP_PASSWORD")
TWILIO_SID      = os.getenv("TWILIO_SID")
TWILIO_TOKEN    = os.getenv("TWILIO_TOKEN")
TWILIO_FROM     = os.getenv("TWILIO_FROM")
TWILIO_TO       = os.getenv("TWILIO_TO")

ARCHIVE_DIR     = Path("archives")
SEEN_PATH       = Path("seen_listings.json")
HEADERS         = {"User-Agent": "Mozilla/5.0 (compatible; AutoTraderBot/1.0)"}

# Flexible selector & regex that work with old and new URL formats
CARD_HREF_CSS   = "a[href*='/a/']"                 # any listing link contains “…/a/…”
ID_REGEX        = re.compile(r'[_/-]([0-9]{6,})')  # captures long numeric ID
# ----------------------------------------- #


def load_seen() -> set:
    """Return previously seen IDs as a set."""
    if SEEN_PATH.exists():
        return set(json.loads(SEEN_PATH.read_text()))
    return set()


def save_seen(seen: set):
    SEEN_PATH.write_text(json.dumps(sorted(seen)))


def fetch_listings() -> List[dict]:
    """
    Scrape SEARCH_URL and return UNIQUE listings as
    [{'id','url','title'}, …].  Dedupes multiple <a> tags that
    belong to the same card.
    """
    res = requests.get(SEARCH_URL, headers=HEADERS, timeout=30)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")

    unique = {}  # id  -> dict

    for a in soup.select(CARD_HREF_CSS):
        url = requests.compat.urljoin(SEARCH_URL, a.get("href", ""))
        m   = ID_REGEX.search(url)
        if not m:
            continue
        lid = m.group(1)
        if lid in unique:          # same listing already captured
            continue
        title = a.get_text(" ", strip=True) or "AutoTrader Listing"
        unique[lid] = {"id": lid, "url": url, "title": title}

    print(f"Found {len(unique)} unique listing link(s) on page.")
    return list(unique.values())


def send_email(subject: str, body: str):
    if not (GMAIL_USER and GMAIL_PASSWORD):
        print("✖ Email skipped (missing Gmail creds)")
        return
    msg = EmailMessage()
    msg["From"] = GMAIL_USER
    msg["To"]   = GMAIL_USER
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(GMAIL_USER, GMAIL_PASSWORD)
        smtp.send_message(msg)
    print("📧  Email sent")


def send_sms(body: str):
    if not (TWILIO_SID and TWILIO_TOKEN and TWILIO_FROM and TWILIO_TO):
        print("✖ SMS skipped (missing Twilio creds)")
        return
    Client(TWILIO_SID, TWILIO_TOKEN).messages.create(
        from_=TWILIO_FROM,
        to=TWILIO_TO,
        body=body[:1600]
    )
    print("📱  SMS sent")


def archive_listing(lst: dict):
    """
    Save listing HTML + images under archives/<id>/ .
    If directory already exists, skip (listing was archived earlier).
    """
    folder = ARCHIVE_DIR / lst["id"]
    if folder.exists():
        return
    folder.mkdir(parents=True, exist_ok=True)

    # Save HTML
    res = requests.get(lst["url"], headers=HEADERS, timeout=30)
    res.raise_for_status()
    (folder / "page.html").write_text(res.text, encoding="utf-8")

    # Save up to 15 images
    soup = BeautifulSoup(res.text, "html.parser")
    img_urls = [img["src"] for img in soup.select("img") if img.get("src", "").startswith("http")]
    for i, img_url in enumerate(img_urls[:15], 1):
        try:
            img = requests.get(img_url, headers=HEADERS, timeout=30)
            with open(folder / f"image_{i}.jpg", "wb") as f:
                f.write(img.content)
        except Exception as e:
            print("Image fetch error:", e)

    # Metadata
    meta = {
        "id": lst["id"],
        "url": lst["url"],
        "title": lst["title"],
        "saved": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    (folder / "metadata.json").write_text(json.dumps(meta, indent=2))

    print(f"💾 Archived {lst['id']}")


def main():
    if not SEARCH_URL:
        sys.exit("Environment variable SEARCH_URL is missing.")

    seen = load_seen()
    new_listings = [l for l in fetch_listings() if l["id"] not in seen]

    if not new_listings:
        print("No new listings 🙂")
        return

    for lst in new_listings:
        body = f"{lst['title']}\n{lst['url']}"
        try:
            send_email(f"[AutoTrader] New listing {lst['id']}", body)
        except Exception as e:
            print("Email error:", e)
        send_sms(body)
        archive_listing(lst)
        seen.add(lst["id"])

    save_seen(seen)
    print(f"✔ Done. {len(new_listings)} new listing(s) processed.")


if __name__ == "__main__":
    main()
