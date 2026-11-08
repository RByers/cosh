"""Chrome Releases security fixes, joined to the commits that fixed them.

  python3 scripts/chrome_releases.py fetch     # Blogger JSON feed, 2020 on (serial, >= 2 s apart)
  python3 scripts/chrome_releases.py parse     # -> security_fixes.json
  python3 scripts/chrome_releases.py join      # -> fixing_commits.json + summary.json (offline)
  python3 scripts/chrome_releases.py all

Data goes to $COSH_DATA_DIR/chrome_releases (default: the main checkout's
data/private). Raw feed pages are kept as fetched, losslessly
(docs/storage-design.md §3.8); rerunning `fetch` only asks for pages it
lacks, or for everything with --refresh. Post bodies are untrusted web
content: they are parsed with regexes and never shown to a model.
"""

import argparse
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from cosh import store  # noqa: E402

OUT = os.path.join(store.DATA_DIR, "chrome_releases")
RAW = os.path.join(OUT, "raw")
FEED = ("https://chromereleases.googleblog.com/feeds/posts/default?alt=json"
        "&published-min=2020-01-01T00:00:00&orderby=published&max-results=150&start-index={start}")
UA = "Mozilla/5.0 (X11; Linux x86_64) cosh-research"
SHARED = os.path.expanduser("~/projects/shared/chromium")
GAP = 2.0


def fetch(refresh=False):
    os.makedirs(RAW, exist_ok=True)
    start, page = 1, 0
    while True:
        path = os.path.join(RAW, f"page-{page:04d}.json")
        if os.path.exists(path) and not refresh:
            body = open(path, "rb").read()
        else:
            req = urllib.request.Request(FEED.format(start=start), headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read()
            with open(path, "wb") as f:
                f.write(body)
            print(f"page {page}: {len(body):,} bytes", file=sys.stderr)
            time.sleep(GAP)
        n = len(json.loads(body)["feed"].get("entry", []))
        if n == 0:
            break
        start += n
        page += 1
    print(f"{page} pages, {start - 1} posts", file=sys.stderr)


class _Text(HTMLParser):
    """Visible text of a post, one line per block element."""
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4"}

    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)

    def text(self):
        return re.sub(r"[ \t\xa0]+", " ", "".join(self.parts))


# Two layouts: "[$7000][40012345] High CVE-2024-1234: Use after free in Foo. Reported by X on
# 2024-01-02" (prose posts), and "40012345 High CVE-2024-1234 Use after free in Foo" (table rows).
FIX = re.compile(
    r"(?:\[(?P<reward>[^\]\n]{0,24})\]\s*)?\[?(?P<bug>\d{5,10})\]?\s+(?P<sev>Critical|High|Medium|Low)\s+"
    r"(?P<cve>CVE-\d{4}-\d{3,7})\s*:?\s*(?P<title>[^\n]*?)(?:\.\s*|\s+)"
    r"(?:Reported by\s+(?P<who>[^\n]*?))?(?:\s+on\s+(?P<on>\d{4}-\d{2}-\d{2}))?\s*(?:\n|$)")


def parse():
    fixes, posts = [], 0
    for name in sorted(os.listdir(RAW)):
        for e in json.load(open(os.path.join(RAW, name))).get("feed", {}).get("entry", []):
            posts += 1
            p = _Text()
            p.feed(e.get("content", {}).get("$t", ""))
            text = html.unescape(p.text())
            labels = [c["term"] for c in e.get("category", [])]
            link = next((x["href"] for x in e.get("link", []) if x.get("rel") == "alternate"), None)
            ver = re.search(r"\b(\d{2,3}\.0\.\d{4}\.\d+)", text)
            for m in FIX.finditer(text):
                fixes.append(dict(
                    bug=int(m["bug"]), cve=m["cve"], severity=m["sev"], title=m["title"].strip()[:200],
                    reward=(m["reward"] or "").strip(), reporter=(m["who"] or "").strip()[:200], reported_on=m["on"],
                    post=e["title"]["$t"], published=e["published"]["$t"][:10], labels=labels,
                    version=ver.group(1) if ver else None, url=link))
    # A CVE is often listed in several posts (desktop, Android, ChromeOS, extended stable):
    # keep the first (earliest) listing per CVE, with every post it appeared in.
    by_cve = {}
    for f in sorted(fixes, key=lambda f: f["published"]):
        x = by_cve.setdefault(f["cve"], dict(f, posts=[]))
        x["posts"].append(dict(post=f["post"], published=f["published"], url=f["url"]))
    out = sorted(by_cve.values(), key=lambda f: (f["published"], f["cve"]))
    for f in out:
        for k in ("post", "url"):
            f.pop(k)
    json.dump(out, open(os.path.join(OUT, "security_fixes.json"), "w"), indent=1)
    print(f"{posts} posts, {len(fixes)} fix lines, {len(out)} distinct CVEs, "
          f"{len({f['bug'] for f in out})} bug ids", file=sys.stderr)


