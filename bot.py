"""Find Indian running events and send their original artwork to Telegram."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "MarathonSaathiBot/2.0 (+event discovery; contact: repo owner)"}
TIMEOUT = 25
SEEN_FILE = Path(os.environ.get("SEEN_FILE", "seen.json"))

# Add a source here to extend coverage. Each URL must be a public event-listing page.
SOURCES = [
    {"name": "MarathonMitra", "url": "https://marathonmitra.com/city/kolkata", "host": "marathonmitra.com", "paths": ("/events/",)},
    {"name": "Townscript", "url": "https://www.townscript.com/in/india/marathons", "host": "townscript.com", "paths": ("/e/", "/event/",)},
    {"name": "India Running", "url": "https://www.indiarunning.com/events", "host": "indiarunning.com", "paths": ("/event/", "/events/",)},
    {"name": "MySamay", "url": "https://mysamay.in/", "host": "mysamay.in", "paths": ("/event/", "/events/",)},
    {"name": "fstr", "url": "https://fstr.in/events", "host": "fstr.in", "paths": ("/events/",)},
    {"name": "RunnersDuniya", "url": "https://runnersduniya.com/", "host": "runnersduniya.com", "paths": ("/event/", "/events/",)},
    {"name": "MarathonTracks", "url": "https://www.marathontracks.com/", "host": "marathontracks.com", "paths": ("/race/", "/event/", "/marathon/",)},
]


@dataclass(frozen=True)
class Event:
    key: str
    title: str
    event_url: str
    registration_url: str
    image_url: str
    source: str


def get(url: str) -> str:
    response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    return response.text


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower().removeprefix("www."), parsed.path.rstrip("/"), "", "", ""))


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
        if len(parsed.path.strip("/").split("/")) < 2:
            continue
        links.add(normalize_url(href))
    return sorted(links)


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
    image = meta("og:image", "twitter:image")
    if image:
        image = urljoin(url, image)
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
    normalized_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    normalized_title = re.sub(r"[^a-z0-9]+", " ", normalized_title).strip()
    key = hashlib.sha256(normalized_title.encode()).hexdigest()
    return Event(key, title, url, reg, image, source["name"])


def scan_sources() -> list[Event]:
    found: dict[str, Event] = {}
    for source in SOURCES:
        try:
            # Bound work per source so one large catalogue cannot exhaust the runner.
            links = event_links(source, get(source["url"]))[:50]
            print(f"{source['name']}: {len(links)} event links")
            for link in links:
                try:
                    event = event_from_page(source, link)
                    if event:
                        found.setdefault(event.key, event)
                except Exception as exc:
                    print(f"Skip {link}: {exc}")
                time.sleep(0.15)
        except Exception as exc:
            print(f"Source unavailable ({source['name']}): {exc}")
    return list(found.values())


def load_seen() -> set[str]:
    try:
        data = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
        return set(data if isinstance(data, list) else data.keys())
    except FileNotFoundError:
        return set()


def send_telegram(event: Event) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    caption = event.registration_url
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
    events = scan_sources()
    print(f"Unique events with original image and registration link: {len(events)}")
    if os.environ.get("DRY_RUN", "true").lower() == "true":
        for event in events:
            print(json.dumps(asdict(event), ensure_ascii=False))
        return 0
    for event in events:
        if event.key in seen:
            continue
        try:
            send_telegram(event)
            seen.add(event.key)
            print(f"Sent: {event.title}")
        except Exception as exc:
            print(f"Send failed ({event.title}): {exc}")
    SEEN_FILE.write_text(json.dumps(sorted(seen), indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
