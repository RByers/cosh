#!/usr/bin/env python3
"""Revert study for docs/review-roi.md (work package 3): reasons, timing, relands, cost.

Reads (all read-only): commits.sqlite (gcommits), balance.sqlite (cl, cl_attention),
the shared Chromium clone (revert and reland messages; `main` first-parent only, no fetch).
Writes only under the scratch directory S (never under data/private).

Rerun, from the worktree:
  export COSH_DATA_DIR=/home/rbagent/projects/cosh/data/private
  S=data/private/scratch/review_roi/reverts
  python3 scripts/review_roi_reverts.py parse   --out $S     # history -> $S/msgs.jsonl (~1 min)
  python3 scripts/review_roi_reverts.py table   --out $S     # revert_reasons.tsv, reverts_full.jsonl
  python3 scripts/review_roi_reverts.py samples --out $S     # samples per class (truncated reasons)
  python3 scripts/review_roi_reverts.py cost    --out $S     # review cost of cycles, bootstrap CIs
  python3 scripts/review_roi_reverts.py timing  --out $S     # bins, years, preventable share
  python3 scripts/review_roi_reverts.py pilot   --out $S     # 100 unknown reasons through cosh.sandbox (Haiku)
  python3 scripts/review_roi_reverts.py results --out $S     # reverts_results.json
Commit messages are untrusted text: used only as regex input and counts.
"""
import argparse, json, os, random, re, sqlite3, statistics as st, subprocess, sys, time
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cosh import commits  # noqa: E402

DATA = os.environ.get("COSH_DATA_DIR", "/home/rbagent/projects/cosh/data/private")
SHARED = os.path.expanduser("~/projects/shared/chromium")
SINCE_TS = 1688169600          # 2023-07-01 UTC
SEP = "\x1e"


def ro(name):
    return sqlite3.connect(f"file:{DATA}/{name}?mode=ro", uri=True)


# ------------------------------------------------------------------ parse
def cmd_parse(a):
    os.makedirs(a.out, exist_ok=True)
    fmt = "%x01%x02%x03%H" + SEP + "%s" + SEP + "%b%x02"
    env = {**os.environ, "GIT_NO_LAZY_FETCH": "1"}
    p = subprocess.Popen(["git", "--git-dir", SHARED, "log", "main", "--first-parent",
                          "--since=2023-06-30", f"--format={fmt}"], stdout=subprocess.PIPE, env=env,
                         preexec_fn=lambda: os.nice(5))
    out = open(os.path.join(a.out, "msgs.jsonl"), "w")
    cnt = Counter()
    buf = b""

    def flush(rec):
        s = rec.decode("utf-8", "replace").rstrip("\x02")
        parts = s.split(SEP, 2)
        if len(parts) < 3:
            return
        sha, subj, body = parts
        cnt["n"] += 1
        m = re.search(r"^This reverts commit ([0-9a-f]{40})", body, re.M)
        if m:
            cnt["revert"] += 1
            out.write(json.dumps({"k": "revert", "sha": sha, "subj": subj[:200], "target": m.group(1),
                                  "body": body[:6000]}) + "\n")
            return
        mm = re.search(r"reland of", body, re.I)
        if subj.lower().startswith("reland") or mm:
            cnt["reland"] += 1
            seg = body[mm.start():mm.start() + 500] if mm else ""
            seg = re.split(r"Original change's description", seg)[0]
            out.write(json.dumps({"k": "reland", "sha": sha, "subj": subj[:200],
                                  "shas": re.findall(r"\b[0-9a-f]{40}\b", seg),
                                  "cls": [int(x) for x in re.findall(r"(?:\+/|googlesource\.com/)(\d{5,8})\b", seg)]}) + "\n")

    while True:
        c = p.stdout.read(1 << 20)
        if not c:
            break
        buf += c
        recs = buf.split(b"\x01\x02\x03")
        buf = recs.pop()
        for r in recs:
            if r.strip():
                flush(r)
    if buf.strip():
        flush(buf)
    print(p.wait(), dict(cnt))
    out.close()


