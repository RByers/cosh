"""The return on code review: the page's datasets (docs/review-roi.md, work
package 4).

Reads the analyses' result files (plain JSON, aggregates only, no
identities) and merges these datasets into summaries/balance.json for the
Review Balance page's #roi section:

  roi_summary    one row of headline figures
  roi_odds       odds ratios of a 30-day revert, by design (the forest)
  roi_depth      30-day revert rate by review depth, raw and re-weighted (D1)
  roi_classes    revert reasons (regex classes)
  roi_timing     hours from landing to revert
  roi_panels     Part 2's long-term estimates, H2a .. H2e
  roi_substance  what addressed review threads were about (pilot, n = 200)

Inputs, in --dir (default $COSH_DATA_DIR/review_roi, else
data/private/review_roi of this checkout): part1_results.json,
part1_report.json, part2_results.json, reverts_results.json and, when it
exists, substance_results.json. They come from scripts/review_roi_part1.py,
review_roi_part2.py, review_roi_reverts.py and review_roi_substance.py.

  COSH_DATA_DIR=/home/rbagent/projects/cosh/data/private \\
      python3 scripts/review_roi_report.py [--dir DIR] [summaries/balance.json]

Offline and fast; nothing is fetched.
"""

import argparse
import json
import math
import os
import re

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The substance pilot's per-CL figures (docs/review-roi-substance.md,
# "Summary"): among CLs with an addressed thread, the share with at least one
# correctness / would-break fix, from the per-thread shares and each CL's
# count of addressed threads, assuming threads are independent within a CL.
SUB_PER_CHANGED_CL = {"correctness": 0.22, "would_break": 0.15}


def r(x, sig=4):
    """Rounded to `sig` significant digits (ints and None as they are)."""
    if x is None or isinstance(x, int) or x == 0:
        return x
    return round(x, sig - 1 - int(math.floor(math.log10(abs(x)))))


def load(d, name, required=True):
    p = os.path.join(d, name)
    if not os.path.exists(p):
        if required:
            raise SystemExit(f"missing {p}")
        return None
    with open(p) as f:
        return json.load(f)


def bin_label(b):
    """'[2, 4)' -> '2–3' for integer bins, '[2.46, 5.81)' -> '2.46–5.81'."""
    m = re.match(r"\[([^,]*), ([^)]*)\)", b)
    if not m:
        return b
    lo, hi = m.groups()
    if not lo:
        return f"< {hi}"
    if not hi:
        return f"{lo}+"
    if lo.isdigit() and hi.isdigit():
        a, z = int(lo), int(hi) - 1
        return str(a) if a == z else f"{a}–{z}"
    return f"{lo}–{hi}"


def depth_rows(rep):
    out = []
    for measure in ("threads", "attn_h", "addressed"):
        for i, row in enumerate(rep["D1"]["tables"][measure]):
            out.append({"measure": measure, "i": i, "bin": bin_label(row["bin"]), "cls": row["cls"],
                        "raw": r(row["raw"], 3), "adjusted": r(row["adjusted"], 3)})
    return out


def odds_rows(p1):
    so = p1["stratified_odds_ratios"]
    ap = p1["approver_habit_and_expertise_logit"]
    wa = p1["within_author_matched_sets"]["measures"]
    nc = p1["negative_control"]
    rows = []

    def add(key, group, label, o, lo, hi, unit, n=None):
        rows.append({"key": key, "group": group, "label": label, "or": r(o, 4), "lo": r(lo, 4), "hi": r(hi, 4),
                     "unit": unit, "n": n})

    for design, f, lo, hi in (("raw", "raw", "raw_ci", "raw_ci"), ("normalized", "stratified", "stratified_ci", "stratified_ci")):
        for m in ("threads", "attn_h", "addressed", "rubber_stamp"):
            s = so[m]
            add(f"{design}:{m}", design, s["label"], s[f], s[lo][0], s[hi][1], "above vs below the stratum median"
                if m != "rubber_stamp" else "yes vs no")
    for m in ("habit_log_first", "appr_appr3", "appr_owner", "appr_tenure"):
        s = ap[m]
        add(f"habit:{m}", "habit", m, s["odds_ratio"], *s["odds_ratio_ci"], s["unit"], s["cls"])
    for m in ("habit_log_first", "threads"):
        s = wa[m]
        add(f"within:{m}", "within author", s["label"], s["cond_or"], s["lo"], s["hi"], "conditional, matched sets",
            s["sets"])
    for k, part in (("related", "rev30_related"), ("unrelated", "rev30_unrelated")):
        s = nc[part]["habit_log_first"]
        add(f"nc:{k}", "negative control", f"habit_log_first, {part}", s["odds_ratio"], *s["odds_ratio_ci"],
            s["unit"], s["cls"])
    return rows


