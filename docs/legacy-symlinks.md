# Legacy symlinks: remove on 2026-11-15

On 2026-11-14 these were renamed so that each name says what it holds (the
data-flow page labels every database box with its file name). The data
files were moved in the main checkout's `data/private/`, and a symlink
with the old name was left behind, so that sessions and worktrees still on
older code keep working for a day.

| Old name (now a symlink) | New name | What it holds |
|---|---|---|
| `data/private/derived.sqlite` | `data/private/reviews.sqlite` | Per-CL, per-comment and per-thread review facts, no comment text |
| `data/private/labels.sqlite` | `data/private/addressed.sqlite` | Haiku's addressed / not-addressed label per review thread (never delete) |
| `data/private/raw.sqlite` | `data/private/gerrit.sqlite` | Every Gerrit REST response, and which weeks are done (never delete) |
| `data/private/sentiment/` | `data/private/comments/` | Review comments rendered with their thread context, the gold set and tuning results |

Code renamed in the same change (no symlinks: each worktree has its own
copy, and picks up the new names when it rebases):

| Old | New |
|---|---|
| `cosh/feedback.py` (`python3 -m cosh.feedback`) | `cosh/review_feedback.py` |
| step `affiliations` | `update-affiliations` |
| `scripts/review_roi_part1.py`, `review_roi_part1_followup.py`, `docs/review-roi-part1.md` | `review_roi_depth.py`, `review_roi_depth_followup.py`, `docs/review-roi-depth.md` |
| `scripts/review_roi_part2.py`, `docs/review-roi-part2.md` | `review_roi_later_changes.py`, `docs/review-roi-later-changes.md` |
| `scripts/balance_narrative.py` | `scripts/balance_review_load.py` |
| `scripts/balance_page_extras.py` | `page_datasets()` in `balance_signals.py`, `balance_clusters.py`, `balance_cluster_map.py` and `chrome_releases.py` |

## Removing them (2026-11-15 or later)

1. Check nothing still opens the old names: no process has them open
   (`ls -l /proc/[0-9]*/fd 2>/dev/null | grep -E
   'data/private/(derived|labels|raw)\.sqlite|data/private/sentiment/'`), and
   no worktree branch still names them (`git grep -lE
   'derived\.sqlite|labels\.sqlite|raw\.sqlite|OUT_DIR = "sentiment"'
   <branch>` for each branch with open work, the private sentiment branch
   included). Rebase any that do first.
2. In the main checkout, remove only the four symlinks, each by its own
   path, and check each is a symlink first (`ls -l`). Never `rm -r`
   `sentiment/`: a trailing slash would follow the link into
   `comments/`.

   ```bash
   rm data/private/derived.sqlite
   ```

   ```bash
   rm data/private/labels.sqlite
   ```

   ```bash
   rm data/private/raw.sqlite
   ```

   ```bash
   rm data/private/sentiment
   ```
3. Delete this file and its pointer in `docs/data-architecture.md`, and
   the reminder in the auto-memory.

## Added 2026-11-14: the review timeline

`data/private/balance-timeline.sqlite` is now a symlink to
`data/private/review-timeline.sqlite` (the NoteDb timeline left Review
Balance when the Review Load page began to read it; `python3 -m
cosh.review_timeline` writes it, with three more tables). The file as it
was before the move is in `data/private/backup-20261114/`, until a person
deletes it. Code renamed with it: `python3 -m cosh.balance timeline` is
`python3 -m cosh.review_timeline`, step `balance-timeline` is
`review-timeline`, and `COSH_BALANCE_TIMELINE` is `COSH_REVIEW_TIMELINE`.

Remove the symlink with the others, after the same checks (also grep the
open branches for `balance-timeline`):

```bash
rm data/private/balance-timeline.sqlite
```