# --------------------------------------------------------------- classes
# First matching rule wins; applied to the lowercased reason text.
RULES = [
    ("compile_or_link", r"luci bisection has identified this change as the (?:culprit|cause) of a build failure"),
    ("test_failure", r"luci bisection has identified this change as the (?:culprit|cause) of a (?:test|compile|step)? ?failure"),
    ("policy_or_process", r"landed by mistake|by accident|wrong branch|missing (?:approval|review|owners?)|without (?:approval|review|owners?)|not approved|should not have (?:landed|been (?:landed|submitted))|submitted (?:by mistake|prematurely|too early)|landed (?:too early|prematurely)|policy violat|launch approval|privacy review|not ready (?:to|for) (?:land|launch|ship)|\bintent to\b|\blegal\b|\blicen[sc]e"),
    ("security", r"security (?:issue|bug|vulnerab|regress|concern|fix)|vulnerab|\bcve\b|exploit|sandbox escape|\bxss\b"),
    ("dependent_or_requested", r"depend(?:s|ent|ency)? (?:on|cl|change)|\bdependent\b|in order to revert|(?:so|to) (?:that )?(?:we|i) can revert|to (?:allow|unblock) (?:the )?revert|revert(?:ing)? (?:the )?(?:parent|child|upstream|downstream|underlying|original)|prerequisite|(?:was|been|being|has been|have been) reverted|requested by|asked (?:me|us) to|asked by|(?:per|at) (?:the )?(?:request|owner)|request(?:ed)? (?:of|from)|(?:author|owner|\boc\b|tl) (?:asked|requested|wants|wanted)|as (?:requested|asked)|reland needs|will reland|to reland|going to reland|plan to reland|reland(?:ing)? (?:with|after|later|soon)|reverting (?:to unblock|to re-?land|for now)|no longer (?:needed|necessary|required)|\bobsolete|\bdeprecated|abandon|superseded|wrong approach|needs? (?:more|further) (?:discussion|design|thought|work|review)|design (?:needs|discussion|concern)|\bpending\b|\bblocker\b|rolled? back|launch was|experiment is (?:finished|over|done)|project canceled|project cancelled"),
    ("flaky_or_unrelated", r"flak(?:e|y|iness)|unrelated|speculative|not the (?:root )?(?:cause|culprit)|to check if|to see if|to verify if|to determine if|to confirm (?:that|if|whether)|checking (?:if|whether)|check whether|see if (?:this|the|it)|infra\b|bad roll|\bswarming|\bgoma\b|upstream (?:break|fail|issue)|out of memory|\boom\b"),
    ("compile_or_link", r"compil|build (?:fail|break|error|is broken|broken)|builds? (?:fail|break)|(?:fail|failing|breaks?|broke|broken|breaking)(?:s|ing)? (?:to )?(?:the )?(?:\w+ )?(?:builds?\b|compil)|fails? to build|\blink(?:er|ing)? (?:error|fail|break)|link(?:er)?[- ]fail|undefined (?:symbol|reference)|unresolved external|ld\.lld|\bbuild\b.{0,25}\b(?:fail|error|break|broke)|syntax error|missing (?:include|header|dep)|\bgn (?:check|gen)|-werror|\bwerror\b|-wunused|-w[a-z-]+\b|unused (?:variable|function|parameter)|\bclang\b|tree (?:is )?(?:red|closed|broken)|closed the tree|(?:break|broke|breaks|broken|breaking)\W+(?:\w+\W+){0,3}builds?\b|include (?:cycle|error)"),
    ("perf_or_size_regression", r"\bperf(?:ormance)?\b|pinpoint|binary size|apk size|size regress|\bsize\b.{0,30}(?:increase|regress|bloat)|bloat|memory (?:regress|leak|usage|increase|bloat)|\bleaks?\b|latenc|slower|slowdown|\bjank|startup (?:time|regress)|speedometer|jetstream|motionmark|benchmark|power regress|\bcpu\b|\bbattery|crossbench|\blcp\b|\bcls\b|\bfcp\b|\bttfb|\bfps\b|\bmetrics? regress"),
    ("test_failure", r"\btests?\b|\w+test\b|_unittest|browsertest|\bfailing\b|\bfailures?\b|\bfails?\b|\bfailed\b|webtests?|layouttests?|expectations|test_\w+|\bpixel\b|screenshot|browser_tests|unit_tests|interactive_ui|\bcts\b|\bwpt\b|\bvts\b|\bfailing"),
    ("crash_or_functional", r"crash|dcheck|check fail|use[- ]after[- ]free|\buaf\b|\basan\b|\bmsan\b|\btsan\b|\bubsan\b|sanitizer|segfault|\bsegv\b|null (?:deref|pointer)|nullptr|\bhang|deadlock|\bassert|stack overflow|buffer overflow|out[- ]of[- ]bounds|\boob\b|data race|race condition|corrupt|\bbroke(?:n)?\b|\bbreaks?\b|\bbreaking\b|\bregress|\bbug\b|\bbugs\b|\bissue|\bproblem|incorrect|\bwrong\b|doesn'?t work|does not work|not working|\bcannot\b|can'?t|unable to|(?:stops?|stopped) working|\bdefect|\berror|\bblank\b|\bblack\b|user[- ]visible|behavio"),
    ("flaky_or_unrelated", r"may (?:be|have been) (?:causing|the cause|responsible|related)|might (?:be|have been) (?:causing|the cause|responsible|related)|(?:possibly|probably|potentially|likely|suspected) (?:the )?(?:cause|culprit|causing|breaking|responsible|related|due|breaks?)|suspect|culprit|trying to (?:unbreak|see|verify|determine|bisect|check|find|identify)|bisect|possible cause|not sure|unsure|unclear|\bmaybe\b|\bluci bisection\b|identified this change as the"),
]
# Duplicate class names above are rules applied in order; the first rule that matches wins.
CLASSES = list(dict.fromkeys(c for c, _ in RULES)) + ["unknown"]
RULES_C = [(c, re.compile(r, re.I)) for c, r in RULES]
NOT_PREVENTABLE = {"flaky_or_unrelated", "dependent_or_requested", "policy_or_process"}


