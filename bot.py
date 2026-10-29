"""Find Indian running events and send their original artwork to Telegram."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "MarathonSaathiBot/2.0 (+event discovery; contact: repo owner)"}
TIMEOUT = 25
MAX_SEND_PER_RUN = 5
SEEN_FILE = Path(os.environ.get("SEEN_FILE", "seen.json"))

# Add a source here to extend coverage. Listing and detail URL patterns are per-site.
SOURCES = [
    {"name": "MarathonMitra", "url": "https://marathonmitra.com/city/kolkata", "host": "marathonmitra.com", "paths": ("/events/",)},
    {"name": "India Running", "url": "https://www.indiarunning.com/city/Kolkata", "host": "indiarunning.com", "paths": ("/event/", "/events/"), "registration_hosts": ("registrations.indiarunning.com",)},
    {"name": "MySamay", "url": "https://www.mysamay.in/public/events", "host": "mysamay.in", "paths": ("/e/", "/event/info/"), "allow_empty": True},
    {"name": "fstr", "url": "https://fstr.in/", "host": "fstr.in", "paths": ("/event/",)},
    {"name": "RunnersDuniya", "url": "https://runnersduniya.com/", "host": "runnersduniya.com", "paths": ("/event/", "/events/")},
    {"name": "MarathonTracks", "url": "https://marathontracks.com/marathons.php", "host": "marathontracks.com", "paths": ("/details.php",)},
    {"name": "runINDIA", "url": "https://www.runindia.in/events", "host": "runindia.in", "paths": ("/events/",)},
]
SCAN_ERRORS: list[str] = []


@dataclass(frozen=True)
class Event:
    key: str
    title: str
    event_url: str
    registration_url: str
    image_url: str
    source: str
    date: str = ""


def get(url: str) -> str:
    response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    return response.text


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower().removeprefix("www."), parsed.path.rstrip("/"), parsed.params, parsed.query, ""))


def event_links(source: dict, html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = set()
    for anchor in soup.find_all("a", href=True):
        href = urljoin(source["url"], anchor["href"])
        parsed = urlparse(href)
        host = parsed.netloc.lower().removeprefix("www.")
        if host != source["host"] and not host.endswith("." + source["host"]):
            continue
        if not any(parsed.path.lower().startswith(path) for path in source["paths"]):
            continue
        if parsed.path.lower().endswith(".php"):
            if not parsed.query:
                continue
        elif len(parsed.path.strip("/").split("/")) < 2:
            continue
        links.add(normalize_url(href))
    return sorted(links)


def _image_url(node, page_url: str) -> str:
    image = node.find("img")
    if not image:
        return ""
    return urljoin(page_url, image.get("src") or image.get("data-src") or image.get("data-lazy-src") or "")


def _original_event_image(soup, title: str, page_url: str) -> str:
    """Prefer OG artwork, then an event image whose alt text identifies the race."""
    for attr, value in (("property", "og:image"), ("name", "twitter:image")):
        tag = soup.find("meta", attrs={attr: value})
        if tag and tag.get("content", "").strip():
            return urljoin(page_url, tag["content"].strip())
    title_words = {word.lower() for word in re.findall(r"[a-z0-9]{4,}", title)}
    candidates = []
    for image in soup.find_all("img"):
        alt = (image.get("alt") or image.get("title") or "").lower()
        src = image.get("src") or image.get("data-src") or image.get("data-lazy-src") or ""
        if not src or re.search(r"logo|avatar|icon|profile|placeholder", alt + " " + src, re.I):
            continue
        words = set(re.findall(r"[a-z0-9]{4,}", alt))
        if title_words and words.intersection(title_words):
            candidates.append(src)
    return urljoin(page_url, candidates[0]) if candidates else ""


def _event_date(text: str) -> str:
    match = re.search(r"\b(?:\d{1,2}\s+[A-Za-z]{3,9}\.?[,]?\s+\d{4}|[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{4})\b", text)
    return match.group(0) if match else ""


def _card_event(source: dict, anchor, listing_url: str) -> Event | None:
    href = urljoin(listing_url, anchor.get("href", ""))
    host = urlparse(href).netloc.lower().removeprefix("www.")
    if host not in source.get("registration_hosts", ()):
        return None
    label = anchor.get_text(" ", strip=True).lower()
    if not re.search(r"register|registration|book\s*now", label):
        return None
    card = anchor
    for _ in range(7):
        if not getattr(card, "parent", None):
            break
        card = card.parent
        if card.find(["h1", "h2", "h3", "h4"]) and card.find("img"):
            break
    heading = card.find(["h1", "h2", "h3", "h4"])
    title = heading.get_text(" ", strip=True) if heading else ""
    image = _image_url(card, listing_url)
    date_text = card.get_text(" ", strip=True)
    detail_url = ""
    for detail_anchor in card.find_all("a", href=True):
        detail_href = urljoin(listing_url, detail_anchor["href"])
        detail_parsed = urlparse(detail_href)
        detail_host = detail_parsed.netloc.lower().removeprefix("www.")
        if detail_host == source.get("host") and any(detail_parsed.path.lower().startswith(path) for path in source.get("paths", ())):
            detail_url = normalize_url(detail_href)
            break
    # Never link to the whole listing page. Prefer the event detail page; if
    # the card has none, use its event-specific registration URL.
    return _make_event(source, title, detail_url or normalize_url(href), href, image, date_text)


def _make_event(source: dict, title: str, event_url: str, registration_url: str, image_url: str, date_text: str = "") -> Event | None:
    title = re.split(r"\s+[|–—]\s+", title, maxsplit=1)[0].strip()
    if not title or not image_url or not registration_url:
        return None
    clean_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    clean_title = re.sub(r"[^a-z0-9]+", " ", clean_title).strip()
    event_date = _event_date(date_text)
    identity = f"{clean_title}|{event_date.lower()}"
    key = hashlib.sha256(identity.encode()).hexdigest()
    return Event(key, title, normalize_url(event_url), normalize_url(registration_url), image_url, source["name"], event_date)


def event_from_page(source: dict, url: str) -> Event | None:
    soup = BeautifulSoup(get(url), "html.parser")
    def meta(*names: str) -> str:
        for name in names:
            node = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
            if node and node.get("content", "").strip():
                return node["content"].strip()
        return ""

    title = meta("og:title", "twitter:title") or (soup.title.get_text(" ", strip=True) if soup.title else "")
    title = re.split(r"\s+[|–—]\s+", title, maxsplit=1)[0].strip()
    image = _original_event_image(soup, title, url)
    # Registration must be a real link; do not substitute an event/listing page.
    reg = ""
    for a in soup.find_all("a", href=True):
        label = a.get_text(" ", strip=True).lower()
        href = urljoin(url, a["href"])
        if re.search(r"register|registration|sign\s*up|book\s*now", label) and urlparse(href).scheme in ("http", "https"):
            reg = normalize_url(href)
            break
    if not title or not image or not reg:
        return None
    page_text = soup.get_text(" ", strip=True)
    return _make_event(source, title, url, reg, image, page_text)


def scan_sources() -> list[Event]:
    SCAN_ERRORS.clear()
    found: dict[str, Event] = {}
    for source in SOURCES:
        try:
            # Bound work per source so one large catalogue cannot exhaust the runner.
            html = get(source["url"])
            soup = BeautifulSoup(html, "html.parser")
            links = event_links(source, html)[:50]
            card_events = [e for a in soup.find_all("a", href=True) if (e := _card_event(source, a, source["url"]))]
            before = len(found)
            for event in card_events:
                found.setdefault(event.key, event)
            for link in links:
                try:
                    event = event_from_page(source, link)
                    if event:
                        found.setdefault(event.key, event)
                except Exception as exc:
                    print(f"Skip {link}: {exc}")
                time.sleep(0.15)
            added = len(found) - before
            print(f"{source['name']}: {len(links)} event pages, {len(card_events)} registration cards, {added} usable events")
            if not links and not card_events:
                print(f"WARNING: {source['name']} listing has no event links right now")
                if not source.get("allow_empty", False):
                    SCAN_ERRORS.append(f"{source['name']}: no parseable event links")
        except Exception as exc:
            print(f"Source unavailable ({source['name']}): {exc}")
            SCAN_ERRORS.append(f"{source['name']}: {exc}")
    return list(found.values())


def load_seen() -> set[str]:
    try:
        data = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
        return set(data if isinstance(data, list) else data.keys())
    except FileNotFoundError:
        return set()


def is_upcoming(event: Event) -> bool:
    if not event.date:
        return False
    for fmt in ("%d %b %Y", "%d %b, %Y", "%d %B %Y", "%d %B, %Y", "%b %d, %Y", "%b %d %Y", "%B %d, %Y", "%B %d %Y", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(event.date, fmt).date() >= date.today()
        except ValueError:
            continue
    return False


def send_telegram(event: Event) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    caption = event.event_url or event.registration_url
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendPhoto",
        data={"chat_id": chat_id, "photo": event.image_url, "caption": caption},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram rejected event photo: {payload}")


def main() -> int:
    seen = load_seen()
    dry_run = os.environ.get("DRY_RUN", "true").lower() == "true"
    send_requested = os.environ.get("SEND_TELEGRAM_REQUESTED", "false").lower() == "true"
    missing_credentials = [name for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID") if not os.environ.get(name, "").strip()]
    events = scan_sources()
    print(f"Unique events with original image and registration link: {len(events)}")
    if SCAN_ERRORS:
        message = "Some sources could not be scanned: " + "; ".join(SCAN_ERRORS)
        if dry_run:
            print("WARNING: " + message + ". Scan-only run will continue.")
        else:
            print("ERROR: " + message + ". Telegram send cancelled to avoid a partial scan.")
            return 1
    if not dry_run:
        if missing_credentials:
            print("ERROR: Telegram send requested, but required GitHub Actions secrets are missing: " + ", ".join(missing_credentials))
            return 1
    if dry_run:
        if send_requested and missing_credentials:
            print("WARNING: Telegram secrets are missing, so this run stayed scan-only; no Telegram message was sent.")
        for event in events:
            print(json.dumps(asdict(event), ensure_ascii=False))
        return 0
    pending = [event for event in events if event.key not in seen and is_upcoming(event)]
    print(f"Upcoming, unseen events: {len(pending)}")
    batch = pending[:MAX_SEND_PER_RUN]
    if len(pending) > len(batch):
        print(f"Safety limit: sending at most {len(batch)} events this run; {len(pending) - len(batch)} remain for a later run.")
    failures = []
    for event in batch:
        try:
            send_telegram(event)
            seen.add(event.key)
            print(f"Sent: {event.title}")
        except Exception as exc:
            print(f"Send failed ({event.title}): {exc}")
            failures.append(event.title)
    SEEN_FILE.write_text(json.dumps(sorted(seen), indent=2) + "\n", encoding="utf-8")
    if failures:
        print(f"ERROR: {len(failures)} Telegram delivery attempt(s) failed.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

