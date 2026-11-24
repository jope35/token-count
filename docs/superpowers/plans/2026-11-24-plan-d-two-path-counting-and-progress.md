# Plan D: two-path counting with tqdm and pending-CSV aggregation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make one run use two paths — the five API families (openai, anthropic, google, glm, kimi) run as concurrent `subprocess.Popen` workers, each counting its (model, file) pairs through an inner `ThreadPoolExecutor` of 4, while the local families (deepseek, mistral, `hf_local`) run sequentially afterwards via `subprocess.run` — with tqdm progress bars on the corpus fetch and on every worker, and a race-free write path where each worker appends only to its own `results/pending/<family>.csv` and the orchestrator aggregates them into `results/results.csv` once all workers finish.

**Architecture:** `run.main()` splits the sorted family list with `split_families()` into API vs local (a family is local when its first model's strategy is `hf_local`), wipes `results/pending/`, fetches the corpus once with a tqdm bar, launches every API family with `Popen` (distinct `--bar-position` 0..4, `--results-csv results/pending/<family>.csv`, wrapped in try/except KeyboardInterrupt that terminates live children and returns nonzero without aggregating), runs local families sequentially with `subprocess.run` (`--bar-position 0`, same pending path), then calls `aggregate_results()` (single writer, sorted family order, torn lines dropped like `read_dedup_keys`, pending dir removed) before `render_results()`. Workers build their item list once, then either loop sequentially (local) or `executor.map` over a pool of `API_CONCURRENCY = 4` (API) with the main thread appending rows as results yield, so `append_row` stays lock-free. `--family <name>` still runs one worker in-process writing straight to `results/results.csv`.

**Tech Stack:** Python 3.14, stdlib `unittest` in `tests/`, `tqdm` added via `pyproject.toml` + `uv lock` + committed `uv.lock` + `uv sync` (never `uv pip install`), existing `httpx`/`tenacity`/`tokenizers`. Run from the repo root: `PYTHONPATH=src .venv/bin/python -m tokencount`.

**Spec:** docs/superpowers/specs/2026-11-24-two-path-counting-design.md

## Global Constraints

- Single `.venv`; dependencies only via `pyproject.toml` + `uv lock` + committed `uv.lock` + `uv sync`. Never `uv pip install`. Adding tqdm means exactly that path.
- Tests: stdlib `unittest` in `tests/`, run from the repo root with `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests` (`uv sync` first if `.venv` is missing).
- Run command unchanged: `PYTHONPATH=src .venv/bin/python -m tokencount` (optionally `--fresh`, `--family <name>`).
- CSV contract unchanged: columns `timestamp,provider,model,strategy,file,file_type,sha256,chars,tokens,note`; notes `error: <msg>`, `n/a`, `missing key <ENV>`; `error:` rows are not deduped; torn trailing lines are ignored by readers. Dedup key `(model, strategy, file, sha256)`.
- Exit-code contract unchanged: 0 only when every worker succeeded; the table is rendered regardless of worker failure.
- Offline behavior preserved: local families need no key and no network beyond cached `samples/`; a run without API keys still exits 0 with `missing key <ENV>` rows.
- `counters.count_tokens(strategy, model_id, text, key=None, tokenizer_file=None) -> int` signature unchanged.
- Pinned constants: `API_CONCURRENCY = 4` in `run.py`; `RETRY_ATTEMPTS = 5` in `counters.py` with `wait_fixed(RETRY_WAIT_SECONDS)` (1) unchanged; `PENDING_DIR = "results/pending/"`; `RESULTS_CSV = "results/results.csv"` (existing).
- Pinned worker/CLI shapes: `run_worker(family, fresh=False, results_csv=None, bar_position=0) -> int`; new CLI flags `--results-csv` (default None) and `--bar-position` (int, default 0); orchestrator passes `--results-csv results/pending/<family>.csv` and `--bar-position <i>` (i = 0..4 for API families, `0` for local); worker bar is exactly `tqdm(items, desc=family, unit="pair", position=bar_position, leave=True, disable=None)`; corpus bar is `tqdm(entries, desc="corpus", unit="file")` when `show_progress`; `fetch_corpus(entries, dest_dir="samples", fresh=False, show_progress=True)` and workers call it with `show_progress=False`.
- Write path: every worker writes only its own pending CSV; `aggregate_results(pending_dir=PENDING_DIR, csv_path=RESULTS_CSV) -> int` is the single writer of `results/results.csv`, runs after all workers finish (even when some failed) and before `render_results()`; `--family` direct runs write `results/results.csv` directly with no aggregation.

## Review Focus

1. **Pool path bypasses the counters-module patch.** If `_count_one` captures `count_tokens` instead of calling `counters.count_tokens` through the module, tests that patch `tokencount.counters.count_tokens` silently stop mocking and hit the network. Pinned by the existing `TestWorker` `ct.call_count` assertions (Task 4), which must hold on both the pool and the sequential path.
2. **Two workers sharing one CSV** (header race, interleaved rows). Pinned by the Task 6 `TestOrchestrator` assertions that each of the 7 children gets its own `--results-csv results/pending/<family>.csv`, plus the single-header assertion in Task 5's `test_aggregate_results`.
3. **Stale pending rows leaking into a new run, or an interrupt touching `results.csv`.** Pinned by Task 6's `test_main_clears_pending_dir_at_start` and the KeyboardInterrupt test (terminate every live child, no aggregation, nonzero rc, `results.csv` byte-identical).
4. **A torn trailing line in a pending CSV aggregated into `results.csv`.** Pinned by Task 5's `test_aggregate_results`, which seeds a pending CSV with a torn trailing line and asserts its data never reaches the main CSV.
5. **429 retry too brittle under up to 20 concurrent requests**, turning calls into `error:` rows (not deduped, so they rerun). Pinned by Task 3's tests asserting exactly `RETRY_ATTEMPTS = 5` attempts before giving up and success on the 5th. Related cosmetic risk — parallel bars garbling on a TTY — is pinned by Task 6's assertion that the 5 Popen commands carry distinct `--bar-position` values 0..4.

## Task 1: Add tqdm via pyproject + uv lock

**Files:**
- Modify: `pyproject.toml` (the `dependencies` list, lines 6-11)
- Create: `uv.lock` (generated by `uv lock`)

**Interfaces:**
- Consumes: nothing new.
- Produces: `tqdm` importable inside `.venv`; `pyproject.toml` `dependencies` gains `"tqdm"`.

- [ ] **Step 1:** Add `"tqdm"` to `dependencies` in `pyproject.toml` (after `"tokenizers"`).
- [ ] **Step 2:** From the repo root run `uv lock`. Expected: `uv.lock` is created/updated and includes a `tqdm` entry. Verify with `uv lock --check` (expected: exit 0, "lockfile is up to date").
- [ ] **Step 3:** Run `uv sync` (expected: `.venv` installs tqdm) and verify: `.venv/bin/python -c "import tqdm; print(tqdm.__version__)"` prints a version string.
- [ ] **Step 4:** Run the full suite to confirm nothing broke: `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests`. Expected: PASS (ok, skips allowed for live-key tests).
- [ ] **Step 5:** Commit: `git add pyproject.toml uv.lock && git commit -m "deps: add tqdm via pyproject and uv lock"`

## Task 2: `fetch_corpus` gains `show_progress`

**Files:**
- Modify: `src/tokencount/corpus.py:74-102` (`fetch_corpus`)
- Test: `tests/test_corpus.py` (add to `TestFetchCorpus`)

**Interfaces:**
- Consumes: `tqdm` from Task 1.
- Produces: `fetch_corpus(entries: list[CorpusEntry], dest_dir="samples", fresh=False, show_progress=True) -> list[Sample]`. Default `True` keeps the orchestrator call and plan A behavior unchanged; workers pass `False` (Task 4).

- [ ] **Step 1:** Write the failing test in `tests/test_corpus.py`, inside `TestFetchCorpus`:

```python
def test_show_progress_false_returns_same_samples(self):
    def handler(request):
        return httpx.Response(200, content=b"progress body")

    with tempfile.TemporaryDirectory() as td, _patch_client(handler):
        s = fetch_corpus([ENTRY], dest_dir=td, show_progress=False)[0]
    self.assertEqual(s.text, "progress body")
    self.assertEqual(s.sha256, hashlib.sha256(b"progress body").hexdigest())
    self.assertEqual(str(Path(td) / "text" / "Austria"), s.path)
```

- [ ] **Step 2:** Run `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests` (or `... -m unittest tests.test_corpus.TestFetchCorpus.test_show_progress_false_returns_same_samples`). Expected: FAIL with `TypeError: fetch_corpus() got an unexpected keyword argument 'show_progress'`.
- [ ] **Step 3:** Implement in `src/tokencount/corpus.py`: add `from tqdm import tqdm` at the top and change the signature to `def fetch_corpus(entries, dest_dir="samples", fresh=False, show_progress=True) -> list[Sample]:`, wrapping the loop as `for entry in (tqdm(entries, desc="corpus", unit="file") if show_progress else entries):`. Body otherwise unchanged.
- [ ] **Step 4:** Run the same test. Expected: PASS. Then run the full suite `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests`. Expected: PASS.
- [ ] **Step 5:** Commit: `git add src/tokencount/corpus.py tests/test_corpus.py && git commit -m "feat: fetch_corpus show_progress parameter with tqdm bar"`

## Task 3: 429 retry bump to `RETRY_ATTEMPTS = 5`

**Files:**
- Modify: `src/tokencount/counters.py:14-38` (constants + `_post_json` retrying)
- Test: `tests/test_counters.py` (add to `TestApiStrategies`, which sets `RETRY_WAIT_SECONDS = 0` in `setUp`)

**Interfaces:**
- Consumes: nothing new.
- Produces: `counters.RETRY_ATTEMPTS = 5`; `_post_json` uses `stop_after_attempt(RETRY_ATTEMPTS)` with `wait_fixed(RETRY_WAIT_SECONDS)` (1) unchanged. No other change: `_BASELINE_CACHE` stays lock-free (GIL-atomic dict ops), each `_post_json` builds its own `httpx.Client`.

- [ ] **Step 1:** Write the failing tests in `tests/test_counters.py`:

```python
def test_429_succeeds_on_fifth_attempt(self):
    self.assertEqual(counters.RETRY_ATTEMPTS, 5)
    state = {"n": 0}

    def handler(request):
        state["n"] += 1
        if state["n"] < 5:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(200, json={"input_tokens": 5})

    use_mock(handler)
    self.assertEqual(counters.count_tokens("openai_api", "m", "x", key="k"), 5)
    self.assertEqual(state["n"], 5)

def test_429_gives_up_after_retry_attempts(self):
    state = {"n": 0}

    def handler(request):
        state["n"] += 1
        return httpx.Response(429, json={"error": "rate limited"})

    use_mock(handler)
    with self.assertRaises(httpx.HTTPStatusError):
        counters.count_tokens("openai_api", "m", "x", key="k")
    self.assertEqual(state["n"], counters.RETRY_ATTEMPTS)
```

- [ ] **Step 2:** Run `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -k test_429` (or the full discover). Expected: `test_429_succeeds_on_fifth_attempt` FAILs (only 3 attempts, so `state["n"] == 3` and `HTTPStatusError` is raised); the give-up test FAILs on `self.assertEqual(counters.RETRY_ATTEMPTS, 5)` (`AttributeError`).
- [ ] **Step 3:** Implement in `src/tokencount/counters.py`: add `RETRY_ATTEMPTS = 5` next to `RETRY_WAIT_SECONDS = 1` and change `stop=stop_after_attempt(3)` to `stop=stop_after_attempt(RETRY_ATTEMPTS)`.
- [ ] **Step 4:** Run both tests. Expected: PASS (note: the existing `test_429_retried_then_succeeds` with 2×429 then 200 still passes under 5 attempts). Run the full suite. Expected: PASS.
- [ ] **Step 5:** Commit: `git add src/tokencount/counters.py tests/test_counters.py && git commit -m "feat: retry 429 up to RETRY_ATTEMPTS=5 times"`

## Task 4: Worker — pool vs sequential, pending CSV path, tqdm bar

**Files:**
- Modify: `src/tokencount/run.py` (`run_worker`, new `_count_one`, new constants, new CLI args in `main` — the `main` orchestrator body itself is Task 5)
- Test: `tests/test_run.py` (`TestWorker`)

**Interfaces:**
- Consumes: `fetch_corpus(..., show_progress=...)` from Task 2; `models_for_family`, `REGISTRY`; `count_sample` (unchanged, calls `counters.count_tokens` through the module); `append_row` (unchanged, lock-free); `read_dedup_keys`; `tqdm` from Task 1.
- Produces:
  - `API_CONCURRENCY = 4` and `PENDING_DIR = "results/pending/"` module constants in `run.py`.
  - `_count_one(item, key) -> dict` — module-level; `item` is a `(model, sample)` tuple; it only computes the row: unpacks the pair, calls `count_sample(model, sample, key)` (which calls `counters.count_tokens` through the module, so the test patch applies), and returns the full row dict with `timestamp` from `datetime.now(timezone.utc).isoformat()`, `provider/model/strategy` from the model, `file/file_type/sha256/chars` from the sample, `tokens/note` from `count_sample`.
  - `run_worker(family: str, fresh: bool = False, results_csv: str = None, bar_position: int = 0) -> int`:
    - `csv_path = results_csv or RESULTS_CSV` (write target only).
    - `samples = fetch_corpus(load_entries(), fresh=fresh, show_progress=False)`.
    - `deduped = set() if fresh else read_dedup_keys(RESULTS_CSV)` — dedup is read from the main `results/results.csv`, not from the pending write target (spec §Aggregation: a worker's pending file starts empty, so reading it would recount everything; the rerun-adds-zero-rows check in Task 8 pins this).
    - `items = [(model, sample) for model in models for sample in samples if (model.model, model.strategy, sample.path, sample.sha256) not in deduped]`.
    - Bar kwargs exactly: `dict(desc=family, unit="pair", position=bar_position, leave=True, disable=None)`.
    - Local family (`models[0].strategy == "hf_local"`): sequential `for item in tqdm(items, **bar): append_row(csv_path, _count_one(item, key))`.
    - API family: `with ThreadPoolExecutor(max_workers=API_CONCURRENCY) as pool: for row in tqdm(pool.map(partial(_count_one, key=key), items), **bar): append_row(csv_path, row)` — only the main thread appends, so `append_row` needs no lock.
    - Returns 0.

- [ ] **Step 1:** Update the `TestWorker.run_worker` helper in `tests/test_run.py` to also patch the dedup source: add `mock.patch.object(run, "RESULTS_CSV", csv_path)` to the `with` block (dedup now reads `RESULTS_CSV`; all existing helper tests keep their meaning).
- [ ] **Step 2:** Write the failing tests in `tests/test_run.py`:

```python
def test_local_family_worker_runs_sequentially(self):
    with tempfile.TemporaryDirectory() as d:
        csv_path = os.path.join(d, "pending", "deepseek.csv")
        rc, ct = self.run_worker("deepseek", csv_path, env={})
        self.assertEqual(rc, 0)
        self.assertEqual(ct.call_count, 2)  # 2 deepseek models x 1 sample
        rows = self.read_rows(csv_path)
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["model"] for r in rows}, {"deepseek-flash", "deepseek-v4-pro"})
        self.assertTrue(all(r["tokens"] == "7" and r["note"] == "" for r in rows))

def test_worker_fetches_corpus_with_show_progress_false(self):
    with tempfile.TemporaryDirectory() as d:
        csv_path = os.path.join(d, "results.csv")
        with (
            mock.patch.object(run, "RESULTS_CSV", csv_path),
            mock.patch.object(run, "load_entries", return_value=[]),
            mock.patch.object(run, "fetch_corpus", return_value=[SAMPLE]) as fc,
            mock.patch.dict(os.environ, {"OPENAI_API_KEY": "k"}, clear=True),
            mock.patch("tokencount.counters.count_tokens", return_value=7),
        ):
            run.run_worker("openai", results_csv=csv_path)
        self.assertEqual(fc.call_args.kwargs.get("show_progress"), False)

def test_worker_bar_kwargs(self):
    with tempfile.TemporaryDirectory() as d:
        csv_path = os.path.join(d, "results.csv")
        with (
            mock.patch.object(run, "RESULTS_CSV", csv_path),
            mock.patch.object(run, "load_entries", return_value=[]),
            mock.patch.object(run, "fetch_corpus", fake_corpus),
            mock.patch.dict(os.environ, {"OPENAI_API_KEY": "k"}, clear=True),
            mock.patch("tokencount.counters.count_tokens", return_value=7),
            mock.patch.object(run, "tqdm", side_effect=lambda it, **kw: it) as tq,
        ):
            run.run_worker("openai", results_csv=csv_path, bar_position=3)
        tq.assert_called_once()
        kw = tq.call_args.kwargs
        self.assertEqual(
            (kw["desc"], kw["unit"], kw["position"], kw["leave"], kw["disable"]),
            ("openai", "pair", 3, True, None),
        )
```

- [ ] **Step 3:** Run `PYTHONPATH=src .venv/bin/python -m unittest tests.test_run -v`. Expected: the new tests FAIL (`run_worker() got an unexpected keyword argument 'bar_position'`, `tqdm` not patched / `API_CONCURRENCY` missing), and `test_local_family_worker_runs_sequentially` shows the current sequential loop still passes shape-wise but the helper change is needed.
- [ ] **Step 4:** Implement in `src/tokencount/run.py` exactly per the Interfaces block above: imports `from concurrent.futures import ThreadPoolExecutor`, `from functools import partial`, `from tqdm import tqdm`; constants `API_CONCURRENCY = 4`, `PENDING_DIR = "results/pending/"`; `_count_one`; rewritten `run_worker`. Leave `main()` for Task 5 except adding the two CLI args (`--results-csv` default None, `--bar-position` type=int default 0) and routing them into the `--family` branch: `return run_worker(args.family, fresh=args.fresh, results_csv=args.results_csv, bar_position=args.bar_position)`.
- [ ] **Step 5:** Run `PYTHONPATH=src .venv/bin/python -m unittest tests.test_run -v`. Expected: PASS, including all pre-existing `TestWorker` tests unchanged in behavior (pool path produces identical rows: `test_appends_rows_with_exact_columns`, `test_dedup_skips_existing_pair`, `test_fresh_recounts_everything`, `test_error_note_row`, `test_error_rows_are_recounted_on_rerun`, `test_torn_trailing_row_is_not_a_dedup_key`, `TestOfflinePartialRun`). Then full suite. Expected: PASS.
- [ ] **Step 6:** Commit: `git add src/tokencount/run.py tests/test_run.py && git commit -m "feat: worker thread pool for API families, pending results csv, tqdm bar"`

## Task 5: Orchestrator — split, Popen phase, aggregation, interrupt

**Files:**
- Modify: `src/tokencount/run.py` (`main`, new `split_families`, new `aggregate_results`)
- Test: `tests/test_run.py` (new `test_split_families`, new `TestAggregateResults`)

**Interfaces:**
- Consumes: `run_worker`/CLI args from Task 4; `route_env`, `family_env`, `resolve_secrets`, `read_dedup_keys`, `append_row`, `render_results` (all unchanged); `REGISTRY`, `models_for_family`.
- Produces:
  - `split_families(families) -> tuple[list, list]` returning `(api_families, local_families)`; a family is local when `models_for_family(family)[0].strategy == "hf_local"` (all models of a family share a strategy).
  - `aggregate_results(pending_dir=PENDING_DIR, csv_path=RESULTS_CSV) -> int`: for each `*.csv` in `pending_dir` in sorted order, read with `csv.DictReader`, skip rows where `any(row.get(col) is None for col in CSV_COLUMNS)` (the torn-line rule, same as `read_dedup_keys`), `append_row(csv_path, row)` each surviving row, count them; then `shutil.rmtree(pending_dir)` if it exists; return the appended count. Header is written once by `append_row` on first append.
  - Rewritten `main(argv=None) -> int` orchestrator branch (after the `--family` early return):
    1. `secrets = resolve_secrets()`
    2. `shutil.rmtree(PENDING_DIR, ignore_errors=True)` — wipe stale pending rows at start
    3. `fetch_corpus(load_entries(), fresh=args.fresh)` — default `show_progress=True` gives the one real corpus bar
    4. `families = sorted({m.family for m in REGISTRY})`; `api_families, local_families = split_families(families)`
    5. Popen phase: for `i, family in enumerate(api_families)`, `cmd = [f"{route_env(family)}/bin/python", "-m", "tokencount", "--family", family, "--bar-position", str(i), "--results-csv", os.path.join(PENDING_DIR, f"{family}.csv")]` plus `--fresh` if set; `proc = subprocess.Popen(cmd, env=family_env(family, secrets))`; collect procs. Wrap the waits in try/except KeyboardInterrupt: `try: for proc in procs: returncodes.append(proc.wait())` / `except KeyboardInterrupt:` terminate every child with `proc.poll() is None`, then `proc.wait(timeout=5)` each (on `subprocess.TimeoutExpired`: `proc.kill()` then `proc.wait()`), and `return 1` — no aggregation, no render, `results/results.csv` untouched.
    6. Local phase: for each `family in local_families`, same cmd shape with `"--bar-position", "0"` and the pending path, run via `subprocess.run(cmd, env=family_env(family, secrets), check=False)`; append `proc.returncode`.
    7. `aggregate_results(PENDING_DIR, RESULTS_CSV)` — explicit args so the module globals are read at call time (patchable in tests); called exactly once, after all workers, even when some returncode is nonzero.
    8. `render_results()`; `return 0 if all(rc == 0 for rc in returncodes) else 1`.

- [ ] **Step 1:** Write the failing tests in `tests/test_run.py`:

```python
class TestSplitFamilies(unittest.TestCase):
    def test_split_families_from_registry(self):
        families = sorted({m.family for m in run.REGISTRY})
        api, local = run.split_families(families)
        self.assertEqual(set(api), {"openai", "anthropic", "google", "glm", "kimi"})
        self.assertEqual(set(local), {"deepseek", "mistral"})


class TestAggregateResults(unittest.TestCase):
    def _write_pending(self, d, name, rows, torn=None):
        os.makedirs(os.path.join(d, "results", "pending"), exist_ok=True)
        p = os.path.join(d, "results", "pending", name)
        with open(p, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(run.CSV_COLUMNS)
            for r in rows:
                w.writerow(r)
            if torn:
                f.write(torn)  # no newline: torn trailing line

    def test_aggregates_sorted_drops_torn_removes_dir(self):
        with tempfile.TemporaryDirectory() as d:
            cwd = os.getcwd()
            os.chdir(d)
            try:
                self._write_pending(d, "beta.csv", [[
                    "2026-11-24T00:00:00+00:00", "kimi", "kimi-k3", "kimi_api",
                    "samples/text/France", "text", "sha-b", "5", "7", "",
                ]])
                self._write_pending(d, "alpha.csv", [[
                    "2026-11-24T00:00:00+00:00", "openai", "gpt-6.2-astra", "openai_api",
                    "samples/text/France", "text", "sha-a", "5", "7", "",
                ], [
                    "2026-11-24T00:00:01+00:00", "openai", "gpt-6.2-sol", "openai_api",
                    "samples/text/France", "text", "sha-a", "5", "8", "",
                ]], torn="2026-11-24T00:00:02+00:00,openai,gpt-6.1-terra")
                # main CSV already has its header
                os.makedirs(os.path.join(d, "results"), exist_ok=True)
                with open("results/results.csv", "w", newline="") as f:
                    csv.writer(f).writerow(run.CSV_COLUMNS)
                n = run.aggregate_results()
                self.assertEqual(n, 3)
                with open("results/results.csv", newline="") as f:
                    lines = f.read().splitlines()
                self.assertEqual(len(lines), 4)  # exactly one header + 3 rows
                self.assertEqual(lines[0], ",".join(run.CSV_COLUMNS))
                with open("results/results.csv", newline="") as f:
                    rows = list(csv.DictReader(f))
                self.assertEqual([r["model"] for r in rows],
                                 ["gpt-6.2-astra", "gpt-6.2-sol", "kimi-k3"])  # sorted family order
                self.assertNotIn("gpt-6.1-terra", [r["model"] for r in rows])  # torn dropped
                self.assertFalse(os.path.exists("results/pending"))
            finally:
                os.chdir(cwd)

    def test_empty_pending_dir_is_a_noop(self):
        with tempfile.TemporaryDirectory() as d:
            cwd = os.getcwd()
            os.chdir(d)
            try:
                self.assertEqual(run.aggregate_results(), 0)
                self.assertFalse(os.path.exists("results/results.csv"))
            finally:
                os.chdir(cwd)
```

- [ ] **Step 2:** Run `PYTHONPATH=src .venv/bin/python -m unittest tests.test_run -v`. Expected: FAIL — `run.split_families` / `run.aggregate_results` do not exist (`AttributeError`).
- [ ] **Step 3:** Implement `split_families`, `aggregate_results`, and the new `main` orchestrator branch in `src/tokencount/run.py` exactly per the Interfaces block (add `import shutil`).
- [ ] **Step 4:** Run `PYTHONPATH=src .venv/bin/python -m unittest tests.test_run -v`. Expected: the new tests PASS; the old `TestOrchestrator` tests now FAIL (they still expect `sp.run.call_count == 7` and no aggregation) — that rewrite is Task 6, so run only the new classes here: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_run.TestSplitFamilies tests.test_run.TestAggregateResults -v`. Expected: PASS.
- [ ] **Step 5:** Commit: `git add src/tokencount/run.py tests/test_run.py && git commit -m "feat: orchestrator splits API/local, Popen phase, pending-csv aggregation, interrupt handling"`

## Task 6: Orchestrator test suite — Popen x5 / run x2, clear-pending, interrupt

**Files:**
- Test: `tests/test_run.py` (rewrite `TestOrchestrator`, add `test_main_clears_pending_dir_at_start`, KeyboardInterrupt test)

**Interfaces:**
- Consumes: `run.main`, `run.split_families`, `run.aggregate_results`, `run.PENDING_DIR`, `run.RESULTS_CSV`, `run.family_env` from Task 5; the `SAMPLE`/`fake_corpus`/`FAMILY_KEY`/`LOCAL_FAMILIES`/`ALL_SECRETS` fixtures already at the top of `tests/test_run.py`.
- Produces: the pinned orchestrator contract — 5 `Popen` calls (API families, distinct `--bar-position` 0..4, `--results-csv results/pending/<family>.csv`), 2 `subprocess.run` calls (local families, `--bar-position 0`, same pending path), `aggregate_results` called once before `render_results`, render once, exit 0 iff all return codes are 0, least-privilege env per family, `--fresh` propagated to every child cmd and the fetch.

- [ ] **Step 1:** Rewrite `TestOrchestrator` in `tests/test_run.py`. The mock harness: patch `run.resolve_secrets` (return `ALL_SECRETS`), `run.load_entries` (return `[]`), `run.fetch_corpus` (`fake_corpus`), `run.subprocess` as `sp`, `run.aggregate_results` and `run.render_results` with side effects appending to a `calls` list so order is assertable. `sp.Popen.side_effect` builds a `mock.Mock()` per call with `wait.return_value` set from a configurable list and `poll.return_value = 0`, recording `(cmd, env)`. `sp.run.side_effect` returns `subprocess.CompletedProcess(args=cmd, returncode=rc)` from a configurable list. All tests `os.chdir` into a `tempfile.TemporaryDirectory()` (restore in `finally`) because `main` touches the relative `results/pending/`.

```python
class TestOrchestrator(unittest.TestCase):
    def _run_main(self, argv=None, popen_rcs=(0,) * 5, run_rcs=(0,) * 2):
        calls = []
        popens = []
        runs = []

        def fake_popen(cmd, env=None):
            p = mock.Mock()
            p.wait.return_value = popen_rcs[len(popens)]
            p.poll.return_value = 0
            popens.append((p, cmd, env))
            return p

        def fake_run(cmd, env=None, check=False):
            runs.append((cmd, env))
            return subprocess.CompletedProcess(args=cmd, returncode=run_rcs[len(runs) - 1])

        with tempfile.TemporaryDirectory() as d:
            cwd = os.getcwd()
            os.chdir(d)
            try:
                with (
                    mock.patch.object(run, "resolve_secrets", return_value=ALL_SECRETS),
                    mock.patch.object(run, "load_entries", return_value=[]),
                    mock.patch.object(run, "fetch_corpus", fake_corpus),
                    mock.patch.object(run, "subprocess") as sp,
                    mock.patch.object(run, "aggregate_results",
                                      side_effect=lambda *a, **k: calls.append("aggregate")) as agg,
                    mock.patch.object(run, "render_results",
                                      side_effect=lambda: calls.append("render")) as rr,
                ):
                    sp.Popen.side_effect = fake_popen
                    sp.run.side_effect = fake_run
                    rc = run.main(argv or [])
            finally:
                os.chdir(cwd)
        return rc, popens, runs, calls, agg, rr

    def test_popen_five_api_and_run_two_local(self):
        rc, popens, runs, calls, agg, rr = self._run_main()
        self.assertEqual(rc, 0)
        self.assertEqual(len(popens), 5)
        self.assertEqual(len(runs), 2)
        api_families, positions, pending = set(), set(), []
        for p, cmd, env in popens:
            self.assertEqual(cmd[:3], [".venv/bin/python", "-m", "tokencount"])
            family = cmd[cmd.index("--family") + 1]
            api_families.add(family)
            positions.add(cmd[cmd.index("--bar-position") + 1])
            self.assertEqual(cmd[cmd.index("--results-csv") + 1],
                             f"results/pending/{family}.csv")
            pending.append(f"results/pending/{family}.csv")
            expected = {"PYTHONPATH", FAMILY_KEY[family]}
            self.assertEqual(set(env), expected)
        self.assertEqual(api_families, set(FAMILY_KEY))
        self.assertEqual(positions, {"0", "1", "2", "3", "4"})  # distinct bar positions
        local_families = set()
        for cmd, env in runs:
            family = cmd[cmd.index("--family") + 1]
            local_families.add(family)
            self.assertEqual(cmd[cmd.index("--bar-position") + 1], "0")
            self.assertEqual(cmd[cmd.index("--results-csv") + 1],
                             f"results/pending/{family}.csv")
            self.assertEqual(set(env), {"PYTHONPATH"})  # local: no key
        self.assertEqual(local_families, LOCAL_FAMILIES)
        self.assertEqual(len(set(pending)), 7)  # every worker its own file
        self.assertEqual(calls, ["aggregate", "render"])  # aggregate once, before render
        agg.assert_called_once()
        rr.assert_called_once_with()

    def test_failed_worker_makes_main_nonzero_but_still_aggregates_and_renders(self):
        rcs = [0, 1, 0, 0, 0]
        rc, popens, runs, calls, agg, rr = self._run_main(popen_rcs=tuple(rcs))
        self.assertEqual(rc, 1)
        self.assertEqual(calls, ["aggregate", "render"])

    def test_fresh_flag_propagates_to_all_workers_and_fetch(self):
        with (
            mock.patch.object(run, "resolve_secrets", return_value={}),
            mock.patch.object(run, "load_entries", return_value=[]),
            mock.patch.object(run, "fetch_corpus", return_value=[SAMPLE]) as fc,
            mock.patch.object(run, "subprocess") as sp,
            mock.patch.object(run, "aggregate_results"),
            mock.patch.object(run, "render_results"),
        ):
            sp.Popen.return_value = mock.Mock(wait=mock.Mock(return_value=0), poll=mock.Mock(return_value=0))
            sp.run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
            with tempfile.TemporaryDirectory() as d:
                cwd = os.getcwd()
                os.chdir(d)
                try:
                    run.main(["--fresh"])
                finally:
                    os.chdir(cwd)
        for call in sp.Popen.call_args_list + sp.run.call_args_list:
            self.assertIn("--fresh", call.args[0])
        self.assertEqual(fc.call_args.kwargs.get("fresh"), True)

    def test_main_clears_pending_dir_at_start(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "results", "pending"))
            stale = os.path.join(d, "results", "pending", "stale.csv")
            with open(stale, "w") as f:
                f.write("stale\n")
            cwd = os.getcwd()
            os.chdir(d)
            try:
                with (
                    mock.patch.object(run, "resolve_secrets", return_value={}),
                    mock.patch.object(run, "load_entries", return_value=[]),
                    mock.patch.object(run, "fetch_corpus", fake_corpus),
                    mock.patch.object(run, "subprocess") as sp,
                    mock.patch.object(run, "aggregate_results") as agg,  # only the start-wipe may remove it
                    mock.patch.object(run, "render_results"),
                ):
                    sp.Popen.return_value = mock.Mock(wait=mock.Mock(return_value=0), poll=mock.Mock(return_value=0))
                    sp.run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
                    rc = run.main([])
            finally:
                os.chdir(cwd)
        self.assertEqual(rc, 0)
        self.assertFalse(os.path.exists(stale))

    def test_keyboard_interrupt_terminates_children_and_touches_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "results"))
            csv_path = os.path.join(d, "results", "results.csv")
            with open(csv_path, "w") as f:
                f.write("original\n")
            before = open(csv_path, "rb").read()
            procs = []

            def fake_popen(cmd, env=None):
                p = mock.Mock()
                p.poll.return_value = None  # still running
                p.wait.side_effect = KeyboardInterrupt
                procs.append(p)
                return p

            cwd = os.getcwd()
            os.chdir(d)
            try:
                with (
                    mock.patch.object(run, "resolve_secrets", return_value={}),
                    mock.patch.object(run, "load_entries", return_value=[]),
                    mock.patch.object(run, "fetch_corpus", fake_corpus),
                    mock.patch.object(run, "subprocess") as sp,
                    mock.patch.object(run, "aggregate_results") as agg,
                    mock.patch.object(run, "render_results") as rr,
                ):
                    sp.Popen.side_effect = fake_popen
                    rc = run.main([])
            finally:
                os.chdir(cwd)
        self.assertEqual(len(procs), 5)
        for p in procs:
            p.terminate.assert_called_once_with()
        agg.assert_not_called()
        rr.assert_not_called()
        self.assertNotEqual(rc, 0)
        self.assertEqual(open(csv_path, "rb").read(), before)  # results.csv untouched
