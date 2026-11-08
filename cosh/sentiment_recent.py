"""Detail for fully scored weeks on the Review Tone page: summaries/sentiment_recent.json
(comments by committers), plus .everyone.json and .noncommitters.json.

  python3 -m cosh.sentiment_people collect --week 2026-W37:2026-W44   # rows with identities
  python3 -m cosh.sentiment score --week 2026-W37:2026-W44            # every comment
  python3 -m cosh.sentiment_recent --week 2026-W37:2026-W44

It writes, for those weeks:
  - an overview, a week-by-week table and the score distribution;
  - the most negative comments flagged as AI friction, anonymously (text,
    month and the writer's role), after a sandboxed screen drops any that
    identify anyone;
  - "who makes whom happy": the CL authors who draw the most glowing
    comments from reviewers, and the reviewers who draw the most from
    authors, over all the weeks and over the last four.

Next to it, summaries/sentiment_comments.json (and its .everyone and
.noncommitters versions) holds the comments behind the praise and happy
boards, with names and Gerrit links, for the page's name popups. Only
praise and glowing comments go in it (ground rule 5).

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
COMMENTS_OUT = os.path.join(os.path.dirname(S.SUMMARY), "sentiment_comments.json")
MIN_COUNTERPARTS = 6        # distinct counterparts to appear in a happy table
TOP = 100                   # rows kept per happy table
MONTH_WEEKS = 4             # "past month": the last four weeks
AI_CHARS = 600              # longer AI-friction comments are left out
AI_SHOWN = 20               # the most negative AI-friction comments shown
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


def happy(rows, scores, top=TOP, ids=None):
    """Who draws the most glowing comments. authors: CL owners, from
    reviewers' comments aimed at them; reviewers: reviewers, from CL owners'
    replies to them. Each row: name, email, glowing (every glowing comment
    to them, repeats from one person included), happy (how many distinct
    people wrote those) and counterparts (distinct people who wrote to them
    that way at all). Ranked by glowing; only people with at least
    MIN_COUNTERPARTS counterparts are listed. If `ids` is a dict,
    ids[table][email] gets the ids of each listed person's glowing comments."""
    names = {}
    for r in rows:
        names[r["author"]] = (r.get("author_name"), r.get("author_email"))
        if _kind(r) == "person" and r.get("target") not in (None, -1):
            names[r["target"]] = (r.get("target_name"), r.get("target_email"))

    def table(pick, key):
        to = defaultdict(lambda: defaultdict(float))
        glowing = defaultdict(list)
        for r in rows:
            if pick(r):
                s = scores[r["id"]][0]
                prev = to[r["target"]].get(r["author"])
                to[r["target"]][r["author"]] = s if prev is None else max(prev, s)
                if s >= S.GLOWING:
                    glowing[r["target"]].append(r["id"])
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
            out.append(dict(name=name or email, email=email, glowing=len(glowing[p]), happy=hits, counterparts=len(by)))
        out.sort(key=lambda x: (-x["glowing"], -x["happy"], x["name"]))
        out = out[:top]
        if ids is not None:
            by_email = {names[p][1]: p for p in to if names.get(p, (None, None))[1]}
            ids[key] = {x["email"]: glowing[by_email[x["email"]]] for x in out}
        return out

    person = lambda r: _kind(r) == "person" and r.get("target") not in (None, -1)
    return dict(
        authors=table(lambda r: person(r) and r["author_role"] == "REVIEWER" and r["target"] == r.get("owner"),
                      "authors"),
        reviewers=table(lambda r: person(r) and r["author_role"] == "AUTHOR" and r["target"] != r.get("owner"),
                        "reviewers"))


