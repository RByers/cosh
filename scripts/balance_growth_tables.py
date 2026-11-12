"""Turn `balance_growth.py all` output into the page's datasets
growth_windows, newcomer_review, mentorship, promotion and ai_paired.
balance_growth prints tables for reading; this parser keeps the page
reproducible from them. `python3 -m cosh.balance_publish` calls
datasets() on balance_growth.page_tables(); to look at them by hand:

  python3 scripts/balance_growth.py all ... > out-growth.txt
  python3 scripts/balance_growth_tables.py out-growth.txt [--out datasets.json]
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cosh.balance_publish import show  # noqa: E402


def sections(text):
    out, cur = {}, None
    for line in text.splitlines():
        if line.startswith("== "):
            cur = line[3:]
            out[cur] = []
        elif cur is not None:
            out[cur].append(line)
    return out


def find(secs, prefix):
    for k, v in secs.items():
        if k.startswith(prefix):
            return v
    raise KeyError(prefix)


def pct(s):
    return round(int(s.rstrip("%")) / 100, 3)


def growth_windows(lines):
    rows, window, cols = [], None, []
    for line in lines:
        m = re.match(r"(\d{4}-\d{2}): people with", line)
        if m:
            window = m.group(1)
            continue
        if line.startswith("tenure at start"):
            cols = ["velocity", "size", "breadth", "reviewing", "indep_threads", "indep_ish", "indep_rounds"]
            continue
        m = re.match(r"(0-2y|2-5y|5y\+|new|all)\s+([\d,]+)\s+(\d+)%\s+(\d+)%(.*)$", line)
        if not (m and window):
            continue
        row = dict(window=window, tenure=m.group(1), people=int(m.group(2).replace(",", "")),
                   none_any=pct(m.group(3)), none_core4=pct(m.group(4)))
        for k, (v, n) in zip(cols, re.findall(r"(\d+)% \(\s*([\d,]+)\)", m.group(5))):
            row[k] = pct(v)
            row[k + "_n"] = int(n.replace(",", ""))
        rows.append(row)
    return rows


def newcomer_review(lines):
    rows = []
    for line in lines:
        m = re.match(r"(\d{4})\s+([\d,]+)\s+(\d+)%\s+(\d+)%\s+(\d+)%\s+(\d+)%\s+([\d,]+)\s+([\d.]+)\s+([\d.]+)%\s+([\d.]+)%", line)
        if m:
            g = m.groups()
            rows.append(dict(year=int(g[0]), approvals=int(g[1].replace(",", "")), lt2=pct(g[2]), y2_5=pct(g[3]),
                             y5_10=pct(g[4]), y10p=pct(g[5]), approvers=int(g[6].replace(",", "")),
                             per_approver=float(g[7]), share_of_all=round(float(g[8]) / 100, 3),
                             cross_org=round(float(g[9]) / 100, 3)))
    return rows


def mentorship(lines):
    rows = {}
    for line in lines:
        m = re.match(r"(\d{4})\s+(\d+)\s+(\d+)%( \(window open\))?$", line.strip())
        if m:
            y = int(m.group(1))
            rows[y] = dict(year=y, mentees=int(m.group(2)), became_mentors=pct(m.group(3)), open=bool(m.group(4)))
            continue
        m = re.match(r"\s*(\d{4}):\s+(\d+) mentors, median \d+ mentees, top 10% of mentors take (\d+)%", line)
        if m:
            y = int(m.group(1))
            rows.setdefault(y, dict(year=y, mentees=None, became_mentors=None, open=True))
            rows[y].update(mentors=int(m.group(2)), top10_share=pct(m.group(3)))
    return [rows[y] for y in sorted(rows)]


def promotion(lines):
    rows, years = [], [1, 2, 3, 5, 8]
    for line in lines:
        m = re.match(r"(\d{4})\s+([\d,]+)\s+(.*)$", line)
        if not m:
            continue
        cells = re.findall(r"(-|\d+%) /\s*(\d+)%", m.group(3))
        for y, (rv, ow) in zip(years, cells):
            rows.append(dict(cohort=int(m.group(1)), people=int(m.group(2).replace(",", "")), years=y,
                             reviewer=None if rv == "-" else pct(rv), owner=pct(ow)))
    return rows


def ai_paired(lines):
    rows = []
    for line in lines:
        m = re.match(r"\s+(.+?)\s+marked - unmarked = ([+-][\d.]+) \(95% CI ([+-][\d.]+) \.\. ([+-][\d.]+), n=(\d+)\)", line)
        if m:
            rows.append(dict(metric=m.group(1).strip(), diff=float(m.group(2)), lo=float(m.group(3)),
                             hi=float(m.group(4)), n=int(m.group(5))))
    return rows


def datasets(text):
    secs = sections(text)
    new = dict(
        growth_windows=growth_windows(find(secs, "Growth: per-person")),
        newcomer_review=newcomer_review(find(secs, "Who carries newcomer review")),
        mentorship=mentorship(find(secs, "Mentorship lineage")),
        promotion=promotion(find(secs, "Kaplan-Meier")),
        ai_paired=ai_paired(find(secs, "Same author, same quarter")),
    )
    for k, v in new.items():
        if not v:
            raise SystemExit(f"{k}: nothing parsed")
    return new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("text", help="what `balance_growth.py all` printed")
    ap.add_argument("--out", help="write the datasets here as JSON")
    args = ap.parse_args()
    show(datasets(open(args.text).read()), args.out)


if __name__ == "__main__":
    main()
