"""Phone-friendly, token-protected source editor and scanner preview."""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import bot

ROOT = Path(__file__).resolve().parent
SOURCES_FILE = ROOT / "sources.json"
PAGE_FILE = ROOT / "admin.html"
bot.SOURCES_FILE = SOURCES_FILE
bot.SOURCES = bot.load_sources()


def valid_source(value: dict) -> dict:
    name = str(value.get("name", "")).strip()
    url = str(value.get("url", "")).strip()
    parsed = urlparse(url)
    if not name or len(name) > 80:
        raise ValueError("Name is required (up to 80 characters).")
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Listing URL must start with http:// or https://.")
    host = str(value.get("host") or parsed.hostname).lower().removeprefix("www.").strip()
    if parsed.hostname.lower().removeprefix("www.") != host and not parsed.hostname.lower().endswith("." + host):
        raise ValueError("Allowed host must match the listing URL domain.")
    paths = value.get("paths", [])
    if isinstance(paths, str):
        paths = [part.strip() for part in paths.splitlines() if part.strip()]
    paths = [str(path).strip() for path in paths if str(path).strip()]
    if not paths or any(not path.startswith("/") for path in paths):
        raise ValueError("Add at least one event path prefix, starting with /.")
    registration_hosts = value.get("registration_hosts", [])
    if isinstance(registration_hosts, str):
        registration_hosts = [part.strip() for part in registration_hosts.splitlines() if part.strip()]
    clean = {"name": name, "url": url, "host": host, "paths": paths}
    registration_hosts = [str(h).lower().strip() for h in registration_hosts if str(h).strip()]
    if registration_hosts:
        clean["registration_hosts"] = registration_hosts
    if value.get("allow_empty"):
        clean["allow_empty"] = True
    return clean


def read_sources() -> list[dict]:
    return json.loads(SOURCES_FILE.read_text(encoding="utf-8"))


class Handler(BaseHTTPRequestHandler):
    server_version = "MarathonSaathiAdmin/1.0"

    def respond(self, code: int, payload, content_type: str = "application/json; charset=utf-8"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def authorized(self) -> bool:
        expected = "Bearer " + self.server.admin_token
        if secrets.compare_digest(self.headers.get("Authorization", ""), expected):
            return True
        self.respond(401, {"error": "Enter the access code shown in the server window."})
        return False

    def read_json(self) -> dict:
        length = min(int(self.headers.get("Content-Length", "0")), 100_000)
        value = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(value, dict):
            raise ValueError("Request must be a JSON object.")
        return value

    def do_GET(self):
        if self.path == "/":
            self.respond(200, PAGE_FILE.read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/sources":
            if self.authorized():
                self.respond(200, {"sources": read_sources()})
        else:
            self.respond(404, {"error": "Not found"})

    def do_POST(self):
        if not self.authorized():
            return
        try:
            data = self.read_json()
            if self.path == "/api/source":
                source = valid_source(data)
                sources = read_sources()
                index = next((i for i, item in enumerate(sources) if item.get("name", "").casefold() == source["name"].casefold()), None)
                if index is None:
                    sources.append(source)
                    action = "added"
                else:
                    sources[index] = source
                    action = "updated"
                SOURCES_FILE.write_text(json.dumps(sources, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                bot.SOURCES = sources
                self.respond(200, {"message": f"{source['name']} {action}. Changes are saved in sources.json."})
                return
            if self.path == "/api/source/delete":
                name = str(data.get("name", "")).strip()
                sources = [s for s in read_sources() if s.get("name", "").casefold() != name.casefold()]
                if len(sources) == len(read_sources()):
                    raise ValueError("Source not found.")
                SOURCES_FILE.write_text(json.dumps(sources, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                bot.SOURCES = sources
                self.respond(200, {"message": f"Removed {name}. Changes are saved in sources.json."})
                return
            if self.path == "/api/publish":
                root = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
                branch = subprocess.run(["git", "branch", "--show-current"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
                if Path(root).resolve() != ROOT.resolve():
                    raise ValueError("Open the editor from the marathonsaathi-bot repository folder.")
                if branch != "main":
                    raise ValueError("This Codespace is on '" + branch + "'. Open a Codespace on main to publish the source list.")
                changed = subprocess.run(["git", "diff", "--quiet", "--", "sources.json"], cwd=ROOT)
                if changed.returncode == 0:
                    self.respond(200, {"message": "No unpublished source changes."})
                    return
                subprocess.run(["git", "add", "--", "sources.json"], cwd=ROOT, check=True, capture_output=True, text=True)
                commit = subprocess.run(["git", "commit", "--only", "-m", "Update scanner sources", "--", "sources.json"], cwd=ROOT, capture_output=True, text=True)
                if commit.returncode:
                    raise ValueError("Could not create the config commit. Check the Codespace Git identity.")
                push = subprocess.run(["git", "push", "origin", "main"], cwd=ROOT, capture_output=True, text=True)
                if push.returncode:
                    raise ValueError("Commit created, but GitHub push failed. Check Codespace Git access and retry from its terminal.")
                self.respond(200, {"message": "Published sources.json to main. GitHub Actions will run a scan-only check."})
                return
            if self.path == "/api/preview":
                source = valid_source(data)
                listing_html = bot.get(source["url"])
                links = bot.event_links(source, listing_html)[:12]
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(listing_html, "html.parser")
                cards = [event for anchor in soup.find_all("a", href=True) if (event := bot._card_event(source, anchor, source["url"]))]
                events = {event.key: event for event in cards}
                for link in links[:8]:
                    try:
                        event = bot.event_from_page(source, link)
                        if event:
                            events.setdefault(event.key, event)
                    except Exception:
                        continue
                self.respond(200, {"event_links": links, "events": [asdict(e) for e in list(events.values())[:12]], "message": f"Found {len(links)} event page links and {len(events)} usable events."})
                return
            self.respond(404, {"error": "Not found"})
        except Exception as exc:
            self.respond(400, {"error": str(exc)})

    def log_message(self, fmt, *args):
        print("Admin:", fmt % args)


def main():
    parser = argparse.ArgumentParser(description="Edit event sources and preview scanner results from your phone.")
    parser.add_argument("--host", default="127.0.0.1", help="Use 0.0.0.0 only on a trusted home Wi-Fi network to connect from your phone.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--token", default="", help="Optional access code; one is generated if omitted.")
    args = parser.parse_args()
    token = args.token or secrets.token_urlsafe(24)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.admin_token = token
    print(f"Marathon Saathi editor: http://{args.host}:{args.port}")
    print(f"Access code: {token}")
    print("Stop the editor with Ctrl+C. Keep the access code private.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Editor stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
