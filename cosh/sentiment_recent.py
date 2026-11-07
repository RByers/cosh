"""Detail for fully scored weeks on the Review Tone page: summaries/sentiment_recent.json
(comments by committers), plus .everyone.json and .noncommitters.json.

  python3 -m cosh.sentiment_people collect --week 2026-W37:2026-W44   # rows with identities
  python3 -m cosh.sentiment score --week 2026-W37:2026-W44            # every comment
  python3 -m cosh.sentiment_recent --week 2026-W37:2026-W44

It writes, for those weeks:
  - an overview, a week-by-week table and the score distribution;
  - every comment flagged as AI friction, anonymously (text, month and the
    writer's role), after a sandboxed screen drops any that identify anyone;
  - "who makes whom happy": the CL authors who draw glowing comments from
    many different reviewers, and the reviewers who draw them from many
    different authors, over all the weeks and over the last four.

Ground rule 5 (docs/plan.md): the page names people only for praise. The
happy tables give each person's counts of counterparts and of happy
counterparts, never a mean or anything negative.
"""

import os
import sys
import time
from collections import defaultdict

from . import sentiment as S
from . import store

OUT = os.path.join(os.path.dirname(S.SUMMARY), "sentiment_recent.json")
MIN_COUNTERPARTS = 6        # distinct counterparts to appear in a happy table
TOP = 100                   # rows kept per happy table
MONTH_WEEKS = 4             # "past month": the last four weeks
AI_CHARS = 600              # longer AI-friction comments are left out
SCREEN_BATCH = 30


def load(weeks, data_dir=store.DATA_DIR, version=None):
    """(rows, scores, missing, n_trivial): substantive scored rows of the
    weeks, each with its week."""
    scores = S.load_scores(None, data_dir, version)
    rows, missing, n_trivial = [], 0, 0
    for w in weeks:
        for r in S.read_jsonl(os.path.join(S.out_dir(data_dir), f"comments-{w}.jsonl")):
            if r["id"] not in scores:
                missing += 1
            elif S.TRIVIAL.match(r["text"]):
                n_trivial += 1
            else:
                r["week"] = w
                rows.append(r)
    return rows, scores, missing, n_trivial


def _stats(v):
    n = len(v)
    s = [x[0] for x in v]
    return dict(n=n, mean=round(sum(s) / n, 4) if n else None,
                glowing=round(sum(x >= S.GLOWING for x in s) / n, 4) if n else None,
                angry=round(sum(x <= S.ANGRY for x in s) / n, 4) if n else None,
                ai=sum(1 for x in v if x[1]))


def overview(rows, scores, weeks):
    """Totals, one row per week, and the share of comments per 0.1 of score."""
    allv = [scores[r["id"]] for r in rows]
    by = defaultdict(list)
    for r in rows:
        by[r["week"]].append(scores[r["id"]])
    dist = defaultdict(int)
    for s, _, _ in allv:
        dist[round(s, 1)] += 1
    return dict(total=_stats(allv), weekly=[dict(week=w, **_stats(by[w])) for w in weeks],
                dist=sorted([b, n] for b, n in dist.items()))


def _kind(r):
    return S._target_kind(r)


def happy(rows, scores, top=TOP):
    """Who draws glowing comments from many different counterparts.
    authors: CL owners, from reviewers' comments aimed at them; reviewers:
    reviewers, from CL owners' replies to them. Each row: name, email,
    counterparts (distinct people who wrote to them that way) and happy (how
    many of those wrote at least one glowing comment)."""
    names = {}
    for r in rows:
        names[r["author"]] = (r.get("author_name"), r.get("author_email"))
        if _kind(r) == "person" and r.get("target") not in (None, -1):
            names[r["target"]] = (r.get("target_name"), r.get("target_email"))

    def table(pick):
        to = defaultdict(lambda: defaultdict(float))
        for r in rows:
            if pick(r):
                s = scores[r["id"]][0]
                prev = to[r["target"]].get(r["author"])
                to[r["target"]][r["author"]] = s if prev is None else max(prev, s)
        out = []
        for p, by in to.items():
            if len(by) < MIN_COUNTERPARTS:
                continue
            hits = sum(1 for s in by.values() if s >= S.GLOWING)
            if not hits:
                continue
            name, email = names.get(p, (None, None))
            if not email:
                continue
            out.append(dict(name=name or email, email=email, counterparts=len(by), happy=hits))
        out.sort(key=lambda x: (-x["happy"], -x["happy"] / x["counterparts"], x["name"]))
        return out[:top]

    person = lambda r: _kind(r) == "person" and r.get("target") not in (None, -1)
    return dict(
        authors=table(lambda r: person(r) and r["author_role"] == "REVIEWER" and r["target"] == r.get("owner")),
        reviewers=table(lambda r: person(r) and r["author_role"] == "AUTHOR" and r["target"] != r.get("owner")))


