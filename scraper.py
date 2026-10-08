"""Collects workshop / exhibition / media-news links and writes data.json.
Per source: use RSS if the page advertises one, otherwise pick topic-related links from the page.
data.json is rewritten only when something real changed, so Netlify does not redeploy for nothing."""
import json, re, hashlib, datetime as dt, xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlparse, unquote
import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
           "Accept-Language": "fa,en;q=0.8"}
TOPIC = re.compile(r"مستند|فیلم|سینما|عکس|عکاسی|تصویربرداری|فیلمبرداری|تدوین|فیلمنامه|کارگردانی|جشنواره|نمایشگاه|گالری|کارگاه|ورکشاپ")
WORKSHOP = re.compile(r"کارگاه|ورکشاپ|دوره|کلاس|ثبت.?نام|workshop")
EXHIBIT = re.compile(r"نمایشگاه|گالری|نگارخانه")
OLD_YEAR = re.compile(r"\b(139\d|140[0-3])\b")   # past Jalali years in title or url
DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
KEEP_DAYS, REFRESH_DAYS, MAX_ITEMS = 28, 7, 600
TODAY = dt.date.today()

def fix(s):
    """Arabic ي/ك -> Persian ی/ک (many Iranian sites still use the Arabic forms)."""
    return s.replace("ي", "ی").replace("ك", "ک")

def fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=25)
    r.raise_for_status()
    if not r.encoding or r.encoding.lower() == "iso-8859-1":
        r.encoding = r.apparent_encoding
    return r.text

def kind_of(text, default):
    if EXHIBIT.search(text): return "exhibition"
    if WORKSHOP.search(text): return "workshop"
    return default if default in ("workshop", "exhibition", "news") else "other"

def from_rss(feed_url):
    r = requests.get(feed_url, headers=HEADERS, timeout=25)
    r.raise_for_status()
    out = []
    for it in ET.fromstring(r.content).iter("item"):
        title = fix((it.findtext("title") or "").strip())
        link = (it.findtext("link") or "").strip()
        if title and link.startswith("http"):
            out.append((title, link))
    return out

def from_html(html, base):
    soup = BeautifulSoup(html, "html.parser")
    host = urlparse(base).netloc.replace("www.", "")
    seen, out = set(), []
    for a in soup.find_all("a", href=True):
        text = fix(a.get_text(" ", strip=True))
        if not (14 <= len(text) <= 160) or not TOPIC.search(text):
            continue
        url = urljoin(base, a["href"]).split("#")[0]
        if not url.startswith("http") or host not in urlparse(url).netloc or url in seen:
            continue
        seen.add(url)
        out.append((text, url))
    return out, soup

def collect(src):
    pairs, soup = from_html(fetch(src["url"]), src["url"])
    feed = soup.find("link", attrs={"type": re.compile("rss|atom")})
    if feed and feed.get("href"):
        try:
            rss = [p for p in from_rss(urljoin(src["url"], feed["href"])) if TOPIC.search(p[0])]
            pairs = rss or pairs
        except Exception:
            pass
    return pairs

def signature(d):
    return json.dumps([d.get("items"), [(s["name"], s["status"]) for s in d.get("sources", [])]],
                      sort_keys=True, ensure_ascii=False)

def main():
    try:
        with open("data.json", encoding="utf-8") as f:
            old = json.load(f)
    except Exception:
        old = {}
    items = {i["id"]: i for i in old.get("items", [])}
    report = []
    with open("sources.json", encoding="utf-8") as f:
        sources = json.load(f)
    for src in sources:
        try:
            kept = 0
            for title, url in collect(src):
                if OLD_YEAR.search((title + " " + unquote(url)).translate(DIGITS)):
                    continue
                iid = hashlib.sha1(url.encode()).hexdigest()[:12]
                if iid in items:
                    last = dt.date.fromisoformat(items[iid]["last_seen"])
                    if (TODAY - last).days >= REFRESH_DAYS:
                        items[iid]["last_seen"] = TODAY.isoformat()
                else:
                    items[iid] = {"id": iid, "title": title, "url": url, "source": src["name"],
                                  "kind": kind_of(title, src.get("default_kind")),
                                  "first_seen": TODAY.isoformat(), "last_seen": TODAY.isoformat()}
                kept += 1
            report.append({"name": src["name"], "url": src["url"], "status": "ok", "count": kept})
        except Exception as e:
            report.append({"name": src["name"], "url": src["url"], "status": "error",
                           "error": str(e)[:120], "count": 0})
    cutoff = (TODAY - dt.timedelta(days=KEEP_DAYS)).isoformat()
    fresh = [i for i in items.values() if i["last_seen"] >= cutoff]
    fresh.sort(key=lambda i: (i["first_seen"], i["id"]), reverse=True)
    out = {"sources": report, "items": fresh[:MAX_ITEMS]}
    print(json.dumps(report, ensure_ascii=False, indent=1))
    if signature(out) == signature(old):
        print("no changes")
        return
    out["updated"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

if __name__ == "__main__":
    main()