# Revert reasons: which group each regex class is in.
CLASS_GROUP = {
    "crash_or_functional": "review", "perf_or_size_regression": "review",
    "test_failure": "ci", "compile_or_link": "ci",
    "flaky_or_unrelated": "never", "dependent_or_requested": "never",
    "unknown": "unknown", "other": "other",
}


def class_rows(t):
    cs = t["class_share"]
    total = sum(v["n"] for v in cs.values())
    within = t["share_of_30d_reverts_within_24h_by_class"]
    med = t["median_hours_to_revert_by_class"]
    rel = t["reland_pct_by_class"]
    rows = []
    for k in ("test_failure", "compile_or_link", "crash_or_functional", "perf_or_size_regression",
              "flaky_or_unrelated", "dependent_or_requested", "unknown"):
        rows.append({"key": k, "group": CLASS_GROUP[k], "n": cs[k]["n"], "share": r(cs[k]["n"] / total, 3),
                     "within_24h": r(within[k], 3), "median_h": r(med[k], 3), "relanded": r(rel[k] / 100, 3)})
    other = [k for k in cs if k not in {x["key"] for x in rows}]  # policy, security: a few dozen
    n = sum(cs[k]["n"] for k in other)
    rows.append({"key": "other", "group": "other", "n": n, "share": r(n / total, 3), "within_24h": None,
                 "median_h": None, "relanded": None})
    return rows


def timing_rows(t):
    bins = t["by_bin"]
    total = sum(bins.values())
    cum = 0
    rows = []
    for i, (b, n) in enumerate(bins.items()):
        cum += n
        rows.append({"bin": b, "i": i, "n": n, "share": r(n / total, 3), "cum": r(cum / total, 3)})
    return rows


def panel_rows(p2):
    h = p2["h2a_h2b_panels"]["half"]["lag1"]
    c = p2["h2c"]["fits"]["split:rev2:all"]
    d = p2["h2d_szz"]["compare_size10_dir2_half"]["feedback_index"]
    e = p2["h2e_survival"]["adjusted"]
    a, b = h["fi->rev"]["fe"], h["fi->att"]["fe"]
    return [
        {"key": "H2a", "est": r(a["b"], 3), "lo": r(a["lo"], 3), "hi": r(a["hi"], 3), "unit": "pts", "null": 0,
         "n": a["n"]},
        {"key": "H2b", "est": r(b["b"], 3), "lo": r(b["lo"], 3), "hi": r(b["hi"], 3), "unit": "h", "null": 0,
         "n": b["n"]},
        {"key": "H2c", "est": r(c["coefs"][0]["or_"], 3), "lo": r(c["coefs"][0]["lo"], 3),
         "hi": r(c["coefs"][0]["hi"], 3), "unit": "or", "null": 1, "n": c["authors"]},
        {"key": "H2d", "est": r(d["diff"], 3), "lo": r(d["lo"], 3), "hi": r(d["hi"], 3), "unit": "fi", "null": 0,
         "n": d["n"]},
        {"key": "H2e", "est": r(e["high_vs_low"]["b"] * 100, 3), "lo": r(e["high_vs_low"]["lo"] * 100, 3),
         "hi": r(e["high_vs_low"]["hi"] * 100, 3), "unit": "pts", "null": 0, "n": e["n"]},
    ]


SUB_LABELS = ("docs", "style", "design", "test", "correctness", "process", "other")