def reason_of(body):
    """The 'Reason for revert' text; falls back to free text before the original description."""
    b = body.replace("\r", "")
    pre = re.split(r"\n\s*Original change's description|\n> ", b)[0]
    m = re.search(r"Reason for revert:?\s*(.*)", pre, re.I | re.S)
    if m:
        txt = m.group(1)
    else:
        txt = re.sub(r"^\s*This reverts commit [0-9a-f]{40}\.?", "", pre, flags=re.M)
    txt = re.sub(r"(?im)^\s*(?:bug|fixed|change-id|no-?presubmit|no-?tree-?checks|no-?try|cq-include-trybots|"
                 r"reviewed-on|reviewed-by|bot-commit|commit-queue|auto-submit|owners-override)\b.*$", "", txt)
    return re.sub(r"\s+", " ", txt).strip()


URL = re.compile(r"https?://\S+|(?:crbug|crrev|b|issues\.chromium\.org/issues|go|goto)(?:\.com|\.org)?/\S+|\b[\w.-]+(?:/[\w.%@~+=-]+){2,}")


def clean(reason):
    """Lowercase, with links, paths and CI boilerplate removed so that words in them don't match."""
    t = re.sub(r"cr-commit-position:.*|failure link:.*|details:.*", " ", reason, flags=re.I)
    t = URL.sub(" ", t)
    return re.sub(r"\s+", " ", t).lower()


def classify(reason):
    if not reason:
        return "unknown"
    t = clean(reason)
    for c, r in RULES_C:
        if r.search(t):
            return c
    return "unknown"


