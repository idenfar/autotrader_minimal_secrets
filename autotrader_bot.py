#!/usr/bin/env python3
"""
AutoTrader notifier – minimal GitHub-Actions edition.
 • Reads SEARCH_URL and creds from environment variables (GitHub secrets)
 • Sends Gmail + Twilio alerts for every brand-new listing
 • Saves full HTML and all images of each new listing to ./archives/<id>/
 • Appends new IDs to seen_listings.json so you never get duplicate alerts
"""

import json, os, re, smtplib, sys, time, requests
from email.message import EmailMessage
from pathlib import Path
from typing import List
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
CARD_HREF_CSS   = "a.result-item"        # <- change this selector if AT.ca updates layout
ID_REGEX        = re.compile(r"-([0-9]+)\.htm")  # pulls numeric id from listing URL
# ----------------------------------------- #

def load_seen() -> set:
    if SEEN_PATH.exists():
        return set(json.loads(SEEN_PATH.read_text()))
    return set()

def save_seen(seen: set):
    SEEN_PATH.write_text(json.dumps(sorted(seen)))
    
def fetch_listings() -> List[dict]:
    """Return list of {'id', 'url', 'title'} dicts found on SEARCH_URL."""
    r = requests.get(SEARCH_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    listings = []
    for a in soup.select(CARD_HREF_CSS):
        url = requests.compat.urljoin(SEARCH_URL, a.get("href") or "")
        mid = ID_REGEX.search(url)
        if not mid:
            continue
        listing_id = mid.group(1)
        title = (a.get_text(strip=True) or "AutoTrader Listing").replace("\n", " ")
        listings.append({"id": listing_id, "url": url, "title": title})
    return listings

def send_email(subject: str, body: str):
    if not (GMAIL_USER and GMAIL_PASSWORD):
        print("✖ Email skipped (missing Gmail creds)")
        return
    msg = EmailMessage()
    msg["From"] = GMAIL_USER
    msg["To"]   = GMAIL_USER      # self-send; Gmail will still forward filters/etc
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
        body=body[:1600]  # SMS max
    )
    print("📱  SMS sent")

def archive_listing(lst: dict):
    """Save HTML + images under archives/<id>/"""
    folder = ARCHIVE_DIR / lst["id"]
    if folder.exists():
        return
    folder.mkdir(parents=True, exist_ok=True)

    res = requests.get(lst["url"], headers=HEADERS, timeout=30)
    res.raise_for_status()
    html_path = folder / "page.html"
    html_path.write_text(res.text, encoding="utf-8")

    soup = BeautifulSoup(res.text, "html.parser")
    img_urls = [img["src"] for img in soup.select("img") if img.get("src", "").startswith("http")]
    for i, img_url in enumerate(img_urls[:15], 1):
        try:
            img = requests.get(img_url, headers=HEADERS, timeout=30)
            with open(folder / f"image_{i}.jpg", "wb") as f:
                f.write(img.content)
        except Exception as e:
            print("Image error:", e)

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
        sys.exit("Missing SEARCH_URL env var")
    seen = load_seen()
    new_listings = [l for l in fetch_listings() if l["id"] not in seen]

    if not new_listings:
        print("No new listings 🙂")
        return

    for lst in new_listings:
        # 1. notifications
        body = f"{lst['title']}\n{lst['url']}"
        send_email(f"[AutoTrader] New listing {lst['id']}", body)
        send_sms(body)

        # 2. archive
        archive_listing(lst)

        # 3. mark as seen
        seen.add(lst["id"])

    save_seen(seen)
    print(f"✔ Done. {len(new_listings)} new listings processed.")

if __name__ == "__main__":
    main()