def ai_comments(rows, scores, sandbox):
    """Every AI-friction comment that a sandboxed screen finds nothing
    identifying in, as text, month and the writer's role only."""
    pool = [r for r in rows if scores[r["id"]][1] and len(r["text"]) <= AI_CHARS
            and not S._LINKY.search(r["text"])]
    pool.sort(key=lambda r: r["written_at"])
    kept = []
    for b in range(0, len(pool), SCREEN_BATCH):
        chunk = pool[b:b + SCREEN_BATCH]
        keys = {f"C{j}": r for j, r in enumerate(chunk)}
        flagged = S.screen_identifying([(k, r["text"]) for k, r in keys.items()], sandbox)
        kept += [r for k, r in keys.items() if k not in flagged]
    out = [dict(text=r["text"], month=r["written_at"][:7], role="author" if r["author_role"] == "AUTHOR" else "reviewer")
           for r in kept]
    return out, len(pool) - len(kept), sum(1 for r in rows if scores[r["id"]][1]) - len(pool)


def build(weeks, data_dir=store.DATA_DIR, version=None, sandbox="auto", authors=S.DEFAULT_AUTHORS):
    """The page's detail for comments written by `authors` (S.AUTHORS)."""
    rows, scores, missing, n_trivial = load(weeks, data_dir, version)
    if rows and "author" not in rows[0]:
        raise SystemExit("these comment files have no identities: collect them with "
                         "`python3 -m cosh.sentiment_people collect`")
    rows = S.by_authors(rows, authors, data_dir)
    month = weeks[-MONTH_WEEKS:]
    box = S.make_sandbox(sandbox, data_dir) if isinstance(sandbox, str) else sandbox
    try:
        ai, screened_out, too_long = ai_comments(rows, scores, box)
    finally:
        if box is not sandbox:
            box.close()
    return dict(generated_at=store.now_iso(), prompt=version or S.PROMPT_VERSION, weeks=[weeks[0], weeks[-1]],
                authors=authors, month_weeks=[month[0], month[-1]], thresholds=dict(glowing=S.GLOWING, angry=S.ANGRY),
                min_counterparts=MIN_COUNTERPARTS, missing=missing, n_trivial=n_trivial,
                **overview(rows, scores, weeks),
                happy=dict(all=happy(rows, scores), month=happy([r for r in rows if r["week"] in month], scores)),
                ai=ai, ai_left_out=dict(screened=screened_out, long_or_linked=too_long))


def main(argv):
    import argparse
    import json
    ap = argparse.ArgumentParser(prog="python3 -m cosh.sentiment_recent")
    ap.add_argument("--week", required=True, help="fully scored weeks, e.g. 2026-W37:2026-W44")
    ap.add_argument("--prompt", default=None)
    ap.add_argument("--sandbox", choices=["auto", "bwrap", "none"], default="auto")
    ap.add_argument("--authors", choices=S.AUTHORS + ("all",), default="all",
                    help="whose comments count; 'all' writes one file for each")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    if a.out and a.authors == "all":
        ap.error("--out needs one --authors group")
    for g in (S.AUTHORS if a.authors == "all" else (a.authors,)):
        t0 = time.time()
        doc = build(S.weeks_in(a.week), version=a.prompt, sandbox=a.sandbox, authors=g)
        out = a.out or S.authors_path(OUT, g)
        with open(out, "w") as f:
            json.dump(doc, f, indent=1, ensure_ascii=False)
            f.write("\n")
        print(f"{g}: {doc['total']['n']} comments, {len(doc['ai'])} AI-friction comments shown "
              f"({doc['ai_left_out']}), {doc['missing']} unscored -> {out} ({time.time() - t0:.0f}s)", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1:])