def is_botemail(e):
    return bool(re.search(r"gserviceaccount|autoroll|bot@|-bot|\[bot\]|robot|rubber-stamper|buildbot|@appspot", e))


# ------------------------------------------------------------------ table
def load_reverts(out):
    g = sqlite3.connect(f"file:{commits.db_path(DATA)}?mode=ro", uri=True)
    byrev = {}
    for line in open(os.path.join(out, "msgs.jsonl")):
        d = json.loads(line)
        if d["k"] == "revert":
            byrev[d["sha"]] = d
    meta = {}
    for sha, em, la, cn, bot, rb, rs, rl in g.execute(
            "SELECT sha, author_email, landed_at, change_number, is_bot, reviewed_by, reverts_sha, is_reland FROM gcommits"):
        meta[sha] = dict(sha=sha, email=em, landed=la, cn=cn, bot=bot, rb=json.loads(rb) if rb else [], rs=rs, rl=rl)
    rows = {}
    for sha, d in sorted(byrev.items(), key=lambda kv: meta.get(kv[0], {}).get("landed", 0)):
        r = meta.get(sha)
        if not r or r["landed"] < SINCE_TS or not r["rs"]:
            continue
        t = meta.get(r["rs"])
        if not t:
            continue
        if r["rs"] in rows:
            rows[r["rs"]]["n_reverts"] += 1
            continue
        reason = reason_of(d["body"])
        email = r["email"]
        if is_botemail(email):
            role = "bot"
        elif email == t["email"]:
            role = "author"
        elif email in t["rb"]:
            role = "approver"
        else:
            role = "third_party"
        rows[r["rs"]] = dict(reverted_sha=r["rs"], revert_sha=sha, reverted_cn=t["cn"], revert_cn=r["cn"],
                             landed=t["landed"], reverted=r["landed"], cls=classify(reason), role=role,
                             reason=reason, bot_stamped=r["bot"], reverted_is_revert=bool(t["rs"]),
                             reverted_email=t["email"], subj=d["subj"], n_reverts=1, reverter_email=email,
                             revert_reviewers=r["rb"])
    return list(rows.values()), meta


def find_relands(out, rows, meta):
    rel = [json.loads(l) for l in open(os.path.join(out, "msgs.jsonl")) if '"k": "reland"' in l]
    bysha = {r["reverted_sha"]: r for r in rows}
    byrevsha = {r["revert_sha"]: r for r in rows}
    bycn = {r["reverted_cn"]: r for r in rows if r["reverted_cn"]}
    bytitle = defaultdict(list)
    for r in rows:
        m = re.match(r'Revert "(.*)"$', r["subj"])
        if m:
            bytitle[m.group(1).strip().lower()].append(r)
    for r in rows:
        r.update(relanded=0, reland_sha=None, reland_days=None, reland_cn=None, reland_method=None, reland_reverted=0)
    cands = defaultdict(list)
    for d in rel:
        m = meta.get(d["sha"])
        if not m:
            continue
        hit = how = None
        for s in d["shas"]:
            hit = bysha.get(s) or byrevsha.get(s)
            if hit:
                how = "sha"
                break
        if not hit:
            for c in d["cls"]:
                hit = bycn.get(c)
                if hit:
                    how = "cl"
                    break
        if not hit:
            mt = re.match(r'Reland (?:of )?"?(.*?)"?(?: \(\d+(?:st|nd|rd|th) attempt\))?$', d["subj"], re.I)
            if mt:
                for x in bytitle.get(mt.group(1).strip().strip('"').lower(), []):
                    if x["reverted"] < m["landed"] <= x["reverted"] + 90 * 86400 and x["reverted_email"] == m["email"]:
                        hit, how = x, "title"
                        break
        if hit and m["landed"] > hit["reverted"] and d["sha"] != hit["reverted_sha"]:
            cands[hit["reverted_sha"]].append((m["landed"], d["sha"], m["cn"], how))
    for s, lst in cands.items():
        lst.sort()
        r = bysha[s]
        t, sha, cn, how = lst[0]
        r.update(relanded=1, reland_sha=sha, reland_days=(t - r["reverted"]) / 86400, reland_cn=cn, reland_method=how)
    for r in rows:
        if r["reland_sha"] and r["reland_sha"] in bysha:
            r["reland_reverted"] = 1
    return rows


