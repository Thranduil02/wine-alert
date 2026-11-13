#!/usr/bin/env python3
"""Daily check for 'buy 6, save 25%' wine offers at Tesco and Sainsbury's.

Two independent signals per retailer:
  1. The retailer's own wine pages (text match). May be blocked by bot protection.
  2. winedrinker.co.uk RSS (recent posts naming the retailer and 25%). Robust fallback.
Sends a push via ntfy.sh when an offer is newly detected.
"""
import json, os, re, sys, urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
import xml.etree.ElementTree as ET

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")  # secret, hard-to-guess string
STATE = Path(os.environ.get("STATE_FILE", "state.json"))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# CONFIRM these URLs in a browser; edit freely.
RETAILER_PAGES = {
    "Tesco": ["https://www.tesco.com/groceries/en-GB/shop/drinks/wine/all"],
    "Sainsbury's": ["https://www.sainsburys.co.uk/shop/gb/groceries/drinks/wine"],
}
RSS = "https://winedrinker.co.uk/category/25-off-wine/feed/"
PATTERN = re.compile(r"buy\s*(any\s*)?(6|six)(\s*or\s*more)?\W{0,3}\s*save\s*25\s*%", re.I)
RSS_MAX_AGE = timedelta(days=7)  # these promotions typically last about a week


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-GB"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def check_pages(name, text_by_url):
    """Return True/False if decidable, None if every page failed."""
    ok = [t for t in text_by_url.values() if t]
    if not ok:
        return None
    return any(PATTERN.search(t) for t in ok)


def check_rss(xml_text, name, now):
    root = ET.fromstring(xml_text)
    key = name.replace("'", "").lower()
    for item in root.iter("item"):
        title = (item.findtext("title") or "")
        if key in title.replace("'", "").replace("’", "").lower() and "25%" in title:
            try:
                when = parsedate_to_datetime(item.findtext("pubDate"))
            except Exception:
                continue
            if now - when <= RSS_MAX_AGE:
                return True
    return False


def notify(msg):
    if not NTFY_TOPIC:
        print("NOTIFY (no topic set):", msg)
        return
    req = urllib.request.Request(f"https://ntfy.sh/{NTFY_TOPIC}", data=msg.encode(),
                                 headers={"Title": "Wine offer", "Tags": "wine_glass"})
    urllib.request.urlopen(req, timeout=30)


def main():
    now = datetime.now(timezone.utc)
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    try:
        rss = fetch(RSS)
    except Exception as e:
        print("RSS failed:", e); rss = None

    for name, urls in RETAILER_PAGES.items():
        texts = {}
        for u in urls:
            try: texts[u] = fetch(u)
            except Exception as e: print(f"{name} page failed: {u}: {e}"); texts[u] = ""
        page = check_pages(name, texts)
        feed = check_rss(rss, name, now) if rss else None
        on = bool(page) or bool(feed)
        print(f"{name}: page={page} feed={feed} -> {'ON' if on else 'off'}")

        was_on = state.get(name, {}).get("on", False)
        if on and not was_on:
            src = "retailer site" if page else "winedrinker.co.uk"
            notify(f"{name}: buy 6, save 25% on wine looks to be ON (via {src}).")
        state[name] = {"on": on, "checked": now.isoformat(timespec="minutes")}

        # Tell him once if both signals are dead, so silence never means 'broken'
        dead = page is None and feed is None
        if dead and not state[name].get("dead_notified"):
            notify(f"Wine checker: could not read any source for {name}. Needs a look.")
            state[name]["dead_notified"] = True
        elif not dead:
            state[name]["dead_notified"] = False

    STATE.write_text(json.dumps(state, indent=2))


def selftest():
    assert PATTERN.search("Buy 6 or more, Save 25% Clubcard Price")
    assert PATTERN.search("buy any 6, save 25%")
    assert not PATTERN.search("Buy 3, save 25%")
    now = datetime(2026, 11, 13, tzinfo=timezone.utc)
    xml = ("<rss><channel><item><title>25% Off Wine at Sainsbury’s</title>"
           "<pubDate>Wed, 11 Nov 2026 09:00:00 +0000</pubDate></item></channel></rss>")
    assert check_rss(xml, "Sainsbury's", now) and not check_rss(xml, "Tesco", now)
    print("selftest ok")


if __name__ == "__main__":
    selftest() if "--selftest" in sys.argv else main()
