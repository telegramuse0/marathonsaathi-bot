import os, re, json, time, subprocess, textwrap
import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont

BASE = "https://marathonmitra.com"
CITIES = ["kolkata", "siliguri", "durgapur", "darjeeling"]
HEAD = {"User-Agent": "MarathonSaathiBot/1.0 (facts only, source credited)"}
DRY = os.environ.get("DRY_RUN", "true").lower() == "true"
TEST_ONE = os.environ.get("TEST_ONE", "false").lower() == "true"
FB = "https://graph.facebook.com/v26.0"
IG = "https://graph.instagram.com/v26.0"
REPO = os.environ.get("GITHUB_REPOSITORY", "")
BRANCH = os.environ.get("GITHUB_REF_NAME", "main")
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
MON = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"


def get(url):
    r = requests.get(url, headers=HEAD, timeout=30)
    r.raise_for_status()
    return r.text


def list_events():
    found = {}
    for c in CITIES:
        try:
            html = get(f"{BASE}/city/{c}")
        except Exception as e:
            print("skip", c, e)
            continue
        for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
            m = re.match(r"^(?:https://marathonmitra\.com)?/events/([a-z0-9\-]+)/?$", a["href"])
            if m:
                found[m.group(1)] = f"{BASE}/events/{m.group(1)}"
        time.sleep(2)
    return found


def details(url):
    soup = BeautifulSoup(get(url), "html.parser")
    og = soup.find("meta", property="og:title")
    title = (og["content"] if og and og.get("content") else (soup.title.string if soup.title else "")).strip()
        title = re.split(r"\s*\|", title)[0]
    title = re.sub(r"\s+in\s+(Kolkata|Siliguri|Durgapur|Darjeeling|Howrah|Asansol)\s*$", "", title, flags=re.I).strip(" .-")
    d = soup.find("meta", property="og:description")
    desc = d["content"] if d and d.get("content") else ""
    text = desc + " " + soup.get_text(" ", strip=True)[:1500]
    dm = re.search(rf"\b(\d{{1,2}}\s+(?:{MON})[a-z]*\s+\d{{4}}|(?:{MON})[a-z]*\s+\d{{1,2}},?\s+\d{{4}})", text)
    dist = []
    for x in re.findall(r"\b(\d{1,2}(?:\.\d)?\s?K\b|Half Marathon|Full Marathon)", text):
        if x not in dist:
            dist.append(x)
    return {"title": title, "date": dm.group(1) if dm else "", "dist": ", ".join(dist[:6])}


def make_poster(info, slug):
    W = H = 1080
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        d.line([(0, y), (W, y)], fill=(11, 60 + y // 14, 46 + y // 16))
    d.text((70, 70), "MARATHON SAATHI", font=ImageFont.truetype(BOLD, 40), fill="#ffd54a")
    size, width = 88, 16
    lines = textwrap.wrap(info["title"].upper(), width)
    if len(lines) > 4:
        size, width = 66, 22
        lines = textwrap.wrap(info["title"].upper(), width)[:5]
    f = ImageFont.truetype(BOLD, size)
    y = 200
    for ln in lines:
        d.text((70, y), ln, font=f, fill="white")
        y += size + 14
    small = ImageFont.truetype(REG, 46)
    if info["date"]:
        d.text((70, y + 40), "Date: " + info["date"], font=small, fill="#ffd54a")
        y += 70
    if info["dist"]:
        y += 40
        for ln in textwrap.wrap("Distance: " + info["dist"], 30)[:4]:
            d.text((70, y), ln, font=small, fill="white")
            y += 60
    d.text((70, H - 110), "Registration link in caption", font=ImageFont.truetype(REG, 36), fill="#cfe8dc")
    path = f"posters/{slug}.png"
    img.save(path)
    return path


def make_caption(info, url):
    lines = [info["title"]]
    if info["date"]:
        lines.append("Date: " + info["date"])
    if info["dist"]:
        lines.append("Distance: " + info["dist"])
    lines += ["", "Registration & details: " + url,
              "Source: MarathonMitra. Please confirm on the official page before registering.",
              "", "#Marathon #Running #Kolkata #WestBengal #MarathonSaathi"]
    return "\n".join(lines)


def git_push(msg):
    for c in (["git", "config", "user.name", "marathon-bot"],
              ["git", "config", "user.email", "bot@users.noreply.github.com"],
              ["git", "add", "-A"]):
        subprocess.run(c, check=True)
    if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode:
        subprocess.run(["git", "commit", "-m", msg], check=True)
        subprocess.run(["git", "push"], check=True)


def post_fb(path, cap):
    with open(path, "rb") as f:
        r = requests.post(f"{FB}/{os.environ['FB_PAGE_ID']}/photos",
                          data={"caption": cap, "access_token": os.environ["FB_PAGE_TOKEN"]},
                          files={"source": f}, timeout=60)
    print("FB", r.status_code, r.text[:200])
    r.raise_for_status()


def post_ig(img_url, cap):
    tok, uid = os.environ["IG_TOKEN"], os.environ["IG_USER_ID"]
    r = requests.post(f"{IG}/{uid}/media",
                      data={"image_url": img_url, "caption": cap, "access_token": tok}, timeout=60)
    print("IG create", r.status_code, r.text[:200])
    r.raise_for_status()
    cid = r.json()["id"]
    for _ in range(10):
        s = requests.get(f"{IG}/{cid}", params={"fields": "status_code", "access_token": tok}, timeout=30).json()
        if s.get("status_code") == "FINISHED":
            break
        time.sleep(5)
    r = requests.post(f"{IG}/{uid}/media_publish",
                      data={"creation_id": cid, "access_token": tok}, timeout=60)
    print("IG publish", r.status_code, r.text[:200])
    r.raise_for_status()


def main():
    seen = json.load(open("seen.json")) if os.path.exists("seen.json") else []
    events = list_events()
    print("events found:", len(events))
    if not events:
        return
    if not seen and not TEST_ONE:
        json.dump(sorted(events), open("seen.json", "w"))
        print("First run: purane events save kiye, kuch post nahi hua.")
        return
    new = list(events)[:1] if TEST_ONE else [s for s in events if s not in seen]
    os.makedirs("posters", exist_ok=True)
    os.makedirs("drafts", exist_ok=True)
    for slug in new[:3]:
        url = events[slug]
        info = details(url)
        img = make_poster(info, slug)
        cap = make_caption(info, url)
        open(f"drafts/{slug}.txt", "w").write(cap)
        ok = DRY
        if not DRY:
            git_push(f"poster {slug}")
            img_url = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/{img}"
            for _ in range(12):
                if requests.head(img_url, timeout=20).status_code == 200:
                    break
                time.sleep(5)
            for fn, arg in ((post_fb, img), (post_ig, img_url)):
                try:
                    fn(arg, cap)
                    ok = True
                except Exception as e:
                    print("POST FAIL", fn.__name__, e)
        if ok and not TEST_ONE:
            seen.append(slug)
    if not TEST_ONE:
        json.dump(seen, open("seen.json", "w"))


main()