def load_rows(out):
    p = os.path.join(out, "reverts_full.jsonl")
    return [json.loads(l) for l in open(p)]


def cmd_table(a):
    rows, meta = load_reverts(a.out)
    rows = find_relands(a.out, rows, meta)
    S = a.out
    with open(os.path.join(S, "revert_reasons.tsv"), "w") as f:
        f.write("reverted_sha\trevert_sha\treverted_change_number\tlanded_at\treverted_at\treason_class\t"
                "reverter_role\trelanded\treland_days\treland_change_number\n")
        for r in rows:
            f.write("\t".join(str(x) for x in [
                r["reverted_sha"], r["revert_sha"], r["reverted_cn"] or "", r["landed"], r["reverted"], r["cls"],
                r["role"], r["relanded"], "" if r["reland_days"] is None else f"{r['reland_days']:.3f}",
                r["reland_cn"] or ""]) + "\n")
    with open(os.path.join(S, "reverts_full.jsonl"), "w") as f:    # reason text is public Gerrit text
        for r in rows:
            f.write(json.dumps(r) + "\n")
    n = len(rows)
    print("reverts (distinct reverted commits)", n)
    c = Counter(r["cls"] for r in rows)
    for k in CLASSES:
        print(f"{k:26s}{c[k]:6d} {100 * c[k] / n:5.1f}%")
    print(Counter(r["role"] for r in rows), "relanded", sum(r["relanded"] for r in rows),
          Counter(r["reland_method"] for r in rows), "reland_reverted", sum(r["reland_reverted"] for r in rows))
    print("empty reasons", sum(1 for r in rows if not r["reason"]), "bot-stamped", sum(1 for r in rows if r["bot_stamped"]))


def cmd_samples(a):
    rows = load_rows(a.out)
    rnd = random.Random(7)
    for c in CLASSES:
        xs = [r for r in rows if r["cls"] == c]
        print(f"\n== {c} ({len(xs)})")
        for r in rnd.sample(xs, min(10, len(xs))):
            print("  -", r["reason"][:100])


# ------------------------------------------------------------------ cost
def size10(lines):
    import math
    return min(9, max(0, int(math.log2(max(lines or 0, 1))) - 1))


def boot_ci(xs, fn, n=400, seed=11):
    rnd = random.Random(seed)
    k = len(xs)
    if k < 5:
        return (None, None)
    vals = sorted(fn([xs[rnd.randrange(k)] for _ in range(k)]) for _ in range(n))
    return (vals[int(0.025 * n)], vals[int(0.975 * n)])


def summ(xs):
    """mean and median with bootstrap 95% CIs (resampling CLs)."""
    if not xs:
        return None
    lo, hi = boot_ci(xs, st.mean)
    mlo, mhi = boot_ci(xs, st.median)
    r = lambda v: None if v is None else round(v, 2)
    return dict(n=len(xs), mean=r(st.mean(xs)), mean_ci=[r(lo), r(hi)], median=r(st.median(xs)), median_ci=[r(mlo), r(mhi)])


