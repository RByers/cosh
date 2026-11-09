"""A map of the six git-model activity patterns, for the Review Balance page
(docs/balance-clusters.md, "Map and rules").

Reads data/private/balance_clusters/people.json (scripts/balance_clusters.py)
and writes balance_clusters/map.json with aggregates only:

- density cells: person-halves binned on PC1 x PC2 and PC1 x PC3, with the
  most common pattern in each cell; cells with fewer than MIN_CELL
  person-halves are dropped, so no point stands for one person;
- one ellipse per pattern and view (mean +- 1.5 SD along the principal axes
  of its PCA scores) with the share of the pattern's half-years inside;
- the PCA loadings of the nine features;
- plain rules on raw counts (rule() below) and how often they agree with the
  clusters, per pattern.

  COSH_DATA_DIR=<main>/data/private python3 scripts/balance_cluster_map.py
"""

import json
import math
import os
import statistics as st
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cosh import store  # noqa: E402

BIN = 0.25          # PC units per cell
MIN_CELL = 5        # person-halves; smaller cells are dropped
RADIUS = 1.5        # ellipse radius in SDs (about 68% for a 2-D normal)
VIEWS = {"pc2": 1, "pc3": 2}  # y axis -> index into git_pc

# Rule thresholds (rule()).
MENTOR_SHARE = 1 / 3
LINES = 40
COMMITS = 12
APPROVALS = 50
REVIEW_SHARE = 0.5


def rule(commits, approvals, lines, review_share, newcomer_share, owner):
    """The pattern plain thresholds give, in order; agrees with k-means for
    about four person-halves in five (docs/balance-clusters.md)."""
    if newcomer_share >= MENTOR_SHARE:
        return "reviewer-mentors"
    if owner and commits >= COMMITS:
        return "authors who also review a lot" if approvals >= APPROVALS else "steady authors"
    if owner and review_share >= REVIEW_SHARE:
        return "mostly reviewing"
    return "newcomers ramping up" if lines >= LINES else "early-career, light activity"


def ellipse(pts):
    n = len(pts)
    mx = sum(x for x, _ in pts) / n
    my = sum(y for _, y in pts) / n
    sxx = sum((x - mx) ** 2 for x, _ in pts) / n
    syy = sum((y - my) ** 2 for _, y in pts) / n
    sxy = sum((x - mx) * (y - my) for x, y in pts) / n
    tr, det = sxx + syy, sxx * syy - sxy * sxy
    l1 = tr / 2 + math.sqrt(max(0.0, tr * tr / 4 - det))
    l2 = max(1e-9, tr - l1)
    ang = 0.5 * math.atan2(2 * sxy, sxx - syy)
    rx, ry = RADIUS * math.sqrt(l1), RADIUS * math.sqrt(l2)
    c, s = math.cos(ang), math.sin(ang)
    inside = sum(1 for x, y in pts
                 if (((x - mx) * c + (y - my) * s) / rx) ** 2 + ((-(x - mx) * s + (y - my) * c) / ry) ** 2 <= 1)
    return dict(cx=round(mx, 3), cy=round(my, 3), rx=round(rx, 3), ry=round(ry, 3), angle=round(ang, 4),
                inside=round(inside / n, 3))


def main():
    d = os.path.join(store.DATA_DIR, "balance_clusters")
    people = json.load(open(os.path.join(d, "people.json")))
    model = json.load(open(os.path.join(d, "clusters.json")))["git_model"]
    rows = []
    for x in people.values():
        for h in x["halves"].values():
            if h.get("git_cluster"):
                rows.append(h)
    out = dict(cells=[], ellipses=[], loadings=[], rules=[], summary={})
    for view, j in VIEWS.items():
        cells = defaultdict(Counter)
        pts = defaultdict(list)
        for h in rows:
            pc = h["git_pc"]
            cells[(math.floor(pc[0] / BIN), math.floor(pc[j] / BIN))][h["git_cluster"]] += 1
            pts[h["git_cluster"]].append((pc[0], pc[j]))
        dropped = 0
        for (bx, by), c in sorted(cells.items()):
            n = sum(c.values())
            if n < MIN_CELL:
                dropped += n
                continue
            top, k = c.most_common(1)[0]
            out["cells"].append(dict(view=view, x=round((bx + 0.5) * BIN, 3), y=round((by + 0.5) * BIN, 3), n=n,
                                     pattern=top, share=round(k / n, 3)))
        out["summary"][f"dropped_{view}"] = dropped
        for name, ps in sorted(pts.items()):
            out["ellipses"].append(dict(view=view, pattern=name, **ellipse(ps)))
    comps = model["pca"]["components"]
    for i, f in enumerate(model["features"]):
        out["loadings"].append(dict(feature=f, pc1=round(comps[0][i], 3), pc2=round(comps[1][i], 3),
                                    pc3=round(comps[2][i], 3)))
    pred = []
    for h in rows:
        f, r = h["features"], h["raw"]
        pred.append((rule(r["commits"] or 0, r["approvals"] or 0, r["median_lines"] or 0, f["review_share"] or 0,
                          f["newcomer_approvals"] or 0, f["owner"]), h["git_cluster"]))
    for name in sorted({c for _, c in pred}):
        tp = sum(1 for a, b in pred if a == b == name)
        hs = [h for h in rows if h["git_cluster"] == name]
        med = lambda xs: st.median(xs) if xs else None  # noqa: E731
        out["rules"].append(dict(
            pattern=name, recall=round(tp / len(hs), 3),
            precision=round(tp / max(1, sum(1 for a, _ in pred if a == name)), 3),
            commits=med([h["raw"]["commits"] or 0 for h in hs]),
            approvals=med([h["raw"]["approvals"] or 0 for h in hs]),
            lines=med([h["raw"]["median_lines"] for h in hs if h["raw"]["median_lines"] is not None]),
            review_share=round(med([h["features"]["review_share"] or 0 for h in hs]), 3),
            newcomer_share=round(med([h["features"]["newcomer_approvals"] or 0 for h in hs]), 3),
            tenure=round(med([math.expm1(h["features"]["tenure"]) for h in hs]), 1),
            owner=round(sum(h["features"]["owner"] for h in hs) / len(hs), 3)))
    var = model["pca"]["variance"]
    out["summary"].update(person_halves=len(rows), agreement=round(sum(a == b for a, b in pred) / len(pred), 3),
                          pc1=round(var[0], 3), pc2=round(var[1], 3), pc3=round(var[2], 3),
                          silhouette=round(model["silhouette"], 3), bin=BIN, min_cell=MIN_CELL)
    with open(os.path.join(d, "map.json"), "w") as fh:
        json.dump(out, fh, indent=1)
    print(f"cells {len(out['cells'])}, agreement {out['summary']['agreement']:.1%}, "
          f"dropped {out['summary']['dropped_pc2']}/{out['summary']['dropped_pc3']} person-halves", file=sys.stderr)
    for e in out["ellipses"]:
        print(f"  {e['view']} {e['pattern']:32} inside {e['inside']:.0%}", file=sys.stderr)
    for r in out["rules"]:
        print(f"  rule {r['pattern']:32} recall {r['recall']:.0%} precision {r['precision']:.0%}", file=sys.stderr)


if __name__ == "__main__":
    main()