def ai_comments(rows, scores, sandbox, n=AI_SHOWN, seed="2026-11"):
    """The `n` most negative AI-friction comments (lowest score first; ties
    by a deterministic shuffle) that a sandboxed screen finds nothing
    identifying in, as text, score, month and the writer's role only. Returns them,
    how many the screen dropped, and how many were too long or linked."""
    pool = [r for r in rows if scores[r["id"]][1] and len(r["text"]) <= AI_CHARS
            and not S._LINKY.search(r["text"])]
    order = {i: k for k, i in enumerate(S._draw([r["id"] for r in pool], seed))}
    pool.sort(key=lambda r: (scores[r["id"]][0], order[r["id"]]))
    kept, dropped = [], 0
    for b in range(0, len(pool), SCREEN_BATCH):
        if len(kept) >= n:
            break
        chunk = pool[b:b + SCREEN_BATCH]
        keys = {f"C{j}": r for j, r in enumerate(chunk)}
        flagged = S.screen_identifying([(k, r["text"]) for k, r in keys.items()], sandbox)
        dropped += len(flagged)
        kept += [r for k, r in keys.items() if k not in flagged]
    out = [dict(text=r["text"], score=scores[r["id"]][0], month=r["written_at"][:7],
                role="author" if r["author_role"] == "AUTHOR" else "reviewer") for r in kept[:n]]
    return out, dropped, sum(1 for r in rows if scores[r["id"]][1]) - len(pool)


def _record(r, scores):
    """One praise or glowing comment for a name popup: text, date, writer,
    recipient and a Gerrit link."""
    return dict(text=r["text"], date=r["written_at"][:10], week=r["week"], score=scores[r["id"]][0],
                writer=r.get("author_name") or r.get("author_email"), writer_email=r.get("author_email"),
                recipient=r.get("target_name") or r.get("target_email"), recipient_email=r.get("target_email"),
                url=S.comment_url(r["project"], r["cl"], r["uuid"]))


def person_comments(rows, scores, weeks, month):
    """The comments behind the praise boards (`praise`: every praise comment
    from one person to another, as on summaries/sentiment_praise.json) and
    the happy tables (`happy[period][table][email]`: each listed person's
    glowing comments). Only praise and glowing comments: never negative ones."""
    praise = [r for r in rows if S.is_praise(r, scores) and S._target_kind(r) == "person"
              and r.get("author_email") and r.get("target_email")]
    happy_ids = {}
    for period, rs in (("all", rows), ("month", [r for r in rows if r["week"] in month])):
        happy_ids[period] = {}
        happy(rs, scores, ids=happy_ids[period])
    wanted = {r["id"] for r in praise} | {i for p in happy_ids.values() for t in p.values() for v in t.values() for i in v}
    comments = {r["id"]: _record(r, scores) for r in rows if r["id"] in wanted}
    assert all(scores[i][0] >= S.GLOWING for i in comments), "only praise and glowing comments"
    return dict(weeks=[weeks[0], weeks[-1]], comments=comments, praise=sorted(r["id"] for r in praise),
                happy=happy_ids)


def build(weeks, data_dir=store.DATA_DIR, version=None, sandbox="auto", authors=S.DEFAULT_AUTHORS):
    """The page's detail for comments written by `authors` (S.AUTHORS), and
    the comments behind its name popups: (detail, comments)."""
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
                ai=ai, ai_left_out=dict(screened=screened_out, long_or_linked=too_long)), \
        dict(generated_at=store.now_iso(), authors=authors, **person_comments(rows, scores, weeks, month))


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
        doc, comments = build(S.weeks_in(a.week), version=a.prompt, sandbox=a.sandbox, authors=g)
        out = a.out or S.authors_path(OUT, g)
        with open(out, "w") as f:
            json.dump(doc, f, indent=1, ensure_ascii=False)
            f.write("\n")
        cout = S.authors_path(COMMENTS_OUT, g) if not a.out else os.path.splitext(a.out)[0] + ".comments.json"
        with open(cout, "w") as f:
            json.dump(comments, f, ensure_ascii=False, separators=(",", ":"))
            f.write("\n")
        print(f"{g}: {doc['total']['n']} comments, {len(doc['ai'])} AI-friction comments shown "
              f"({doc['ai_left_out']}), {doc['missing']} unscored -> {out} ({time.time() - t0:.0f}s)", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1:])