def load_cl():
    d = ro("balance.sqlite")
    att = dict(d.execute("SELECT change_number, sum(hours) FROM cl_attention GROUP BY change_number"))
    top = {}
    for cn, dr, lines in d.execute("SELECT change_number, dir, lines FROM cl_dirs ORDER BY lines"):
        top[cn] = "/".join(dr.strip("/").split("/")[:2])        # the last row per CL is its largest dir
    end = d.execute("SELECT max(closed_at) FROM cl").fetchone()[0]
    cl = {}
    for (cn, status, cr, cl_at, gl, files, th, rounds, rw, ow, isrev, isrel, rat, ck) in d.execute(
            "SELECT change_number, status, created_at, closed_at, git_lines, files, threads, rounds, reviewer_wait_h, "
            "owner_wait_h, is_revert, is_reland, reverted_at, comments FROM cl"):
        cl[cn] = dict(status=status, created=cr, closed=cl_at, lines=gl or 0, files=files or 0, threads=th or 0,
                      rounds=rounds or 0, att=att.get(cn, 0.0), owner_h=ow or 0.0, rev_wait_h=rw or 0.0,
                      life_h=((cl_at - cr) / 3600 if cl_at else None), is_rev=isrev, is_rel=isrel, reverted=rat,
                      comments=ck or 0, dir2=top.get(cn, "?"), s10=size10(gl))
    return cl, end


METRICS = [("threads", "review threads"), ("rounds", "rounds"), ("att", "reviewer attention h"),
           ("owner_h", "owner attention h"), ("life_h", "creation to landing h")]


def cmd_cost(a):
    rows = load_rows(a.out)
    cl, end = load_cl()
    ok = lambda c: c and c["status"] == "MERGED" and c["closed"] and c["life_h"] is not None and c["files"] < 100
    ctrl = [c for c in cl.values() if ok(c) and not c["is_rev"] and not c["is_rel"] and not c["reverted"]
            and SINCE_TS <= c["closed"] <= end - 30 * 86400]
    strata, size_only = defaultdict(list), defaultdict(list)
    for c in ctrl:
        strata[(c["s10"], c["dir2"])].append(c)
        size_only[c["s10"]].append(c)
    cache = {}

    def expected(c, m):
        k = (c["s10"], c["dir2"], m)
        if k not in cache:
            s = strata.get((c["s10"], c["dir2"]), [])
            if len(s) < 20:
                s = size_only[c["s10"]]
            cache[k] = st.mean(x[m] for x in s)
        return cache[k]

    out = dict(controls=len(ctrl))
    groups = {"reverted": [cl.get(r["reverted_cn"]) for r in rows],
              "reland": [cl.get(r["reland_cn"]) for r in rows if r["relanded"]]}
    groups = {k: [c for c in v if ok(c)] for k, v in groups.items()}
    print("controls", len(ctrl), {k: len(v) for k, v in groups.items()})
    out["control"] = {m: dict(n=len(ctrl), mean=round(st.mean(c[m] for c in ctrl), 2), median=round(st.median(c[m] for c in ctrl), 2)) for m, _ in METRICS}
    for g, cs in groups.items():
        out[g] = {"n": len(cs)}
        for m, lab in METRICS:
            raw = [c[m] for c in cs]
            exc = [c[m] - expected(c, m) for c in cs]
            out[g][m] = dict(raw=summ(raw), excess_vs_same_size_dir=summ(exc))
            print(f"{g:9s}{lab:24s} mean {out[g][m]['raw']['mean']:8.1f} median {out[g][m]['raw']['median']:7.1f}"
                  f" | excess mean {out[g][m]['excess_vs_same_size_dir']['mean']:8.1f} CI {out[g][m]['excess_vs_same_size_dir']['mean_ci']}")
    rv = [(r, cl.get(r["revert_cn"])) for r in rows]
    rv = [(r, c) for r, c in rv if c and c["status"] == "MERGED" and c["life_h"] is not None]
    out["revert_cl"] = {"n": len(rv)}
    for lab, sel in (("all", lambda r: True), ("bot_stamped", lambda r: r["bot_stamped"]),
                     ("not_bot_stamped", lambda r: not r["bot_stamped"])):
        xs = [c for r, c in rv if sel(r)]
        hr = [c for c in xs if c["att"] > 0 or c["threads"] > 0]
        out["revert_cl"][lab] = dict(n=len(xs), human_review_share=round(len(hr) / max(len(xs), 1), 3),
                                     att_h=summ([c["att"] for c in xs]), att_h_when_reviewed=summ([c["att"] for c in hr]),
                                     threads_when_reviewed=summ([c["threads"] for c in hr]),
                                     life_h=summ([c["life_h"] for c in xs]), owner_h=summ([c["owner_h"] for c in xs]))
    cyc = {k: [] for k in ("att", "owner_h", "threads", "rounds", "life_h")}
    for r in rows:
        if not r["relanded"]:
            continue
        rl, rc = cl.get(r["reland_cn"]), cl.get(r["revert_cn"])
        if not ok(rl) or not rc or rc["life_h"] is None:
            continue
        for m in cyc:
            cyc[m].append(rl[m] + rc[m])
    out["cycle_reland_plus_revert"] = {m: summ(v) for m, v in cyc.items()}
    only = [c for r, c in rv if not r["relanded"]]
    out["revert_only_no_reland"] = {m: summ([c[m] for c in only]) for m in ("att", "owner_h", "threads", "life_h")}
    print("cycle", {m: (v["n"], v["mean"], v["mean_ci"], v["median"]) for m, v in out["cycle_reland_plus_revert"].items()})
    print("revert cl", {k: (v if k == "n" else (v["n"], v["human_review_share"], v["att_h"]["mean"], v["att_h_when_reviewed"] and v["att_h_when_reviewed"]["median"])) for k, v in out["revert_cl"].items()})
    json.dump(out, open(os.path.join(a.out, "cost.json"), "w"), indent=1)


