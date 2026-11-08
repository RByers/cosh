"""Detail for fully scored weeks on the Review Tone page: summaries/sentiment_recent.json
(comments by committers), plus .everyone.json and .noncommitters.json.

  python3 -m cosh.sentiment_people collect --week 2025-W45:2026-W44   # rows with identities
  python3 -m cosh.sentiment score --week 2025-W45:2026-W44            # every comment
  python3 -m cosh.sentiment_recent --week 2025-W45:2026-W44

It writes, for those weeks: a row per week and per month, and for each of
the page's periods (all the weeks, each calendar year, each calendar month;
`S.periods`):
  - an overview and the score distribution;
  - the most negative comments flagged as AI friction, anonymously (text,
    month and the writer's role), after a sandboxed screen drops any that
    identify anyone;
  - "who makes whom happy": the CL authors who draw the most glowing
    comments from reviewers, and the reviewers who draw the most from
    authors.

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
AI_CHARS = 600              # longer AI-friction comments are left out
AI_SHOWN = 20               # the most negative AI-friction comments shown
SCREEN_BATCH = 30


def load(weeks, data_dir=store.DATA_DIR, version=None):
    """(rows, scores, missing, n_trivial): substantive scored rows of the
    weeks, each with its week, and the bare acknowledgements per week."""
    scores = S.load_scores(None, data_dir, version)
    rows, missing, n_trivial = [], 0, defaultdict(int)
    for w in weeks:
        for r in S.read_jsonl(os.path.join(S.out_dir(data_dir), f"comments-{w}.jsonl")):
            if r["id"] not in scores:
                missing += 1
            elif S.TRIVIAL.match(r["text"]):
                n_trivial[w] += 1
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


def monthly(rows, scores, weeks):
    """One row per calendar month of `weeks` (by Thursday, `S.periods`): its
    first and last week and its figures."""
    by = defaultdict(list)
    for r in rows:
        by[r["week"]].append(scores[r["id"]])
    return [dict(month=k, weeks=[ws[0], ws[-1]], **_stats([v for w in ws for v in by[w]]))
            for k, ws in S.periods(weeks).items() if len(k) == 7]


def _kind(r):
    return S._target_kind(r)


def happy(rows, scores, top=TOP, ids=None):
    """Who draws the most glowing comments. authors: CL owners, from
    reviewers' comments aimed at them; reviewers: reviewers, from CL owners'
    replies to them. Each row: name, email, glowing (every glowing comment
    to them, repeats from one person included), happy (how many distinct
    people wrote those) and counterparts (distinct people who wrote to them
    that way at all). Ranked by glowing; only people with at least
    MIN_COUNTERPARTS counterparts are listed, the first `top` (None: all). If
    `ids` is a dict, ids[table][email] gets the ids of each listed person's
    glowing comments."""
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
        out = out[:top] if top is not None else out
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


def ai_comments(rows, scores, sandbox, n=AI_SHOWN, seed="2026-11", screened=None):
    """The `n` most negative AI-friction comments (lowest score first; ties
    by a deterministic shuffle) that a sandboxed screen finds nothing
    identifying in, as text, score, month and the writer's role only. Returns them,
    how many the screen dropped, and how many were too long or linked.
    `screened` is a `S.screen_first` cache to share between calls."""
    pool = [r for r in rows if scores[r["id"]][1] and len(r["text"]) <= AI_CHARS
            and not S._LINKY.search(r["text"])]
    order = {i: k for k, i in enumerate(S._draw([r["id"] for r in pool], seed))}
    pool.sort(key=lambda r: (scores[r["id"]][0], order[r["id"]]))
    by_id = {r["id"]: r for r in pool}
    kept, dropped = S.screen_first([r["id"] for r in pool], n, lambda i: by_id[i]["text"], sandbox,
                                   {} if screened is None else screened, SCREEN_BATCH)
    out = [dict(text=by_id[i]["text"], score=scores[i][0], month=by_id[i]["written_at"][:7],
                role="author" if by_id[i]["author_role"] == "AUTHOR" else "reviewer") for i in kept]
    return out, dropped, sum(1 for r in rows if scores[r["id"]][1]) - len(pool)


def _record(r, scores):
    """One praise or glowing comment for a name popup: text, date, writer,
    recipient, each one's role on the CL ("author": its owner, else
    "reviewer") and a Gerrit link."""
    return dict(text=r["text"], date=r["written_at"][:10], week=r["week"], score=scores[r["id"]][0],
                writer=r.get("author_name") or r.get("author_email"), writer_email=r.get("author_email"),
                writer_role="author" if r.get("author_role") == "AUTHOR" else "reviewer",
                recipient=r.get("target_name") or r.get("target_email"), recipient_email=r.get("target_email"),
                recipient_role="author" if r.get("target") is not None and r.get("target") == r.get("owner") else "reviewer",
                url=S.comment_url(r["project"], r["cl"], r["uuid"]))


def person_comments(rows, scores, weeks, listed=None, praise_rows=None):
    """The comments behind the praise boards (`praise`: every praise comment
    from one person to another, as on summaries/sentiment_praise.json) and
    the happy tables (`happy[table][email]`: the glowing comments, over all
    of `rows`, of everyone listed in any period; the page keeps those of the
    period shown). `listed[table]` is those emails (default: everyone in the
    tables over all of `rows`). Only praise and glowing comments: never
    negative ones.

    Praise comes from `praise_rows` when given (the praise boards can cover
    more weeks than the fully scored ones, `rows`), and `weeks` is then their
    range."""
    praise_rows = rows if praise_rows is None else praise_rows
    praise = [r for r in praise_rows if S.is_praise(r, scores) and S._target_kind(r) == "person"
              and r.get("author_email") and r.get("target_email")]
    every = {}
    happy(rows, scores, top=None, ids=every)
    if listed is None:
        listed = {t: set(v) for t, v in every.items()}
    happy_ids = {t: {e: v for e, v in every[t].items() if e in listed[t]} for t in every}
    wanted = {r["id"] for r in praise} | {i for t in happy_ids.values() for v in t.values() for i in v}
    comments = {r["id"]: _record(r, scores) for r in (*rows, *praise_rows) if r["id"] in wanted}
    assert all(scores[i][0] >= S.GLOWING for i in comments), "only praise and glowing comments"
    return dict(weeks=[weeks[0], weeks[-1]], comments=comments, praise=sorted(r["id"] for r in praise),
                happy=happy_ids)


def build(weeks, data_dir=store.DATA_DIR, version=None, sandbox="auto", authors=S.DEFAULT_AUTHORS,
          praise_weeks=None, screened=None):
    """The page's detail for comments written by `authors` (S.AUTHORS), and
    the comments behind its name popups: (detail, comments). `praise_weeks`
    (default `weeks`) are the praise boards' weeks, which may be more than
    `weeks` (the week-by-week detail here). `screened` is a
    `S.screen_first` cache to share between calls."""
    rows, scores, missing, n_trivial = load(weeks, data_dir, version)
    praise_weeks = praise_weeks or weeks
    extra = [w for w in praise_weeks if w not in weeks]
    praise_rows = rows + (load(extra, data_dir, version)[0] if extra else [])
    if any("author" not in r for r in praise_rows[:1] + praise_rows[-1:]):
        raise SystemExit("these comment files have no identities: collect them with "
                         "`python3 -m cosh.sentiment_people collect`")
    rows = S.by_authors(rows, authors, data_dir)
    praise_rows = S.by_authors(praise_rows, authors, data_dir)
    box = S.make_sandbox(sandbox, data_dir) if isinstance(sandbox, str) else sandbox
    cache = {} if screened is None else screened
    out, listed = {}, {"authors": set(), "reviewers": set()}
    try:
        for key, ws in S.periods(weeks).items():
            set_ws = set(ws)
            rs = [r for r in rows if r["week"] in set_ws]
            ai, screened_out, too_long = ai_comments(rs, scores, box, screened=cache)
            o = overview(rs, scores, ws)
            tables = happy(rs, scores)
            for t, v in tables.items():
                listed[t] |= {x["email"] for x in v}
            out[key] = dict(weeks=[ws[0], ws[-1]], n_trivial=sum(n_trivial[w] for w in ws),
                            total=o["total"], dist=o["dist"], happy=tables,
                            ai=ai, ai_left_out=dict(screened=screened_out, long_or_linked=too_long))
    finally:
        if box is not sandbox:
            box.close()
    return dict(generated_at=store.now_iso(), prompt=version or S.PROMPT_VERSION, weeks=[weeks[0], weeks[-1]],
                authors=authors, thresholds=dict(glowing=S.GLOWING, angry=S.ANGRY),
                min_counterparts=MIN_COUNTERPARTS, missing=missing,
                weekly=overview(rows, scores, weeks)["weekly"], monthly=monthly(rows, scores, weeks), periods=out), \
        dict(generated_at=store.now_iso(), authors=authors,
             **person_comments(rows, scores, [praise_weeks[0], praise_weeks[-1]], listed, praise_rows))


def main(argv):
    import argparse
    import json
    ap = argparse.ArgumentParser(prog="python3 -m cosh.sentiment_recent")
    ap.add_argument("--week", required=True, help="fully scored weeks, e.g. 2026-W37:2026-W44")
    ap.add_argument("--praise-week", default=None,
                    help="the praise boards' weeks for the name popups (default --week), e.g. 2025-W45:2026-W44")
    ap.add_argument("--prompt", default=None)
    ap.add_argument("--sandbox", choices=["auto", "bwrap", "none"], default="auto")
    ap.add_argument("--authors", choices=S.AUTHORS + ("all",), default="all",
                    help="whose comments count; 'all' writes one file for each")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    if a.out and a.authors == "all":
        ap.error("--out needs one --authors group")
    screened = {}
    for g in (S.AUTHORS if a.authors == "all" else (a.authors,)):
        t0 = time.time()
        doc, comments = build(S.weeks_in(a.week), version=a.prompt, sandbox=a.sandbox, authors=g,
                              praise_weeks=S.weeks_in(a.praise_week) if a.praise_week else None, screened=screened)
        out = a.out or S.authors_path(OUT, g)
        with open(out, "w") as f:
            json.dump(doc, f, indent=1, ensure_ascii=False)
            f.write("\n")
        cout = S.authors_path(COMMENTS_OUT, g) if not a.out else os.path.splitext(a.out)[0] + ".comments.json"
        with open(cout, "w") as f:
            json.dump(comments, f, ensure_ascii=False, separators=(",", ":"))
            f.write("\n")
        top = doc["periods"]["all"]
        print(f"{g}: {top['total']['n']} comments, {len(top['ai'])} AI-friction comments shown over all weeks "
              f"({top['ai_left_out']}), {len(doc['periods'])} periods, {doc['missing']} unscored -> {out} "
              f"({time.time() - t0:.0f}s)", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1:])
