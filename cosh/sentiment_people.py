"""Identities on sentiment comment rows.

`cosh.sentiment.collect` emits rows without identities and calls an
`annotate` hook; `Identities` is such a hook. It adds the writer's and
recipient's account, name, email and org, which per-person views need (the
Review Tone page's "who makes whom happy" tables, `cosh.sentiment_recent`).

  python3 -m cosh.sentiment_people collect --week 2026-W37:2026-W44
  python3 -m cosh.sentiment_people collect --week 2023-W26:2026-W44 --sample 0.05 --name sample-5pct
  python3 -m cosh.sentiment_people lookup --week 2025-W45:2026-W44   # -> summaries/sentiment_people.json

It writes the same comments-<name>.jsonl files as `python3 -m cosh.sentiment
collect`, with the identity fields added; rendering and scoring are the
same. Ground rule 5 (docs/plan.md): our pages never name anyone for negative
tone, whatever this data makes possible.
"""

import json
import os
import sqlite3
import sys
import time

from . import sentiment as S
from . import store
from .orgs import OrgResolver

AI_TARGET = "(AI/bot)"
comment_url = S.comment_url


class Identities:
    """annotate(row, ids) for S.collect: owner, author, author_name,
    author_email, author_org, target, target_name, target_email, target_org
    and target_is_ai (target -1 and org "(AI/bot)" for an AI recipient)."""

    def __init__(self, data_dir=store.DATA_DIR, accounts=None, resolve=None):
        if accounts is None:
            db = sqlite3.connect(f"file:{os.path.join(data_dir, store.DERIVED_FILE)}?mode=ro", uri=True)
            accounts = {(h, a): dict(email=e, name=n) for h, a, e, n in
                        db.execute("SELECT host, account_id, email, name FROM accounts")}
        self.accounts = accounts
        self.resolve = resolve or OrgResolver()

    def _acct(self, host, aid):
        return self.accounts.get((host, aid)) or {}

    def __call__(self, row, ids):
        host, day = ids["host"], ids["day"]
        a = self._acct(host, ids["author"])
        row.update(owner=ids["owner"], author=ids["author"], author_name=a.get("name"),
                   author_email=a.get("email"), author_org=self.resolve(a.get("email"), day))
        kind = row["target_kind"]
        if kind == "ai":
            row.update(target=-1, target_name=None, target_email=None, target_org=AI_TARGET, target_is_ai=True)
        elif kind == "person":
            t = self._acct(host, ids["target"])
            row.update(target=ids["target"], target_name=t.get("name"), target_email=t.get("email"),
                       target_org=self.resolve(t.get("email"), day), target_is_ai=False)
        else:
            row.update(target=None, target_name=None, target_email=None, target_org=None, target_is_ai=False)


LOOKUP_OUT = os.path.join(os.path.dirname(S.SUMMARY), "sentiment_people.json")


def lookup(weeks, data_dir=store.DATA_DIR):
    """Everyone who wrote, or was the person a comment answered, in the
    weeks' collected rows: {email: name}, for the Review Tone page's lookup
    box, so anyone can be looked up, praised or not. Names and emails only:
    nothing about tone (ground rule 5)."""
    people = {}
    for w in weeks:
        for r in S.read_jsonl(os.path.join(S.out_dir(data_dir), f"comments-{w}.jsonl")):
            if "author_email" not in r:
                raise SystemExit(f"{w}: no identities; collect it with `python3 -m cosh.sentiment_people collect`")
            for e, n in ((r.get("author_email"), r.get("author_name")), (r.get("target_email"), r.get("target_name"))):
                if e:
                    people[e] = n or people.get(e) or e
    return dict(generated_at=store.now_iso(), weeks=[weeks[0], weeks[-1]], people=dict(sorted(people.items())))


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="python3 -m cosh.sentiment_people")
    ap.add_argument("step", choices=["collect", "lookup"])
    ap.add_argument("--week", default="2026-W44", help="a week or a range, e.g. 2026-W37:2026-W44")
    ap.add_argument("--sample", type=float, default=None,
                    help="collect: a deterministic sample at this rate over --week's range")
    ap.add_argument("--name", default=None, help="collect: name of the sample set, e.g. sample-5pct")
    a = ap.parse_args(argv)
    t0 = time.time()
    weeks = S.weeks_in(a.week)
    if a.step == "lookup":
        doc = lookup(weeks)
        with open(LOOKUP_OUT, "w") as f:
            json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
            f.write("\n")
        print(f"{len(doc['people'])} people -> {LOOKUP_OUT}", file=sys.stderr)
        return
    ann = Identities()
    if a.sample:
        start, end = S.week_bounds(weeks[0])[0], S.week_bounds(weeks[-1])[1]
        sets = [(a.name or f"sample-{a.sample:g}",
                 S.collect(None, start=start, end=end, keep=lambda i: S.in_sample(i, a.sample), annotate=ann))]
    else:
        sets = [(w, S.collect(w, annotate=ann)) for w in weeks]
    for name, rows in sets:
        p = os.path.join(S.out_dir(), f"comments-{name}.jsonl")
        S.write_jsonl(p, rows)
        print(f"{len(rows)} comments -> {p} ({time.time() - t0:.0f}s)", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1:])
