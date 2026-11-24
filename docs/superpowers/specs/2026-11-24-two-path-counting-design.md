# Design: two-path counting with tqdm (2026-11-24)

## Intent

The token-count run currently does everything sequentially: one blocking
subprocess per model family, and inside each worker one (model, file) count
at a time. Local tokenizers (`hf_local`, the vendored DeepSeek and Mistral
files) are CPU-heavy, so they must stay sequential to avoid loading the
machine. API tokenizers only wait on the network, so they can run in
parallel. The user also wants TQDM progress bars everywhere, because today
the run is a black box: no output until the table renders at the very end.

## Goals

- One run, two paths: API families run concurrently, local families run
  strictly one at a time.
- Visible progress with tqdm: corpus fetch, and one bar per worker over its
  (model, file) pairs, laid out so parallel workers do not garble each other.
- No change to results: same CSV columns, same dedup key
  `(model, strategy, file, sha256)`, same table, same exit-code contract
  (0 only when every worker succeeded, table rendered regardless).

## Non-goals

- No change to what is counted (no new models, no tokenizer changes, no
  baseline logic changes).
- No change to the per-family subprocess isolation or the secrets plumbing
  (`family_env` least-privilege stays).
- No re-download fix: with `--fresh` every worker still re-fetches the
  corpus, as today. Out of scope.
- No new progress IPC between workers and orchestrator (no shared counters
  over pipes). Bars live in the workers.

## Constraints

- Single `.venv`; dependencies only via `pyproject.toml` + `uv lock` +
  committed `uv.lock` + `uv sync`. Never `uv pip install`. Adding tqdm means
  exactly that path.
- Tests: stdlib `unittest` in `tests/`, run from the repo root with
  `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests`.
- Run command unchanged: `PYTHONPATH=src .venv/bin/python -m tokencount`
  (optionally `--fresh`, `--family <name>`).
- CSV contract unchanged: columns
  `timestamp,provider,model,strategy,file,file_type,sha256,chars,tokens,note`;
  notes `error: <msg>`, `n/a`, `missing key <ENV>`; `error:` rows are not
  deduped; torn trailing lines are ignored by readers.
- Offline behavior preserved: local families need no key and no network
  (beyond the cached `samples/`), and a run without API keys still exits 0
  with `missing key <ENV>` rows.
- `counters.count_tokens` signature unchanged:
  `count_tokens(strategy, model_id, text, key=None, tokenizer_file=None)`.

## Approaches

Three ways to parallelize the API path were put to the user:

1. Family-level only: run the 5 API family subprocesses concurrently, each
   counting its own models in order. Smallest change, lowest rate-limit risk.
2. Thread pool only: one worker, all 18 API models through a pool of N
   parallel HTTP calls.
3. Both (picked): the 5 API family subprocesses run concurrently AND each API
   worker counts its (model, file) pairs through an inner thread pool. Local
   families stay sequential subprocesses, one at a time.

Option 3 was chosen on 2026-11-24. Trade-off accepted: up to
5 x 4 = 20 concurrent HTTP requests, so more 429 risk than today; mitigated
by the retry bump below.

## Design (the parts decided)

### Execution split in `run.py`

- New helper `split_families(families) -> tuple[list, list]` returning
  `(api_families, local_families)`, where a family is local when its first
  model's strategy is `hf_local` (all models of a family share a strategy).
- `main()` computes `families = sorted({m.family for m in REGISTRY})`, splits
  them, then:
  1. Clears `PENDING_DIR` (`results/pending/`, wiped so a previously
     interrupted run cannot leak stale rows into this one) and fetches the
     corpus once (with a tqdm bar over the entries).
  2. Launches every API family with `subprocess.Popen(cmd, env=...)`,
     appending `--bar-position <i>` (i = 0..4 for the API families) and
     `--results-csv results/pending/<family>.csv`, then `wait()`s on all of
     them and collects return codes.
  3. Runs every local family sequentially with `subprocess.run` (as today),
     `--bar-position 0`, also writing to `results/pending/<family>.csv`.
  4. Aggregates: `aggregate_results()` appends every pending CSV into
     `results/results.csv` in sorted family order (single writer, no locks,
     header written once), drops torn trailing lines with the same rule as
     `read_dedup_keys`, then removes `PENDING_DIR`.
  5. Calls `render_results()` and returns 0 iff all return codes are 0.
  Same contract as today, just a different schedule and write path.
- Interrupt handling: the Popen phase is wrapped in try/finally. On
  KeyboardInterrupt every still-running child is `terminate()`d and waited
  on briefly, so an interrupted run leaves no orphan workers. Because
  workers write only to `PENDING_DIR`, an interrupted run never touches
  `results/results.csv`; its pending files are wiped at the start of the
  next run and the work is simply recounted. The wait itself cannot hang on
  the network: httpx
  applies a default 5 s timeout to every request (httpx docs,
  `DEFAULT_TIMEOUT_CONFIG = Timeout(timeout=5.0)`), tenacity retries only
  429 (5 attempts, 1 s apart), and any other exception becomes an `error:`
  row via `count_sample`, so a worker finishes in at most
  `items x (5 x (5 s + 1 s) + 0.1 s)` worst case.
