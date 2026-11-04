# "Addressed comment" classifier: evaluation

Status: research (2026-11-04). This follows `docs/review-impact.md`, which
proposed counting review threads that led to a change. This note builds a
labelled set, compares ways to classify a thread as **addressed**, and
measures each one's precision, recall and cost. Nothing is in the pipeline
yet.

## Summary

| Method | Precision | Recall | Accuracy | Time per 1k threads | Tokens per 1k threads | API-equivalent $ per 1k |
|---|---:|---:|---:|---:|---:|---:|
| Simple regex (owner's first reply starts with Done/Fixed/…) | 0.984 | 0.777 | 0.818 | < 1 ms | 0 | 0 |
| Pattern rules (all owner replies, change verbs, negatives) | 0.941 | 0.932 | 0.902 | 15 ms | 0 | 0 |
| Local naive Bayes (stdlib, 10-fold CV) | 0.823 | 0.977 | 0.820 | 0.2 s | 0 | 0 |
| Haiku via `claude -p`, 50 threads per call | 0.975 | 0.990 | 0.973 | 3.0 min | 235k | 0.06 |
| Regex, then Haiku for the rest (39% of threads) | 0.969 | 0.994 | 0.970 | 1.2 min | 91k | 0.02 |
| Sonnet via `claude -p`, 50 per call | 0.990 | 0.987 | 0.983 | 2.0 min | 210k | 0.88 |
| Opus via `claude -p`, 50 per call | 0.990 | 0.997 | 0.990 | 3.5 min | 218k | 1.92 |

Scores are against the 400-thread gold set (310 done, 90 not). Time is
wall-clock for serial calls. "API-equivalent $" is the `total_cost_usd`
that Claude Code reports; on Pro, the usage counts against the plan's
limits instead of being billed.

1. **The regex is a fine lower bound but misses a fifth of the changes.**
   It is right 98% of the time when it says "done", but it misses every
   change described in free text ("Used `ALLOWLISTED_PREFERENCE_KEYS`",
   "Just formatted", "I like that idea").
2. **Hand-written patterns plateau around 90% accuracy and overfit.**
   - A second rule set, tuned on the errors in the even-numbered half,
     raised that half's F1 from 0.933 to 0.952.
   - On the held-out odd half it scored 0.930, against 0.940 for the
     original rules.
   - What separates "Good point, I've changed X" from "Good point, but X
     already does Y" is meaning, not wording.
3. **A local model needs far more labels than this set has.** Naive Bayes
   on 400 examples hardly beats "always done" (0.820 accuracy against
   0.775).
4. **Any Claude model is close to the ceiling.**
   - On the 392 threads a careful reader can decide, accuracy is 0.990
     for Haiku and Sonnet and 0.995 for Opus.
   - Haiku's remaining errors lean towards "done" on vague replies
     ("ditto", "Found this sheet id …").
   - All three call a bare "Done" to "Ping me in August" done; the regex
     makes the same mistake.
5. **Recommendation: regex first, then Haiku in batches of 50–100 for the
   ~39% the regex doesn't catch,** run from scripts with headless
   `claude -p`.
   - **Accuracy:** about 0.97, with recall 0.99.
   - **Measured cost per 1k threads:** about 1.2 minutes and 91k Haiku
     tokens.
   - **Projected cost** (at 6,600 threads a week with an owner reply):
     - one week: 0.6M tokens and ~6 min;
     - one year: 31M tokens and ~7 h serial;
     - the approved 3-year range: about 100M tokens and ~23 h serial.

   This is well within reach on Pro if it's spread over a few days and run
   weekly after that (see "Cost against Pro limits").
   - **Upgrades:** use Haiku on everything (0.973) if the regex's
     false "Done"s matter. Use Opus (0.990 overall) only for a small
     audit sample, since it costs about 30× Haiku.

## Task and labels

- **Unit.** A reviewer-started thread with at least one reply from the
  owner side (the owner, or anyone who uploaded a patchset). It is
  rendered as the reviewer's root comment followed by up to nine replies,
  each tagged `REVIEWER`, `OWNER` or `OTHER` (text from the stored NoteDb
  notes; `scripts/review_impact.py`, field `thread`).
  - Threads with no owner reply (28% of all threads) are out of scope.
    No reply text means nothing to classify, and they rarely led to a
    change in the CL (`review-impact.md`).
- **Population and sample.** 59,434 such threads on CLs that closed in
  2026-W36..W44; a simple random sample of 400 (seed 42). With n = 400, a
  proportion near 0.95 has a 95% interval of about ±2 points, and recall is
  measured on 310 positives.
- **Definition (given to every labeller and model):**
  - **done:** the owner changed something in the CL in response. That
    covers code, tests, comments, build files or the commit message,
    including partial adoption and a different or better fix prompted by
    the comment, and adding a TODO.
  - **not:** answered, explained, pushed back, the reviewer withdrew, an
    approval or FYI, deferred to another CL or a bug, or a bare Ack with no
    sign of a change.

  The full text is `DEFINITION` in `scripts/comment_classifier.py`.
- **Labelling (the "flash" step).** Four Haiku subagents, 100 threads
  each, ran in parallel and labelled by reading, each with a confidence.
  - They took 31–39 s each and 48–54k tokens per 100 threads. That is
    about twice the headless `claude -p` cost, because of the subagent's own
    context.
  - Result: 310 done, 90 not, 34 marked low-confidence.
- **Adjudication.** I (Opus, in the main session) read every thread where
  any of the three headless models disagreed with the Haiku label, plus
  every low-confidence one: 37 threads.
  - I changed 8 labels:
    - 4 not → done: T161 and T222 (moving code *out of* this CL is a
      change; Haiku had labelled the same case in T292 as done), T013
      ("the feedback was definitely helpful") and T226 ("Sgtm").
    - 4 done → not: T275 (screenshots, not code), T301 (explained, not
      fixed), T311 (just "ditto" to another thread) and T398 ("Done" to
      "ping me in August").
  - 8 threads stay genuinely ambiguous to a careful reader (T013, T029,
    T213, T226, T258, T275, T311, T359), so about 2% label noise is a
    floor for any method.
  - A spot check of 30 random threads that weren't adjudicated found 30 of
    30 labels correct.
- **Caveat.** Adjudication was triggered by model disagreement, so errors
  that every model shares with the Haiku labeller could survive. The spot
  check bounds that: 0 of 30, so probably under ~5% of the
  non-adjudicated threads.

## Results in detail

### Held-out half (odd ids, n = 200)

The pattern rules were written before any labels existed. `rules2` was
tuned on the even half only.

| Method | Precision | Recall | F1 | Accuracy |
|---|---:|---:|---:|---:|
| regex | 0.975 | 0.763 | 0.856 | 0.805 |
| rules | 0.947 | 0.934 | 0.940 | 0.910 |
| rules2 (tuned on even half) | 0.940 | 0.921 | 0.930 | 0.895 |
| naive Bayes (10-fold CV) | 0.802 | 0.961 | 0.874 | 0.790 |
| Haiku, batches of 50 | 0.962 | 0.993 | 0.977 | 0.965 |
| Haiku, batches of 100 | 0.962 | 0.993 | 0.977 | 0.965 |
| Sonnet | 1.000 | 0.987 | 0.993 | 0.990 |
| Opus | 0.987 | 1.000 | 0.993 | 0.990 |

### Without the 8 ambiguous threads (n = 392)

| Method | Precision | Recall | Accuracy |
|---|---:|---:|---:|
| regex | 0.988 | 0.785 | 0.824 |
| rules | 0.948 | 0.941 | 0.913 |
| Haiku | 0.990 | 0.997 | 0.990 |
| Sonnet | 0.990 | 0.997 | 0.990 |
| Opus | 0.997 | 0.997 | 0.995 |

### What each method gets wrong

- **Regex.**
  - **False positives:** "Done" replies to things that weren't change
    requests ("committed" / "Done", "Ping me in August" / "Done").
  - **False negatives:** every free-text change ("Removed. Thanks for
    flagging!" matches, but "Used `X`", "Just formatted", "I like that,
    thanks" and "renamed on latest patchset" don't).
- **Rules.**
  - **False positives:** explanations that contain change words ("…
    removes that notice suggestion from suggestions list…", "would have
    been removed in non-debug builds"), and fixes made in another CL
    ("Updated the page seq logic in cl/8299152").
  - **False negatives:** agreement with no verb ("Sgtm", "Weird that my IDE
    didn't catch this"), and "Acknowledged. Added a TODO … in a follow-up",
    where a negative word vetoes a real change.
- **Naive Bayes.** With 90 negatives it learns little beyond "most threads
  are done".
- **LLMs.** Haiku 11 errors (7 on ambiguous threads), Sonnet 7 (3), Opus 4
  (2).
  - The errors that aren't ambiguous: "Done" to a reminder request (all
    three); "We switched r8 … so that made this redundant" (Haiku: done);
    "I'll update this doc … another CL" (Sonnet: not); and a thread where a
    third reviewer later reversed the approach (Opus: not).
- **Batch size.** Haiku with 100 threads per call gave the same accuracy as
  50 and was 20% faster, but one bad JSON response would lose more work.
  The script records missing ids (none were missing here).

## Cost

### How the models were run

The models run through Claude Code's headless mode, which uses the Pro
login (no API key on this machine):

```
claude -p --model haiku --output-format json --tools "" \
  --system-prompt "You are a precise classifier of code-review threads." \
  --strict-mcp-config --mcp-config '{"mcpServers":{}}' --disable-slash-commands \
  --exclude-dynamic-system-prompt-sections --no-session-persistence \
  --json-schema '<labels schema>'  < prompt
```

- **Overhead.** A plain `claude -p` call carries about 15.7k tokens of
  Claude Code context, its system prompt and tool definitions. The
  `--system-prompt` and no-tools flags cut that to 12.8k, and disabling MCP
  servers and slash commands cut it to **about 0.7k**. That matters more
  than the model choice when threads are classified one at a time.
- **`--bare`** would be leaner still, but it accepts only
  `ANTHROPIC_API_KEY`, not the Pro login.
- **Run directory.** Run from a scratch directory: the classifier
  needs no project context.
- **Structured output.** `--json-schema` makes the reply a validated
  `{"labels": [{"id", "done"}]}` object (`structured_output` in the JSON
  result). All 400 ids came back in every run.
- **Per-thread cost.**
  - About 210–235 tokens per thread, almost all input. The thread text
    averages about 110 tokens. The rest is the definition, repeated once
    per call (the cache-creation tokens), and Haiku's longer output (37
    tokens per thread, against 13 for Sonnet).
  - Larger batches spread the per-call part more thinly.
  - A local model and the regex cost nothing.

### Projections

There are about 6,600 threads with an owner reply each week.

| Mechanism | One week | One year | 3-year range (175 weeks) |
|---|---|---|---|
| Regex + Haiku (b100) on the 39% left | 0.5M tokens, ~6 min, $0.13 | 28M tokens, 5.4 h, $7 | 96M tokens, 18 h, $23 |
| Haiku (b100) on everything | 1.4M tokens, ~17 min, $0.34 | 73M tokens, 14 h, $18 | 247M tokens, 47 h, $60 |
| Sonnet on everything | 1.4M tokens, ~12 min, $5.84 | 72M tokens, 12 h, $304 | 243M tokens, 39 h, $1,022 |
| Opus on everything | 1.4M tokens, ~24 min, $12.70 | 75M tokens, 20 h, $660 | 252M tokens, 68 h, $2,222 |

Hours are serial. Two to four `claude -p` processes in parallel divide them
accordingly, but they also use the Pro limits faster. The $ figures are
API-equivalent list prices; on Pro they translate to limit usage, not
charges.

### Cost against Pro limits

- **What Anthropic publishes:**
  - Pro has a rolling 5-hour session limit and a weekly limit.
  - Both are shared between claude.ai and Claude Code.
  - The size is given only as multiples of the Free plan, not as token
    counts.
  - Usage depends on the model and on message length.
  - Third-party guides estimate about 45 Claude Code prompts per 5 hours
    on Pro. These figures are unofficial and varied during 2026's
    promotions.
- **So the honest unit is measured relative use.**
  - **This session.** The part of this session after entering the
    worktree used 12.7M Opus tokens over 81 calls (12.4M of them cache
    reads) and stayed within the limits.
  - **Per call.** A Haiku classification call of 100 threads uses about
    21k tokens, and Haiku costs far less per token than Opus (about 1/35
    by Claude Code's own `total_cost_usd`: $0.056 against $1.92 per 1k
    threads).
  - **Weekly run.** The weekly regex-plus-Haiku run (0.5M Haiku tokens) is
    a rounding error next to a working session.
  - **One-year backfill.** It is about $7 API-equivalent (28M Haiku
    tokens), a little over twice this session's token count, but on the
    much cheaper model.
- **Suggested way to confirm.**
  1. Note `/usage`.
  2. Classify one week (≈2.6k threads after the regex, 26 Haiku calls, ~6
     minutes).
  3. Note `/usage` again, and scale from the difference.
  4. Spread a backfill over several 5-hour windows or days, and never run
     it alongside interactive work, so the shared limits stay available.

Sources for the plan structure:
- [Claude support: usage limits](https://support.claude.com/en/articles/15910845)
- [Claude Code usage limits by plan (morphllm)](https://www.morphllm.com/claude-code-usage-limits)
- [Claude usage limits 2026: 5-hour sessions and weekly caps](https://www.ai-toolbox.co/claude-management-and-productivity/claude-usage-limits-2026)

## Recommendation

1. **Store the regex result for every thread** (free, precision 0.98). It
   is the floor and needs no model.
2. **Classify the rest with Haiku** in batches of 100 via headless
   `claude -p`, with the definition above.
   - Store `addressed`, `classifier` (`regex` or `haiku-<version>`) and the
     definition's version per thread, in `derived.sqlite` or a sidecar
     cache keyed by comment uuid. That way a rerun classifies only new
     threads, and a model change is a versioned rebuild, like
     `metric_version`.
   - Run it after `derive`, as a separate, resumable, rate-limited step,
     never inside `derive`.
3. **Audit.** Each quarter, have Opus label about 200 threads chosen at
   random and compare. If Haiku's agreement drops below about 0.95, revisit
   the prompt.
4. **Not worth it:**
   - more regex rules (they overfit at about 0.90);
   - a local model, unless several thousand labels are produced first, for
     example by Haiku itself. That would only reproduce Haiku, more cheaply
     at run time.
5. **Keep the boundary cases explicit in the definition:**
   - a change made in another CL is "not";
   - moving code out of the CL is "done";
   - a "Done" to a non-request is "not".

   These caused most of the disagreements between models.

## Planned design: addressed comments as the headline metric

Status: planned (2026-11-04), not built. Decided by the user: this becomes
the headline metric, classification is its own pipeline step, and the UI
must work with no labels or only some. Defaults still to confirm are
marked *(default)*.

### Scoring

- **Unit and credit.** A thread is a reviewer's top-level comment plus all
  its replies (Gerrit `parentUuid` chains). If the thread led to a change
  in the CL, **every comment in it by a non-author account earns one
  point**. The point goes to that comment's account, and to the account's
  org as of the comment's date.
  - A reviewer who goes back and forth earns a point per comment.
  - A third reviewer who joins earns points for their own comments.
- **No points:**
  - in a thread that ended without a change;
  - in a thread the author side never answered, since there is nothing to
    classify;
  - to the CL author side. That is the owner plus anyone who uploaded a
    patchset *(default)*, so co-authors don't score on their own CLs;
  - to bots, as today.
- **Trailing comments.** Non-author comments written after the author
  side's last reply ("Thanks", "LGTM") earn no point, since they came after
  the change *(default)*.
- **Same rules as today otherwise:** each point counts in the week its
  comment was written; the path scope (`config/paths.txt`) and the
  metric_version 6 placement apply; self-declared AI comments from a
  person's own account count.
- **Model input.** The classifier sees the whole thread, capped at a few
  thousand tokens, not the prototype's 9 replies of 800 characters each.
  Per-comment credit needs the model to see every comment.

### Pipeline

```
derive    (rebuildable)  raw + NoteDb -> derived.sqlite: comments + threads (+ regex result)
classify  (new, costs Pro usage)  pending threads -> claude -p (Haiku, batches of 100) -> labels.sqlite
summarize (rebuildable)  derived.sqlite + labels.sqlite (read-only ATTACH) -> summaries/
```

- **`cosh classify` is a separate command.** It never runs inside `derive`.
  - **Pending threads:** those with an author reply, where the regex
    doesn't say done, and with no label yet for their current input hash
    and the active classifier.
  - **Rendering:** it renders the pending threads from NoteDb (comment text
    isn't stored in `derived.sqlite`) and sends them in batches.
  - **Writes:** labels are written per batch, so an interrupted run loses
    at most one batch, and a rerun continues where it stopped.
  - **Lock:** it takes its own `data/private/classify.lock`. It puts no load
    on Gerrit, so it may run while an extractor runs, as `derive` can.
  - **Limits:** a `--max-threads` cap lets a run be sized to the Pro
    limits.
- **`summarize` without labels is fine:**
  - with no `labels.sqlite`, or an empty one, it still writes every other
    metric, and the addressed metric is just incomplete;
  - it never calls a model.

### `derived.sqlite` additions (rebuildable)

- **`comments`:** add `parent_uuid TEXT` and `root_uuid TEXT`. The NoteDb
  reader currently drops the reply link.
- **New `threads` table,** one row per reviewer-started thread:

  ```sql
  CREATE TABLE threads (
    host TEXT, change_number INTEGER, root_uuid TEXT,
    root_account INTEGER,
    n_comments INTEGER,
    last_author_reply_at TEXT,   -- NULL: the author side never replied (no points)
    input_hash INTEGER,          -- first 8 bytes of sha256(definition version + rendered thread), signed
    regex_addressed INTEGER,     -- free classifier, computed in derive
    PRIMARY KEY (host, change_number, root_uuid)) STRICT, WITHOUT ROWID;
  ```

### `data/private/labels.sqlite` (new; never delete, never rebuild)

LLM labels cost Pro usage to make, so this file gets the same protection
as `raw.sqlite`. It only gains rows.

```sql
CREATE TABLE classifiers (classifier_id INTEGER PRIMARY KEY,  -- 1-byte ids in label rows
  model TEXT, definition_version INTEGER, prompt_sha256 TEXT, created_at TEXT);
CREATE TABLE runs (run_id INTEGER PRIMARY KEY, classifier_id INTEGER, started_at TEXT,
  finished_at TEXT, threads INTEGER, calls INTEGER, tokens INTEGER, usd_equiv REAL);
CREATE TABLE labels (
  change_number INTEGER, root_uuid TEXT, classifier_id INTEGER, input_hash INTEGER,
  addressed INTEGER, run_id INTEGER,
  PRIMARY KEY (change_number, root_uuid, classifier_id, input_hash)) STRICT, WITHOUT ROWID;
```

- **Mapping back.** A thread's current label is the row matching its
  `(change_number, root_uuid)`, the active `classifier_id` and the
  thread's current `input_hash`.
  - **A new reply** changes the hash, so the thread is pending until it is
    relabelled (this happens on open CLs). Older labels stay as history.
  - **A new model or definition** is a new `classifier_id`. The two can be
    compared, or swapped, with nothing lost.
- **Only model labels are stored.** Regex decisions and "never answered"
  are computed free in `derive`.
- **No `host` column yet** (only Chromium Gerrit). If other hosts are
  added, add `host_id INTEGER` in front of the key.

### Size and speed

Measured with 450k rows, the 3-year volume of model labels (about 39% of
1.16M threads with an author reply), in SQLite 3:

| Layout | Size | Bytes/row | Insert all | Full scan |
|---|---:|---:|---:|---:|
| Text everywhere (host, 64-hex hash, classifier name, timestamp; rowid table) | 151 MB | 336 | 2.2 s | 31 ms |
| **Planned:** integer ids, 8-byte integer hash, text `root_uuid`, `WITHOUT ROWID` | **18 MB** | **40** | 1.1 s | 17 ms |
| Same, with `root_uuid` packed into an 8-byte integer | 14 MB | 31 | 0.8 s | 16 ms |

- **SQLite does not deduplicate strings.** Every row stores its own copy of
  a TEXT value, so a repeated classifier name like `claude-haiku-5-5/def-1`
  costs 22 bytes on every row. Integers are stored in 1–8 bytes by size,
  so `classifier_id = 1` costs one byte. Hence the lookup tables.
- **`WITHOUT ROWID`** stores rows in the primary-key B-tree itself, with no
  separate index. Most of the 8× saving comes from that and from the
  integer columns. They weren't measured separately.
- **Packing the uuid** would save another 4 MB, but it assumes every Gerrit
  uuid is `8hex_8hex`. Not worth the risk.
- **So 3 years of labels are under 20 MB**, and relabelling history adds
  little. One year is about 6 MB.
- **Speed.** Writing labels and joining them in `summarize` take about a
  second. The cost of the metric is the model calls, not the storage.

### Summaries and the UI with partial data

- **Summaries:**
  - `org_weekly` rows gain `addressed_comments` and `share_addressed`;
  - `reviewer_weekly.json` and `area_weekly.json` gain an addressed
    column;
  - `meta.addressed_coverage[week]` = decided threads ÷ threads with an
    author reply, where "decided" means the regex says done or there is a
    current label.
- **UI:**
  - The addressed metric joins the metric selector, and the selector hides
    it if the summaries don't have the column.
  - Weeks under 99% coverage are left out of the addressed charts and range
    totals, and shown as a hatched gap with "classified through week N".
    Comments, characters and reviewed CLs are unaffected, so everything
    else works on complete data from day one.
- **Headline:**
  - The headline default is the addressed metric when the selected date
    range is fully covered.
  - Otherwise it falls back to comments, with a note saying how much of the
    range is classified.

  The value ratio uses the same rule. This lets classification proceed a
  few weeks at a time.

## Reproducing

```
COSH_DATA_DIR=<main>/data/private python3 scripts/review_impact.py --weeks 2026-W36:2026-W44 --out $T/threads.jsonl
python3 scripts/comment_classifier.py dataset $T/threads.jsonl $T/cc --n 400   # + batch_NN.txt for labellers
# labels: labels_00..03.jsonl from the Haiku subagents -> gold.jsonl after adjudication
python3 scripts/comment_classifier.py predict $T/cc regex     # also: rules, rules2, nb
TMPDIR=$T python3 scripts/comment_classifier.py llm $T/cc haiku --batch 50   # also sonnet, opus
python3 scripts/comment_classifier.py score $T/cc [--half odd]
```

The dataset, labels and predictions hold Gerrit comment text, which is
public data. They live in the job's scratch directory and are not
committed. Rebuilding the dataset with the same seed gives the same 400
threads. The adjudicated label overrides are listed under "Task and
labels".
