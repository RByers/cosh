"""Publish the Review Balance page's data (web/balance.html, docs/balance.md).

Writes summaries/balance.json, summaries/balance_dirs.json and
summaries/balance_authors.json, each whole and once, from the steps in
STEPS, run in that order. STEPS is the record of where every dataset comes
from: each step names the datasets (or whole files) it gives, a dataset has
exactly one step, and the files hold nothing else. The steps call the
compute functions of the balance scripts in scripts/; those scripts keep
their main() for exploration, and no longer write into summaries/.

  COSH_DATA_DIR=<main>/data/private nice -n 5 python3 -m cosh.balance_publish [--out DIR]
  ... python3 -m cosh.balance_publish --check          # rebuild into the work dir, compare with summaries/
  ... python3 -m cosh.balance_publish --steps a,b      # rerun only these steps, reuse the others' results
  python3 -m cosh.balance_publish compare DIR_A DIR_B  # the three files, dataset by dataset

Each step runs in its own process (the scripts set module globals, and each
loads several GB), one at a time, and leaves its result as JSON in the work
directory ($COSH_DATA_DIR/scratch/balance-publish/steps by default) with a
log of what it printed. A full run takes about 8 min (2026-11-12, at
nice 10; the slowest steps are report 1.5 min, signals 1 min, narrative 1
min); most of it is the same loading of balance.sqlite and commits.sqlite
in each step.

Everything is computed from the stores except these inputs, read from fixed
paths under $COSH_DATA_DIR (or --inputs). Each is an analysis too slow,
too costly or too private to repeat on every publish:

- balance_clusters/clusters.json and map.json: scripts/balance_clusters.py
  (about 10 min, k-means over per-person panels it keeps private in
  people.json) and scripts/balance_cluster_map.py;
- chrome_releases/summary.json: scripts/chrome_releases.py join (the
  Chrome Releases security fixes);
- review_roi/{part1_results,part1_report,part2_results,reverts_results,
  substance_results}.json: the review-ROI studies (docs/review-roi.md;
  about an hour, with Haiku pilots and blame runs);
- review_roi/addressed_{cl,blame,people}.json: scripts/balance_addressed_value.py
  cl, blame and people (docs/balance-addressed.md; cl and blame need the
  ROI per-CL table and blame scratch).

The AI-predict scores (ai_predict/scores.sqlite, Haiku) are read as a store
by balance_narrative.

The analysis window ends at DATA_END below, which follows the data: the
first day of the month in which derived.sqlite's newest fetched week ends
(so new weeks reach the page once a month is complete). The scripts take
their end of data and last whole quarter from it; their comparison eras
(2023 H2 - 2024 against the latest four quarters, and so on) are still their
own constants. $COSH_BALANCE_DATA_END (YYYY-MM-DD) pins it.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(HERE, "scripts")
SUMMARIES = os.path.join(HERE, "summaries")

# ------------------------------------------------------------------ window

def data_end():
    """The first day of the month in which derived.sqlite's newest fetched
    week ends: 2026-11-01 for data through 2026-W44 (ending 2026-11-02).
    Without a derived.sqlite (tests), 2026-11-01."""
    if os.environ.get("COSH_BALANCE_DATA_END"):
        return datetime.fromisoformat(os.environ["COSH_BALANCE_DATA_END"]).replace(tzinfo=timezone.utc)
    import sqlite3
    from datetime import date, timedelta
    from cosh import store
    path = os.path.join(store.DATA_DIR, store.DERIVED_FILE)
    weeks = []
    if os.path.exists(path):
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        weeks = [w for (v,) in db.execute("SELECT v FROM meta WHERE k = 'fetched_weeks'") for w in json.loads(v or "[]")]
    if not weeks:
        return datetime(2026, 11, 1, tzinfo=timezone.utc)
    y, w = max(weeks).split("-W")
    end = date.fromisocalendar(int(y), int(w), 1) + timedelta(days=7)
    return datetime(end.year, end.month, 1, tzinfo=timezone.utc)


DATA_END = data_end()     # first day after the data


def quarter_of(t):
    return f"{t.year}Q{(t.month - 1) // 3 + 1}"


def quarter_end(q):
    """The first moment after quarter q ("2026Q3" -> 2026-10-01 UTC)."""
    y, n = int(q[:4]), int(q[-1])
    return datetime(y + n // 4, n % 4 * 3 + 1, 1, tzinfo=timezone.utc)


def last_whole_quarter(end):
    """The last quarter that ends at or before `end`."""
    y, n = end.year, (end.month - 1) // 3 + 1
    q = f"{y}Q{n}"
    if quarter_end(q) <= end:
        return q
    return f"{y}Q{n - 1}" if n > 1 else f"{y - 1}Q4"


LAST_QUARTER = last_whole_quarter(DATA_END)               # 2026Q3


def show(new, out=None):
    """What a script's main() does with its datasets: list them, and write
    them as JSON to `out` if given."""
    for k, v in new.items():
        print(f"{k}: {len(v) if isinstance(v, (list, dict)) else v} rows", file=sys.stderr)
    if out:
        with open(out, "w") as f:
            json.dump(new, f, indent=1)
            f.write("\n")


# ------------------------------------------------------------------- steps

def _scripts():
    if SCRIPTS not in sys.path:
        sys.path.insert(0, SCRIPTS)


def _args(**kw):
    """The arguments the scripts' loaders expect: the four inputs from
    commits.sqlite, no cache."""
    return argparse.Namespace(first_commit=None, owners_added=None, ai_marked=None, mech=None, cache=None,
                              explore=False, **kw)


def _json(path):
    with open(path) as f:
        return json.load(f)


REPORT = ["exchange", "git_quarters", "reviewers_by_tenure", "reviewer_quarters", "reviewer_load_hist",
          "reviewer_load_top", "areas", "cohort_curves", "git_cohorts", "learning"]


def step_report(ctx):
    _scripts()
    import balance_report
    out = balance_report.compute(_args())
    new = {k: out[k] for k in REPORT}
    new["summary"] = [{"mechanical_cls": out["mechanical_cls"], "lsc_cls": out["lsc_cls"]}]
    new["balance_dirs.json"] = out["dirs"]
    return new


def step_mechanical(ctx):
    _scripts()
    import balance_analysis as A
    return A.mechanical_datasets(A.load_cl())


def step_pipeline(ctx):
    _scripts()
    import balance_analysis as A
    return {"pipeline": A.pipeline_new_people(*A.pipeline_people(A.load_commits()))}


def step_growth(ctx):
    _scripts()
    import balance_growth
    import balance_growth_tables
    return balance_growth_tables.datasets(balance_growth.page_tables(_args()))


def step_narrative(ctx):
    _scripts()
    import balance_narrative as N
    return N.datasets(N.load_cached(_args()), ctx.result("growth")["ai_paired"])


def step_dirgrowth(ctx):
    _scripts()
    import balance_dirgrowth
    return balance_dirgrowth.compute(_args(min_cls=3000))


def step_histograms(ctx):
    _scripts()
    import balance_histograms as H
    return H.datasets(H.load(None))


def step_definitions(ctx):
    _scripts()
    import balance_definitions as D
    return D.datasets(D.load(None))


def step_behind(ctx):
    _scripts()
    import balance_behind
    return balance_behind.compute(_args())[0]


def step_review_share(ctx):
    _scripts()
    import balance_review_share as RS
    return RS.datasets(RS.load(_args()))


def step_learning(ctx):
    _scripts()
    import balance_learning
    return balance_learning.compute(_args(), "then")[0]


def step_feedback_predicts(ctx):
    _scripts()
    import balance_feedback_predicts
    return balance_feedback_predicts.compute(_args())


def step_signals(ctx):
    _scripts()
    import balance_page_extras
    import balance_signals
    report = json.loads(json.dumps(balance_signals.compute(_args())))   # as the old balance_signals.json held it
    return balance_page_extras.signals(report)


def step_clusters(ctx):
    _scripts()
    import balance_page_extras as X
    d = os.path.join(ctx.inputs, "balance_clusters")
    new = X.clusters(_json(os.path.join(d, "clusters.json")))
    new.update(X.pattern_map(_json(os.path.join(d, "map.json"))))
    return new


def step_security(ctx):
    _scripts()
    import balance_page_extras as X
    return X.security(_json(os.path.join(ctx.inputs, "chrome_releases", "summary.json")))


def step_roi(ctx):
    _scripts()
    import review_roi_report
    return review_roi_report.datasets(os.path.join(ctx.inputs, "review_roi"))


def step_addressed(ctx):
    _scripts()
    import balance_addressed_value as AV
    d = os.path.join(ctx.inputs, "review_roi")
    return AV.report_datasets(*(_json(os.path.join(d, f"addressed_{k}.json")) for k in ("cl", "blame", "people")))


def step_authors(ctx):
    _scripts()
    import balance_authors
    return {"balance_authors.json": balance_authors.document(_args())}


class Step:
    def __init__(self, name, run, gives, inputs=()):
        self.name, self.run, self.gives, self.inputs = name, run, list(gives), list(inputs)


# The record: every dataset of balance.json, and the other two files, with
# the one step that makes it. Steps run in this order; narrative reads
# growth's ai_paired.
STEPS = [
    Step("report", step_report, REPORT + ["summary", "balance_dirs.json"]),
    Step("mechanical", step_mechanical, ["mechanical_files", "mechanical_repetition"]),
    Step("pipeline", step_pipeline, ["pipeline"]),
    Step("growth", step_growth, ["growth_windows", "newcomer_review", "mentorship", "promotion", "ai_paired"]),
    Step("narrative", step_narrative, ["reviewer_burden", "approver_burden", "org_feedback", "org_feedback_fit",
                                       "org_reviewing", "org_review_value", "new_reviewer_growth", "ai_quarters",
                                       "ai_reviewer_load", "ai_summary", "capacity_years", "capacity_tenure",
                                       "capacity_orgs"]),
    Step("dirgrowth", step_dirgrowth, ["queue_growth", "queue_openness", "queue_approver", "queue_blink",
                                       "queue_quarters", "queue_summary", "queue_months", "queue_hours", "queue_dirs",
                                       "queue_shift", "queue_mix", "queue_inflow", "queue_inflow_periods",
                                       "queue_learning"]),
    Step("histograms", step_histograms, ["ftr_hist", "ftr_hist_summary", "wait_hist", "wait_hist_summary"]),
    Step("definitions", step_definitions, ["feedback_def_hist", "feedback_def_deciles", "feedback_def_summary"]),
    Step("behind", step_behind, ["behind_share_years", "behind_share_by_year", "behind_share_cohorts",
                                 "behind_share_summary", "behind_feedback", "behind_feedback_summary"]),
    Step("review_share", step_review_share, ["review_share_hist", "review_share_years"]),
    Step("learning", step_learning, ["learning_practice", "learning_practice_fit"]),
    Step("feedback_predicts", step_feedback_predicts, ["fb_predict_fifths", "fb_predict_fit", "fb_predict_summary"]),
    Step("signals", step_signals, ["signals_era", "signals_tenure", "signals_familiarity", "panels", "matched",
                                   "signals_summary"]),
    Step("clusters", step_clusters, ["patterns", "trajectories", "joiner_paths", "transitions", "pattern_cells",
                                     "pattern_ellipses", "pattern_loadings", "pattern_rules", "pattern_map_summary"],
         ["balance_clusters/clusters.json", "balance_clusters/map.json"]),
    Step("security", step_security, ["security_years", "security_summary"], ["chrome_releases/summary.json"]),
    Step("roi", step_roi, ["roi_summary", "roi_odds", "roi_depth", "roi_classes", "roi_timing", "roi_panels",
                           "roi_substance"],
         ["review_roi/part1_results.json", "review_roi/part1_report.json", "review_roi/part2_results.json",
          "review_roi/reverts_results.json", "review_roi/substance_results.json"]),
    Step("addressed", step_addressed, ["addr_tenure", "addr_compare"],
         ["review_roi/addressed_cl.json", "review_roi/addressed_blame.json", "review_roi/addressed_people.json"]),
    Step("authors", step_authors, ["balance_authors.json"]),
]
FILES = ["balance.json", "balance_dirs.json", "balance_authors.json"]
BY_NAME = {s.name: s for s in STEPS}


class Context:
    def __init__(self, work, inputs):
        self.work, self.inputs = work, inputs

    def result_path(self, name):
        return os.path.join(self.work, f"{name}.json")

    def result(self, name):
        return _json(self.result_path(name))


def run_step(ctx, name):
    """In this process: run one step and leave its result in the work dir."""
    step = BY_NAME[name]
    new = step.run(ctx)
    if set(new) != set(step.gives):
        raise SystemExit(f"step {name} gave {sorted(new)}, not {sorted(step.gives)}")
    tmp = ctx.result_path(name) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(new, f, separators=(",", ":"))
    os.replace(tmp, ctx.result_path(name))


def run_all(ctx, names):
    """Run the named steps, in STEPS order, each in a child process."""
    os.makedirs(ctx.work, exist_ok=True)
    for step in STEPS:
        if step.name not in names:
            continue
        missing = [p for p in step.inputs if not os.path.exists(os.path.join(ctx.inputs, p))]
        if missing:
            raise SystemExit(f"step {step.name}: missing inputs under {ctx.inputs}: {', '.join(missing)}")
        t0 = time.time()
        log = os.path.join(ctx.work, f"{step.name}.log")
        with open(log, "w") as f:
            rc = subprocess.run([sys.executable, "-m", "cosh.balance_publish", "--run-step", step.name,
                                 "--work", ctx.work, "--inputs", ctx.inputs], cwd=HERE, stdout=f,
                                stderr=subprocess.STDOUT).returncode
        if rc:
            raise SystemExit(f"step {step.name} failed (exit {rc}); see {log}")
        print(f"{step.name}: {time.time() - t0:.0f} s", file=sys.stderr, flush=True)


def assemble(ctx):
    """The three files' content from the steps' results, in STEPS order."""
    datasets, files = {}, {}
    for step in STEPS:
        res = ctx.result(step.name)
        for k in step.gives:
            (files if k in FILES else datasets)[k] = res[k]
    files["balance.json"] = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "datasets": datasets}
    return files


def write(files, out):
    os.makedirs(out, exist_ok=True)
    for name in FILES:
        path = os.path.join(out, name)
        with open(path + ".tmp", "w") as f:
            json.dump(files[name], f, separators=(",", ":"))
            f.write("\n")
        os.replace(path + ".tmp", path)
        print(f"wrote {path}", file=sys.stderr)


# ----------------------------------------------------------------- compare

GENERATED = "generated"      # a run's date: never compared


def _strip(doc):
    return {k: v for k, v in doc.items() if k != GENERATED}


def _first_diff(a, b):
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return f"{len(a)} rows vs {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            if x != y:
                if isinstance(x, dict) and isinstance(y, dict):
                    ks = [k for k in sorted(set(x) | set(y)) if x.get(k) != y.get(k)]
                    return f"row {i}: {', '.join(ks[:6])}{' ...' if len(ks) > 6 else ''}"
                return f"row {i}"
    if isinstance(a, dict) and isinstance(b, dict):
        ks = [k for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]
        return f"keys {', '.join(ks[:6])}{' ...' if len(ks) > 6 else ''}"
    return "differs"


def compare(a_dir, b_dir):
    """[(file, dataset or "", status, detail)] for every dataset of
    balance.json and the two other files, ignoring `generated` and key
    order. status: same, differs, only-a, only-b."""
    out = []
    for name in FILES:
        pa, pb = os.path.join(a_dir, name), os.path.join(b_dir, name)
        if not (os.path.exists(pa) and os.path.exists(pb)):
            out.append((name, "", "only-a" if os.path.exists(pa) else "only-b", ""))
            continue
        a, b = _strip(_json(pa)), _strip(_json(pb))
        if name == "balance.json":
            da, db = a.pop("datasets"), b.pop("datasets")
            for k in sorted(set(da) | set(db)):
                if k not in db:
                    out.append((name, k, "only-a", ""))
                elif k not in da:
                    out.append((name, k, "only-b", ""))
                else:
                    out.append((name, k, "same" if da[k] == db[k] else "differs",
                                "" if da[k] == db[k] else _first_diff(da[k], db[k])))
        out.append((name, "", "same" if a == b else "differs", "" if a == b else _first_diff(a, b)))
    return out


def print_compare(rows):
    bad = [r for r in rows if r[2] != "same"]
    for f, k, status, detail in rows:
        if status != "same":
            print(f"{status:8} {f} {k} {detail}".rstrip())
    print(f"{len(rows) - len(bad)} of {len(rows)} the same")
    return not bad


# -------------------------------------------------------------------- main

def main(argv=None):
    from cosh import store
    if argv is None:
        argv = sys.argv[1:]
    if argv[:1] == ["compare"]:
        if len(argv) != 3:
            raise SystemExit("usage: python3 -m cosh.balance_publish compare DIR_A DIR_B")
        sys.exit(0 if print_compare(compare(argv[1], argv[2])) else 1)
    ap = argparse.ArgumentParser(description="Write the Review Balance page's three summaries files.")
    ap.add_argument("--out", default=SUMMARIES, help="where to write the files (default: summaries/)")
    ap.add_argument("--work", default=os.path.join(store.DATA_DIR, "scratch", "balance-publish", "steps"),
                    help="where the steps leave their results and logs")
    ap.add_argument("--inputs", default=store.DATA_DIR, help="where the fixed-path inputs are (default: the data dir)")
    ap.add_argument("--steps", help="comma-separated steps to rerun; the others' results are reused from --work")
    ap.add_argument("--check", action="store_true",
                    help="write into <work>/out instead, and compare with --out (exit 1 if anything differs)")
    ap.add_argument("--run-step", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    ctx = Context(args.work, args.inputs)
    if args.run_step:
        run_step(ctx, args.run_step)
        return
    names = [s.name for s in STEPS]
    if args.steps:
        names = args.steps.split(",")
        unknown = set(names) - set(BY_NAME)
        if unknown:
            raise SystemExit(f"unknown steps: {', '.join(sorted(unknown))}; steps are {', '.join(BY_NAME)}")
        for s in STEPS:
            if s.name not in names and not os.path.exists(ctx.result_path(s.name)):
                raise SystemExit(f"no result of step {s.name} in {ctx.work} to reuse")
    t0 = time.time()
    run_all(ctx, set(names))
    files = assemble(ctx)
    out = os.path.join(args.work, "out") if args.check else args.out
    write(files, out)
    print(f"done in {(time.time() - t0) / 60:.1f} min", file=sys.stderr)
    if args.check:
        sys.exit(0 if print_compare(compare(out, args.out)) else 1)


if __name__ == "__main__":
    main()