def git(*args, input=None):
    return subprocess.run(["git", "-C", SHARED, *args], input=input, capture_output=True, text=True,
                          check=True, env={**os.environ, "GIT_NO_LAZY_FETCH": "1"},
                          errors="replace").stdout


BUGLINE = re.compile(r"^(Bug|Fixed):\s*(.+)$", re.M)


def bug_ids(body):
    out = set()
    for m in BUGLINE.finditer(body):
        for t in re.split(r"[,\s]+", m.group(2)):
            mm = re.fullmatch(r"(?:chromium:)?(\d{5,10})", t.strip())
            if mm:
                out.add(int(mm.group(1)))
    return out


def join():
    fixes = json.load(open(os.path.join(OUT, "security_fixes.json")))
    by_bug = defaultdict(list)
    for f in fixes:
        by_bug[f["bug"]].append(f)
    # Streamed, and only the Bug/Fixed trailers: whole messages since 2019 don't fit in memory
    # on a shared box.
    p = subprocess.Popen(
        ["git", "-C", SHARED, "log", "main", "--first-parent", "--since=2019-06-01",
         "--format=%H%x01%aI%x01%s%x01%(trailers:key=Bug,key=Fixed,valueonly,separator=%x2C)%x02"],
        stdout=subprocess.PIPE, text=True, errors="replace", env={**os.environ, "GIT_NO_LAZY_FETCH": "1"})
    commits, buf = [], ""
    for chunk in iter(lambda: p.stdout.read(1 << 20), ""):
        buf += chunk
        *recs, buf = buf.split("\x02")
        for rec in recs:
            if "\x01" not in rec:
                continue
            sha, at, subj, ids = rec.strip("\n").split("\x01", 3)
            hit = bug_ids("Bug: " + ids.replace("\n", ",")) & by_bug.keys()
            if hit:
                commits.append(dict(sha=sha, at=at[:10], revert=subj.startswith("Revert "),
                                    reland=subj.lower().startswith("reland"), bugs=sorted(hit)))
    if p.wait():
        raise RuntimeError("git log failed")
    # Each fixing commit's top-level and 2-level directory, by changed lines.
    stat = git("log", "--no-walk=unsorted", "--stdin", "--no-renames", "--numstat", "--format=%x01%H",
               input="".join(c["sha"] + "\n" for c in commits))
    dirs = {}
    for chunk in stat.split("\x01")[1:]:
        lines = chunk.strip("\n").split("\n")
        acc = Counter()
        for ln in lines[1:]:
            parts = ln.split("\t")
            if len(parts) == 3:
                a, d, path = parts
                n = (int(a) if a.isdigit() else 0) + (int(d) if d.isdigit() else 0) + 1
                segs = path.split("/")
                acc["/".join(segs[:2]) + "/" if len(segs) > 2 else (segs[0] + "/" if len(segs) > 1 else "(root)/")] += n
        if acc:
            dirs[lines[0]] = acc.most_common(1)[0][0]
    for c in commits:
        c["dir2"] = dirs.get(c["sha"])
        c["dir1"] = c["dir2"].split("/")[0] + "/" if c["dir2"] and c["dir2"] != "(root)/" else c["dir2"]
        sev = [f["severity"] for b in c["bugs"] for f in by_bug[b]]
        c["severity"] = min(sev, key=["Critical", "High", "Medium", "Low"].index)
        c["cves"] = sorted({f["cve"] for b in c["bugs"] for f in by_bug[b]})
    json.dump(commits, open(os.path.join(OUT, "fixing_commits.json"), "w"), indent=1)

    matched = {b for c in commits for b in c["bugs"]}
    year = lambda d: d[:4]
    summary = dict(
        cves=len(fixes), bugs=len(by_bug), bugs_with_commit=len(matched),
        fixing_commits=len(commits), reverts=sum(c["revert"] for c in commits),
        relands=sum(c["reland"] for c in commits),
        cves_by_year={y: dict(Counter(f["severity"] for f in fixes if year(f["published"]) == y))
                      for y in sorted({year(f["published"]) for f in fixes})},
        matched_share_by_year={y: round(sum(1 for f in fixes if year(f["published"]) == y and f["bug"] in matched)
                                        / max(1, sum(1 for f in fixes if year(f["published"]) == y)), 3)
                               for y in sorted({year(f["published"]) for f in fixes})},
        commits_by_dir1=dict(Counter(c["dir1"] for c in commits).most_common(25)),
        commits_by_dir2=dict(Counter(c["dir2"] for c in commits).most_common(30)),
        severity_by_dir1={d: dict(Counter(c["severity"] for c in commits if c["dir1"] == d))
                          for d, _ in Counter(c["dir1"] for c in commits).most_common(12)},
    )
    json.dump(summary, open(os.path.join(OUT, "summary.json"), "w"), indent=1)
    print(json.dumps(summary, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fetch", "parse", "join", "all"])
    ap.add_argument("--refresh", action="store_true", help="refetch pages already on disk")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    if a.cmd in ("fetch", "all"):
        fetch(a.refresh)
    if a.cmd in ("parse", "all"):
        parse()
    if a.cmd in ("join", "all"):
        join()


if __name__ == "__main__":
    main()