```

- [ ] **Step 2:** Run `PYTHONPATH=src .venv/bin/python -m unittest tests.test_run.TestOrchestrator -v`. Expected: FAIL (old expectations vs new behavior, or assertion mismatches against the Task 5 implementation — fix the test to match the pinned contract above, not the other way around).
- [ ] **Step 3:** If any failure reveals a real deviation from the pinned contract in Task 5 (e.g. aggregate not before render, missing `--results-csv`), fix `src/tokencount/run.py` accordingly; do not weaken the assertions.
- [ ] **Step 4:** Run the full suite: `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests`. Expected: PASS (all modules, skips allowed only for live-key tests).
- [ ] **Step 5:** Commit: `git add tests/test_run.py src/tokencount/run.py && git commit -m "test: orchestrator Popen/run split, pending wipe, aggregation order, interrupt contract"`

## Task 7: README run section + `.gitignore`

**Files:**
- Modify: `README.md` (the run paragraph after the Quickstart command, around line 15)
- Modify: `.gitignore`

**Interfaces:**
- Consumes: the behavior from Tasks 4-6.
- Produces: docs only.

- [ ] **Step 1:** Add `results/pending/` as a new line in `.gitignore`.
- [ ] **Step 2:** Extend the run paragraph in `README.md` (after line 15) with a short paragraph covering exactly these points: the 5 API families run in parallel as separate processes, each counting through a pool of 4 (`API_CONCURRENCY`); the local deepseek/mistral families run one at a time afterwards; each worker appends only to its own `results/pending/<family>.csv` (gitignored) and the orchestrator aggregates those into `results/results.csv` after all workers finish; tqdm shows a corpus-fetch bar and one bar per family; `--family <name>` still runs a single worker writing `results/results.csv` directly.
- [ ] **Step 3:** Verify: `grep -n "results/pending/" .gitignore` prints the new line; `grep -n "pending" README.md` shows the new paragraph; run the full test suite `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests`. Expected: PASS.
- [ ] **Step 4:** Commit: `git add README.md .gitignore && git commit -m "docs: two-path run, pending csv aggregation, tqdm bars; ignore results/pending/"`

## Task 8: End-to-end offline verification

**Files:**
- Test: none new — this task runs the spec's Verification section against the real CLI from the repo root.

**Interfaces:**
- Consumes: everything from Tasks 1-7.
- Produces: confidence evidence only.

- [ ] **Step 1:** `uv sync` (if `.venv` missing), then `uv lock --check` (expected exit 0) and `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests` (expected PASS).
- [ ] **Step 2:** Offline run with warm `samples/`, no API keys: `env -u OPENAI_API_KEY -u ANTHROPIC_API_KEY -u GOOGLE_API_KEY -u Z_AI_API_KEY -u MOONSHOT_API_KEY PYTHONPATH=src .venv/bin/python -m tokencount`. Expected: exit 0; tqdm bars on stderr (one corpus bar + per-family bars); API rows in `results/results.csv` carry `missing key <ENV>`; deepseek/mistral rows are numeric; `results/table.md` regenerated with 23 model rows.
- [ ] **Step 3:** Rerun the same command without `--fresh`. Expected: zero new deduped rows appended (row count unchanged).
- [ ] **Step 4:** Fresh-CSV parallel start: delete `results/results.csv`, rerun the Step 2 command. Expected: final CSV has exactly one header line, no mid-file header rows, row count = sum of all family pending rows, and `results/pending/` is gone afterwards.
- [ ] **Step 5:** Interrupted run: start a run, kill the orchestrator mid-flight; assert `results/results.csv` is byte-identical to before, then rerun and assert it recounts cleanly with zero duplicate dedup keys.
- [ ] **Step 6:** Eyeball the bar layout once with keys absent (5 API bars at distinct positions, then 2 local bars); on a non-TTY the bars must self-disable via `disable=None` (no update spam in the log).
- [ ] **Step 7:** Commit any corrections the verification surfaced: `git add -A && git commit -m "fix: <what verification found>"`; if nothing changed, `git commit --allow-empty -m "chore: verify plan D end-to-end offline"`.

---

## Self-review (run after writing, before committing)

1. **Spec coverage:** split/Popen/aggregate/interrupt → Tasks 5-6; worker pool + pending + bar → Task 4; `show_progress` → Task 2; `RETRY_ATTEMPTS=5` → Task 3; tqdm dep path → Task 1; README/`.gitignore` → Task 7; spec Verification section → Task 8. Builder-left-open decisions are pinned: `_count_one` is a module-level function calling `count_sample` (which calls `counters.count_tokens` through the module); `--bar-position` and `--results-csv` are CLI flags; bar `desc=family`. No spec requirement is left without a task.
2. **Step scan:** every step is one action with a checkable result (test code with exact assertions, exact run command with expected FAIL/PASS, exact commit command). No step transcribes a whole function body; the Interfaces blocks pin signatures and values only.
3. **Type consistency:** `run_worker(family, fresh=False, results_csv=None, bar_position=0) -> int`, `split_families(families) -> tuple[list, list]`, `aggregate_results(pending_dir=PENDING_DIR, csv_path=RESULTS_CSV) -> int`, `_count_one(item, key) -> dict`, `fetch_corpus(entries, dest_dir="samples", fresh=False, show_progress=True) -> list[Sample]`, `count_tokens(strategy, model_id, text, key=None, tokenizer_file=None) -> int` — used identically in every task.
4. **Review Focus:** all five lines map to concrete tests (Task 3 ×2, Task 4 `ct.call_count`, Task 5 `test_aggregate_results`, Task 6 orchestrator/interrupt/clear tests).
5. **Proportion:** the plan is longer than the spec only because it carries 8 tasks' worth of test assertions; no code bodies are transcribed beyond the pinned one-liners.
