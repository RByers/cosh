"""Code fingerprints: how an incremental store notices that the code which
computed its rows has changed (docs/data-architecture.md §4).

A store keeps, per part, a fingerprint of what that part's rows are a
function of besides their inputs: the functions that compute them, their
regexes and constants, a version to bump by hand for anything else (a
changed git flag in a caller, say), and whole files for a coarse part.
When the fingerprint differs from the stored one, the part is reset (its
rows deleted, its markers cleared) in the same transaction that records the
new fingerprint, and the step recomputes it. Rows from old and new code
are never mixed.

    fp = codefp.fingerprint(VERSION, parse_votes, LABEL, files=["config/bots.txt"])
    codefp.check(db, "walk", fp, reset)

Keep the hashed functions free of logging and progress output: any edit to
their source counts as a change. A store with no fingerprint yet adopts the
current one without a reset (its rows are taken to be from the code that
first records it).
"""

import hashlib
import inspect
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _text(x):
    if isinstance(x, str):
        return x
    if isinstance(x, re.Pattern):
        return f"re:{x.pattern!r}:{x.flags}"
    if inspect.isfunction(x) or inspect.isclass(x) or inspect.ismethod(x):
        return f"{x.__module__}.{x.__qualname__}:{inspect.getsource(x)}"
    return repr(x)


def fingerprint(*parts, files=()):
    """16 hex digits of a hash of `parts` (strings, numbers, regexes,
    functions by their source) and `files` (repository-relative paths, by
    content)."""
    h = hashlib.sha256("|".join(_text(p) for p in parts).encode())
    for f in files:
        h.update(f.encode())
        with open(os.path.join(ROOT, f), "rb") as fh:
            h.update(hashlib.sha256(fh.read()).digest())
    return h.hexdigest()[:16]


def stored(db, key, table="meta"):
    row = db.execute(f"SELECT v FROM {table} WHERE k = ?", (f"code_fp:{key}",)).fetchone()
    return row[0] if row else None


def check(db, key, fp, reset=None, table="meta"):
    """Compares part `key`'s stored fingerprint (row 'code_fp:<key>' of
    `table` (k, v)) with `fp`, in one IMMEDIATE transaction, so concurrent
    runs (sharded stages) reset a part once. Returns:
      "same"     it matches: nothing to do
      "new"      none stored yet: `fp` is recorded and the rows kept
      "changed"  it differs: reset(db) runs, then `fp` is recorded
    reset must not commit (no `with db:`, no executescript). With reset
    None, a changed fingerprint is returned without being recorded: the
    caller redoes the part and records it with record()."""
    if db.in_transaction:
        db.commit()
    db.execute("BEGIN IMMEDIATE")
    try:
        old = stored(db, key, table)
        state = "same" if old == fp else "new" if old is None else "changed"
        if state == "changed" and reset is not None:
            reset(db)
        if state == "new" or (state == "changed" and reset is not None):
            record(db, key, fp, table)
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return state


def record(db, key, fp, table="meta"):
    """Stores part `key`'s fingerprint (in the caller's transaction)."""
    db.execute(f"INSERT OR REPLACE INTO {table} (k, v) VALUES (?, ?)", (f"code_fp:{key}", fp))