def substance_rows(s):
    rows = [{"key": k, "kind": "label", "share": r(s["label"][k][0], 3), "lo": r(s["label"][k][1], 3),
             "hi": r(s["label"][k][2], 3)} for k in SUB_LABELS]
    for k in ("would_break", "nit"):
        rows.append({"key": k, "kind": "flag", "share": r(s[k][0], 3), "lo": r(s[k][1], 3), "hi": r(s[k][2], 3)})
    return rows


def summary_row(p1, rep, t, cost, sub):
    u = p1["unit"]
    d1 = rep["D1"]["tables"]
    n = rep["table"]["unit_cls"]
    no_thread = next(x["cls"] for x in d1["threads"] if x["bin"] == "[0, 1)")
    no_addr = next(x["cls"] for x in d1["addressed"] if x["bin"] == "[0, 1)")
    cs = t["class_share"]
    total = sum(v["n"] for v in cs.values())
    share = lambda *ks: sum(cs[k]["n"] for k in ks) / total
    bins = t["by_bin"]
    within24 = (bins["<1h"] + bins["1-6h"] + bins["6-24h"]) / sum(bins.values())
    in30 = sum(v for k, v in bins.items() if k != "30d+")
    in7 = in30 - bins["7-30d"]
    cyc = cost["cycle_reland_plus_revert"]["att"]
    habit = p1["approver_habit_and_expertise_logit"]["habit_log_first"]
    per1000 = habit["reverts_per_1000_change_p25_to_p75"]
    ci = habit["reverts_per_1000_change_ci"]
    rev30 = u["reverted_within_30d"]
    nc = p1["negative_control"]
    so = p1["stratified_odds_ratios"]
    wa = p1["within_author_matched_sets"]["measures"]["habit_log_first"]
    y25 = t["by_year"]["2025"]
    row = {
        "unit_cls": n, "rev7": u["reverted_within_7d"], "rev30": rev30, "rev90": u["reverted_within_90d"],
        "rubber_stamp": r(u["rubber_stamp_share"], 3), "with_thread": r(1 - no_thread / n, 3),
        "with_addressed": r(1 - no_addr / n, 4),
        "reverts": t["n_reverts"], "reverts_2025": y25["reverts"], "per_1000_2025": r(y25["per_1000_commits"], 3),
        "within_24h": r(within24, 3), "within_7d_of_30d": r(in7 / in30, 3),
        "median_h_to_revert": t["median_hours_to_revert"],
        "test_failure": r(share("test_failure"), 3), "compile": r(share("compile_or_link"), 3),
        "ci_caught": r(share("test_failure", "compile_or_link"), 3),
        "crash_functional": r(share("crash_or_functional"), 3), "perf": r(share("perf_or_size_regression"), 3),
        "review_for": r(share("crash_or_functional", "perf_or_size_regression"), 3),
        "never": r(share("flaky_or_unrelated", "dependent_or_requested"), 3),
        "unknown": r(share("unknown"), 3),
        "third_party": r(t["roles_pct"]["third_party"] / 100, 3),
        "relanded": r(t["reland"]["pct"] / 100, 3), "reland_median_days": t["reland"]["median_days"],
        "cycle_h_median": r(cyc["median"], 3), "cycle_h_mean": r(cyc["mean"], 3),
        "excess_threads": cost["reverted"]["threads"]["excess_vs_same_size_dir"]["mean"],
        "excess_attn_h": cost["reverted"]["att"]["excess_vs_same_size_dir"]["mean"],
        "threads_or_raw": so["threads"]["raw"], "threads_or_norm": so["threads"]["stratified"],
        "habit_or": habit["odds_ratio"], "habit_or_lo": habit["odds_ratio_ci"][0], "habit_or_hi": habit["odds_ratio_ci"][1],
        "habit_per_1000": r(-per1000, 3), "habit_per_1000_lo": r(-ci[1], 3), "habit_per_1000_hi": r(-ci[0], 3),
        "habit_share_of_reverts": r(-per1000 / (rev30 * 1000), 3),
        "habit_upper_share": r(-ci[0] / (rev30 * 1000), 3),
        "habit_upper_hours": r(-ci[0] * cyc["mean"], 3),
        "habit_nc_unrelated": nc["rev30_unrelated"]["habit_log_first"]["odds_ratio"],
        "habit_nc_related": nc["rev30_related"]["habit_log_first"]["odds_ratio"],
        "habit_within": wa["cond_or"], "habit_within_lo": wa["lo"], "habit_within_hi": wa["hi"],
        "within_sets": p1["within_author_matched_sets"]["sets_one_case"],
    }
    fu = p1.get("followup")
    if fu:
        # The approver's weekly CL load as an instrument for their thoroughness: the IV estimate
        # per +1 log1p thread, scaled to the p25 -> p75 gap of the habit (docs/review-roi-part1.md).
        iv = fu["approver_weekly_load_instrument"]["load_cls_log2"]["reduced_form"]["rev30"]
        gap = round(habit["p75"] - habit["p25"], 2)  # 0.37, as in the doc
        by = fu["outcome_by_reason_class"]
        rs = fu["rubber_stamp_votes_only"]
        row.update({
            "iv_per_1000": r(iv["iv_per_1000_per_log1p_thread"] * gap, 3),
            "iv_per_1000_lo": r(iv["iv_ci"][0] * gap, 3), "iv_per_1000_hi": r(iv["iv_ci"][1] * gap, 3),
            "prevent_per_1000": r(by["rev30_prevent"]["threads"]["base_rate"] * 1000, 3),
            "ci_per_1000": r(by["rev30_ci"]["threads"]["base_rate"] * 1000, 3),
            "rs_votes_or": rs["mh_or"], "rs_votes_lo": rs["mh_ci"][0], "rs_votes_hi": rs["mh_ci"][1],
        })
    if sub:
        changed = sub["cl_share_with_addressed"]["window_2025_07_2026_09"][0]
        nm = sub["revert_nearmiss"]
        row.update({
            "sub_threads": sub["n"], "sub_changed": changed,
            "sub_correctness": sub["label"]["correctness"][0],
            "sub_would_break": sub["would_break"][0], "sub_would_break_lo": sub["would_break"][1],
            "sub_would_break_hi": sub["would_break"][2], "sub_nit": sub["nit"][0],
            "sub_agree": r(sub["agreement"]["label_agree"] / sub["agreement"]["n"], 3),
            "sub_kappa": sub["agreement"]["label_kappa"], "sub_hand": sub["agreement"]["n"],
            "sub_cl_correctness": r(changed * SUB_PER_CHANGED_CL["correctness"], 3),
            "sub_cl_would_break": r(changed * SUB_PER_CHANGED_CL["would_break"], 3),
            "nearmiss_n": nm["n"], "nearmiss_yes": nm["raised"]["yes"][0], "nearmiss_partly": nm["raised"]["partly"][0],
        })
    return [row]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    default = os.path.join(os.environ.get("COSH_DATA_DIR") or os.path.join(HERE, "data", "private"), "review_roi")
    ap.add_argument("--dir", default=default)
    ap.add_argument("path", nargs="?", default=os.path.join(HERE, "summaries", "balance.json"))
    args = ap.parse_args()
    p1 = load(args.dir, "part1_results.json")
    rep = load(args.dir, "part1_report.json")
    p2 = load(args.dir, "part2_results.json")
    rv = load(args.dir, "reverts_results.json")
    sub = load(args.dir, "substance_results.json", required=False)
    new = {
        "roi_summary": summary_row(p1, rep, rv["timing"], rv["cost"], sub),
        "roi_odds": odds_rows(p1),
        "roi_depth": depth_rows(rep),
        "roi_classes": class_rows(rv["timing"]),
        "roi_timing": timing_rows(rv["timing"]),
        "roi_panels": panel_rows(p2),
    }
    if sub:
        new["roi_substance"] = substance_rows(sub)
    with open(args.path) as f:
        data = json.load(f)
    if not sub:
        data["datasets"].pop("roi_substance", None)
    data["datasets"].update(new)
    with open(args.path, "w") as f:
        json.dump(data, f, separators=(",", ":"))
        f.write("\n")
    for k, v in new.items():
        print(k, len(v), "rows")


if __name__ == "__main__":
    main()