# ----------------------------------------------------------------- timing
BINS = [("<1h", 0, 1), ("1-6h", 1, 6), ("6-24h", 6, 24), ("1-7d", 24, 168), ("7-30d", 168, 720), ("30d+", 720, 1e12)]


def binof(h):
    for n, lo, hi in BINS:
        if lo <= h < hi:
            return n


def cmd_timing(a):
    import datetime as dt
    rows = load_rows(a.out)
    n = len(rows)
    out = dict(n_reverts=n)
    utc = dt.timezone.utc
    for r in rows:
        r["h"] = (r["reverted"] - r["landed"]) / 3600
        r["bin"] = binof(max(r["h"], 0))
        r["year"] = dt.datetime.fromtimestamp(r["reverted"], utc).year
    cnt = Counter(r["cls"] for r in rows)
    out["class_share"] = {c: dict(n=cnt[c], pct=round(100 * cnt[c] / n, 1)) for c in CLASSES}
    out["by_bin"] = {b: sum(1 for r in rows if r["bin"] == b) for b, _, _ in BINS}
    out["bin_by_class"] = {c: {b: sum(1 for r in rows if r["cls"] == c and r["bin"] == b) for b, _, _ in BINS} for c in CLASSES}
    out["median_hours_to_revert_by_class"] = {c: round(st.median([r["h"] for r in rows if r["cls"] == c] or [0]), 1) for c in CLASSES}
    out["median_hours_to_revert"] = round(st.median(r["h"] for r in rows), 1)
    w30 = [r for r in rows if r["h"] <= 720]
    out["within30d"] = len(w30)
    out["share_of_30d_reverts_within_24h"] = round(sum(1 for r in w30 if r["h"] <= 24) / len(w30), 3)
    out["share_of_30d_reverts_within_24h_by_class"] = {
        c: round(sum(1 for r in w30 if r["cls"] == c and r["h"] <= 24) / max(sum(1 for r in w30 if r["cls"] == c), 1), 3) for c in CLASSES}
    g = sqlite3.connect(f"file:{commits.db_path(DATA)}?mode=ro", uri=True)
    land = Counter()
    for (la,) in g.execute("SELECT landed_at FROM gcommits WHERE reverts_sha IS NULL AND is_bot = 0 AND landed_at >= ?", (SINCE_TS,)):
        land[dt.datetime.fromtimestamp(la, utc).year] += 1
    out["by_year"] = {}
    strict = {"flaky_or_unrelated", "dependent_or_requested"}
    for y in (2023, 2024, 2025, 2026):
        ys = [r for r in rows if r["year"] == y]
        k = Counter(r["cls"] for r in ys)
        m = max(len(ys), 1)
        out["by_year"][y] = dict(reverts=len(ys), landed_nonbot_commits=land[y], per_1000_commits=round(1000 * len(ys) / max(land[y], 1), 2),
                                 class_pct={c: round(100 * k[c] / m, 1) for c in CLASSES},
                                 within24h_pct=round(100 * sum(1 for r in ys if r["h"] <= 24) / m, 1),
                                 not_preventable_strict_pct=round(100 * sum(1 for r in ys if r["cls"] in strict) / m, 1),
                                 relanded_pct=round(100 * sum(r["relanded"] for r in ys) / m, 1))
    out["not_preventable_strict_pct"] = round(100 * sum(1 for r in rows if r["cls"] in strict) / n, 1)
    out["not_preventable_broad_pct"] = round(100 * sum(1 for r in rows if r["cls"] in NOT_PREVENTABLE) / n, 1)
    out["roles_pct"] = {k: round(100 * v / n, 1) for k, v in Counter(r["role"] for r in rows).items()}
    out["role_by_class"] = {c: dict(Counter(r["role"] for r in rows if r["cls"] == c)) for c in CLASSES}
    out["bot_stamped_revert_share"] = round(sum(1 for r in rows if r["bot_stamped"]) / n, 3)
    out["median_hours_to_revert_by_role"] = {k: round(st.median([r["h"] for r in rows if r["role"] == k]), 1) for k in ("author", "approver", "third_party", "bot")}
    rl = [r for r in rows if r["relanded"]]
    ds = sorted(r["reland_days"] for r in rl)
    out["reland"] = dict(n=len(rl), pct=round(100 * len(rl) / n, 1), median_days=round(st.median(ds), 2),
                         p25_days=round(ds[len(ds) // 4], 2), p75_days=round(ds[3 * len(ds) // 4], 2),
                         reverted_again_n=sum(r["reland_reverted"] for r in rl),
                         reverted_again_pct=round(100 * sum(r["reland_reverted"] for r in rl) / len(rl), 1),
                         methods=dict(Counter(r["reland_method"] for r in rl)))
    out["reland_pct_by_class"] = {c: round(100 * sum(r["relanded"] for r in rows if r["cls"] == c) / max(cnt[c], 1), 1) for c in CLASSES}
    out["reverted_commit_is_itself_a_revert_pct"] = round(100 * sum(1 for r in rows if r["reverted_is_revert"]) / n, 1)
    out["multi_revert_n"] = sum(1 for r in rows if r["n_reverts"] > 1)
    json.dump(out, open(os.path.join(a.out, "timing.json"), "w"), indent=1)
    print(json.dumps({k: v for k, v in out.items() if k not in ("role_by_class",)}, indent=1))


def cmd_results(a):
    res = {f: json.load(open(os.path.join(a.out, f + ".json"))) for f in ("timing", "cost")}
    res["llm_pilot"] = "skipped: unknown class under 25%"
    json.dump(res, open(os.path.join(a.out, "reverts_results.json"), "w"), indent=1)
    print("wrote reverts_results.json")


def cmd_pilot(a):
    rows = load_rows(a.out)
    n = len(rows)
    u = sum(1 for r in rows if r["cls"] == "unknown")
    print(f"unknown {u}/{n} = {100 * u / n:.1f}%: under 25%, so the LLM pilot is skipped (not run).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["parse", "table", "cost", "timing", "pilot", "results", "samples"])
    ap.add_argument("--out", default=os.path.join(DATA, "scratch", "review_roi", "reverts"))
    a = ap.parse_args()
    globals()["cmd_" + a.cmd](a)