- `--fresh` propagates to both Popen and run commands, as today.
- `--family <name>` still runs a single worker in-process with no pending
  file: it writes straight to `results/results.csv` (single process, single
  writer, no aggregation step). The worker picks pool vs sequential from its
  own family's strategy.

### Worker changes in `run.py`

- `run_worker(family, fresh, results_csv, bar_position=0)`:
  - Builds the work list once:
    `items = [(model, sample) for model in models for sample in samples
    if (model.model, model.strategy, sample.path, sample.sha256) not in deduped]`.
  - Local family (`hf_local`): plain sequential loop over
    `tqdm(items, desc=family, position=bar_position)`.
  - API family: `concurrent.futures.ThreadPoolExecutor(max_workers=API_CONCURRENCY)`.
    `_count_one(item)` only computes the row (calls `count_sample`); the
    main thread appends each row as `executor.map` yields it, wrapped in the
    same tqdm bar. All CSV appends therefore happen on one thread per
    worker, so `append_row` needs no lock at all: per-row append is kept (a
    killed worker still leaves valid rows in its pending file, and torn
    lines stay possible-but-ignored).
- Each worker writes only its own `results/pending/<family>.csv`, so no two
  processes ever share a CSV. This replaces the flock idea from the
  validate-plan round; with one writer per file there is no header race to
  fix.

### Aggregation (the race-free write path)

- `aggregate_results(pending_dir=PENDING_DIR, csv_path=RESULTS_CSV) -> int`:
  for each `*.csv` in the pending dir in sorted order, read rows with
  `csv.DictReader` (skipping rows with any missing field, the torn-line
  rule), `append_row` them into `csv_path`, then remove the pending dir.
  Runs after all workers finish, even when some worker failed (partial
  progress is aggregated, matching today's render-on-failure contract), and
  before `render_results()`.
- Dedup stays where it is: each worker reads the dedup keys from the main
  `results/results.csv` at start. Trade-off pinned: a run killed before
  aggregation loses that run's rows (the pending files are wiped next run
  and the pairs are recounted). No corruption, no race, just redo.
- Two orchestrator runs at the same time share `PENDING_DIR`; that is not
  supported. The table stays correct anyway because `table._latest_rows`
  keeps only the newest row per (model, strategy, file).
- `API_CONCURRENCY = 4` in `run.py`. My call (the user picked "both" but not
  a number): 4 per family keeps worst-case concurrency at 20 requests, and
  each call already sleeps `CALL_DELAY_SECONDS = 0.1`.
- The corpus fetch inside the worker passes `show_progress=False` (the
  orchestrator already showed the one real fetch bar); cached hits are
  instant.

### Progress bars

- Add `tqdm` to `dependencies` in `pyproject.toml`, then `uv lock`, commit
  `uv.lock`, `uv sync`.
- `corpus.fetch_corpus(entries, dest_dir="samples", fresh=False, show_progress=True)`:
  wraps the entry loop in `tqdm(entries, desc="corpus", unit="file")` when
  `show_progress` is true. Default true, so plan A behavior and the
  orchestrator call are unchanged.
- Worker bars: `tqdm(items, desc=family, unit="pair", position=bar_position,
  leave=True, disable=None)`. `disable=None` makes tqdm auto-disable on a
  non-TTY stderr (the Python API default `disable=False` would print update
  lines into CI logs); tqdm's source does exactly
  `if disable is None and not file.isatty(): disable = True`. Parallel API
  workers get distinct positions 0..4, the documented mechanism for
  multi-process bars; local workers run after them, one at a time, at
  position 0. Caveat pinned: tqdm's shared output lock does not cross Popen
  process boundaries, so interleaved bars from the 5 API workers can garble
  cosmetically on a TTY; on a non-TTY the bars disable themselves. No stuck
  state: a crashed worker's bar simply stops updating.
- No orchestrator-level aggregate bar (would need IPC; out of scope). The
  per-family bars plus the corpus bar answer "how long does stuff take".

### `counters.py` under concurrency

- `stop_after_attempt(3)` becomes `stop_after_attempt(5)` for the 429 retry
  (constant `RETRY_ATTEMPTS = 5`), wait stays `wait_fixed(1)`. My call: with
  up to 20 concurrent calls, 3 attempts is too brittle; a failed call still
  lands as an `error:` row, which is not deduped and reruns next time, so
  this is safety, not correctness.
- `_BASELINE_CACHE` needs no lock: CPython dict set/get is atomic under the
  GIL; worst case two threads compute the same 1-char baseline probe twice.
- Each `_post_json` call already builds its own `httpx.Client`, so the
  pool is thread-safe without changes.

### Tests

- `tests/test_run.py`:
  - New `test_split_families`: from the real REGISTRY, API families are
    exactly `{openai, anthropic, google, glm, kimi}` and local families
    exactly `{deepseek, mistral}`.
  - Update `TestOrchestrator`: `main([])` must call `subprocess.Popen` 5
    times (API families, each with a distinct `--bar-position` and a
    `--results-csv results/pending/<family>.csv`) and `subprocess.run` 2
    times (local families, same pending path), must call
    `aggregate_results` once before rendering, still render the table once,
    and exit 0 only when all return codes are 0 (keep the failed-worker
    test, adapted: a Popen with returncode 1 makes main return 1 but still
    aggregates and renders). Keep the env least-privilege assertions per
    family.
  - New `test_aggregate_results`: write two pending CSVs (one with a torn
    trailing line) plus an empty pending dir case; assert the main CSV gets
    exactly one header, all well-formed rows in sorted family order, no
    torn-row data, and the pending dir is gone afterwards.
  - New `test_main_clears_pending_dir_at_start`: stale file in
    `results/pending/` is gone after `main([])` runs.
  - Keep `TestWorker` as-is (it mocks `count_tokens`, so both the pool path
    and the sequential path must produce identical rows; existing tests
    cover the API family through the pool). Add one worker test for a local
    family (`deepseek`) asserting rows are written and `count_tokens` was
    called once per model (sequential path).
- `tests/test_corpus.py`: one test that `fetch_corpus` accepts
  `show_progress=False` and returns the same samples (mock the HTTP layer
  as the existing tests do).
- New orchestrator test: when the Popen wait raises KeyboardInterrupt,
  `main` calls `terminate()` on every live child, does not aggregate, and
  returns nonzero (results.csv untouched).
- No new test for tqdm itself (third-party, headless-safe); the worker and
  orchestrator tests exercise the bar code paths.

### Docs

- README: the run section gains a short paragraph: API families run in
  parallel (family processes plus a pool of 4 per family), local families run
  one at a time, each worker writes its own `results/pending/<family>.csv`
  (gitignored), the orchestrator aggregates them into `results/results.csv`
  after all workers finish, and tqdm shows corpus-fetch and per-family
  progress bars.
- `.gitignore`: add `results/pending/`.

### Hidden state machines and stuck states (validated 2026-11-24)

- CSV write-path state machine: workers append only to their own
  `results/pending/<family>.csv` (one process and one thread per file, so
  `append_row` stays lock-free); the orchestrator is the only writer of
  `results/results.csv`, via `aggregate_results` after all workers finish.
  Readers still drop a torn trailing line. A run interrupted before
  aggregation leaves results.csv untouched; the pending dir is wiped at the
  start of the next run.
- Dedup state machine: a (model, strategy, file, sha256) pair is "done" when
  its row is numeric, `n/a`, or `missing key ...`; `error:` rows are
  deliberately not done and rerun on the next run. Each family has exactly
  one worker per orchestrator run and reads the dedup set once at start, so
  there is no intra-run duplicate work.
- Two orchestrator runs at the same time share `PENDING_DIR` and are not
  supported; the invariant that keeps the table correct anyway:
  `table._latest_rows` keeps only the newest row per (model, strategy,
  file). Pinned here, no code change.
- Bounded runtime: no unbounded wait anywhere. Corpus fetch uses
  `httpx.Client(timeout=30.0)`; API counts use httpx's 5 s default timeout
  plus bounded 429 retries; the orchestrator's Popen wait is bounded by
  worker runtime and gets the terminate-on-interrupt wrap above. tqdm bars
  are passive output and cannot hang the run.

## What is left to the builder

- Exact placement of `API_CONCURRENCY` / `RETRY_ATTEMPTS` constants and
  whether `_count_one` is a module function or a closure (pick the one the
  existing tests mock most easily; tests patch
  `tokencount.counters.count_tokens`, so `_count_one` must call it through
  the module, not capture it).
- Whether `--bar-position` is a CLI flag or an env var (flag is more
  explicit; env var keeps the existing cmd shape in tests stable — decide
  when updating `TestOrchestrator`).
- tqdm bar wording (`desc=family` vs `desc=f"count {family}"`).

## Verification

- `uv lock --check` passes; `uv sync` installs tqdm.
- `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests` passes.
- Offline end-to-end, from the repo root with no API keys and warm
  `samples/`:
  `env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY -u GOOGLE_API_KEY -u Z_AI_API_KEY -u MOONSHOT_API_KEY PYTHONPATH=src .venv/bin/python -m tokencount`
  exits 0, prints tqdm bars on stderr (corpus + per-family), API rows land
  as `missing key <ENV>`, deepseek/mistral rows are numeric, and
  `results/table.md` is regenerated with 23 rows.
- Rerun without `--fresh` adds zero new deduped rows.
- Eyeball the bar layout once with keys absent (5 API bars at distinct
  positions, then 2 local bars) to confirm no garbled output.
- Fresh-CSV parallel start: delete `results/results.csv`, run offline, and
  assert the final CSV has exactly one header line, no mid-file header rows,
  row count = sum of all family pending rows, and `results/pending/` is gone.
- Interrupted run: start a run, kill the orchestrator mid-flight, assert
  `results/results.csv` is byte-identical to before and a rerun recounts
  cleanly with zero duplicate dedup keys.
