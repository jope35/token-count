# Plan A: base environment and corpus — Implementation Plan

> **For the agent executing this plan:** read `docs/superpowers/specs/2026-11-23-token-count-table-design.md` first, then execute the tasks below in order. Each task is independently testable and committed. Do NOT create or modify `src/tokencount/models.py`, `src/tokencount/counters.py`, `src/tokencount/run.py`, or `src/tokencount/table.py` — those belong to plans B and C.

**Goal:** give the project its reproducible base environment (uv venvs, pinned requirements, secrets scaffolding) and the committed corpus definition plus `src/tokencount/corpus.py` implementing the shared `load_entries`/`fetch_corpus` contract that plans B and C build on.

**Architecture:** Plan A builds everything the other two plans stand on: `./devenv.sh` creates the four uv-managed envs from committed pinned requirements, the secretspec/SOPS/age scaffolding declares the five optional API keys, and `corpus/eu-members.txt` + `corpus/repos.txt` are the committed source of truth for the corpus that `src/tokencount/corpus.py` fetches into the gitignored `samples/` cache. Plan B's orchestrator (`run.py`) will call `load_entries()`/`fetch_corpus()` and consume `Sample` fields to write CSV rows; Plan C's `table.py` derives its columns from the file types these samples carry. **This plan has no upstream plan dependency.** The contract interfaces it produces for plans B and C are exactly: `CorpusEntry(file_type, name, url, repo, sha, path)`, `load_entries() -> list[CorpusEntry]`, `Sample(path, file_type, name, sha256, chars, text)`, `fetch_corpus(entries, dest_dir="samples", fresh=False) -> list[Sample]` in `src/tokencount/corpus.py`, plus the data files `corpus/eu-members.txt` and `corpus/repos.txt` and the base `.venv` (httpx + secretspec) all plans run tests in.

**Tech Stack:** Python 3.14 (`.python-version`), uv 0.12.x, httpx and `secretspec>=0.21,<0.22` in the base env, SOPS + age as system CLIs, stdlib `unittest` for tests. Plan A adds no other runtime dependency; `corpus.py` and its tests run in the base `.venv` with httpx + stdlib only.

**Spec:** docs/superpowers/specs/2026-11-23-token-count-table-design.md

## Global Constraints

- Run command: `PYTHONPATH=src .venv/bin/python -m tokencount`; the base `.venv` runs the orchestrator and all of plan A's code/tests (httpx + stdlib only there).
- `./devenv.sh` creates exactly four venvs — `.venv` (requirements/base.txt: httpx, `secretspec>=0.21,<0.22`), `.venv-api` (requirements/api.txt: httpx, tenacity, tiktoken), `.venv-deepseek` (requirements/deepseek.txt: tokenizers), `.venv-mistral` (requirements/mistral.txt: tokenizers) — each requirements file pinned via `uv pip compile` and committed; `.python-version` committed; `devenv.sh` checks `sops` on PATH and an age identity and only warns when missing.
- Secrets: `secretspec.toml` declares `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `Z_AI_API_KEY`, `MOONSHOT_API_KEY`, each `required = false`, project provider chain `["sops", "env"]` under `[defaults].providers` (secretspec 0.21+); `secrets.enc.yaml` is committed SOPS+age ciphertext only; `.sops.yaml` holds the age creation rule; `.gitignore` covers `.venv*`, `__pycache__`, `samples/`, `key.txt`, `*.age`.
- Corpus (owner decision 2026-11-24, overrides the spec's inline URL list): `corpus/eu-members.txt` = 27 lines of `<file_type> <name> <url>` with file type `text` and `https://en.wikipedia.org/wiki/<Country>`; `corpus/repos.txt` = 5 lines of `<file_type> <name> <owner/repo> <git-sha> <path-in-repo>` with file types python, javascript, shell, rust, go and a comment header noting 2026-11-24; `samples/` is gitignored and the data files are the committed source of truth; fetch live at run time, cache unless `--fresh`; CSV keys on sha256 of file content.
- Plan split (owner decision 2026-11-24): Plan A = base environment + corpus definition/fetch only; Plan B owns `models.py`, `counters.py`, `run.py` and the CSV; Plan C owns `table.py` and `results/table.md`.
- Shared contract produced by this plan (exact names/signatures): `CorpusEntry(file_type: str, name: str, url: str, repo: str|None, sha: str|None, path: str|None)`; `load_entries() -> list[CorpusEntry]`; `Sample(path, file_type, name, sha256, chars, text)`; `fetch_corpus(entries, dest_dir="samples", fresh=False) -> list[Sample]` — for repo entries `load_entries` sets `url = https://raw.githubusercontent.com/<repo>/<sha>/<path>`.
- Tests: stdlib unittest only, run from the repo root in the base env: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_scaffolding tests.test_secretspec tests.test_corpus_data tests.test_corpus` (plans B/C add `tests.test_table` / `tests.test_counters`).

## Builder Decisions (marked)

- `.python-version` = `3.14` (matches the environment's Python 3.14.4; uv discovers it for `uv venv`).
- The owner's "javascript/typescript" slot is resolved as the most-starred repo across `language:javascript` AND `language:typescript` searches → **morluto/rea** (TypeScript, 476,080 stars) with sample file `src/adb/AdbCommand.ts`, stored under file type `javascript`. If the owner prefers the `language:javascript`-only top (affaan-m/ECC, 309,756 stars), it is a one-line edit in `corpus/repos.txt`.
- Repo choices and HEAD shas below were captured via the GitHub API on 2026-11-24; Task 3 re-runs the API calls at execution time and records the then-current HEAD sha (repo choice and sample path are fixed; re-verify the path exists at the recorded sha).
- `parse_entries(members_path, repos_path)` helper is added so tests can parse tmp files while `load_entries()` keeps the exact contract signature; `_make_client()` factory is added so tests inject `httpx.Client(transport=httpx.MockTransport(...))`.
- Requirements are regenerated with stdin input, e.g. `printf 'httpx\nsecretspec>=0.21,<0.22\n' | uv pip compile - --python-version 3.14 -o requirements/base.txt`.
- `sops`/`age` are not installed in the drafting environment, so `secrets.enc.yaml` is committed as a documented empty placeholder; Task 2 includes the step that creates the real ciphertext on a machine with an age identity.

## Review Focus

- Repo-entry URL built from the wrong field order (repo/sha/path) → `TestParseEntries.test_repo_line_builds_raw_url` (Task 4).
- Cache/`--fresh` logic inverted (cache bypassed or fresh ignored) → `TestFetchCorpus.test_cache_reuse_makes_no_http_request` and `test_fresh_redownloads` (Task 4).
- sha256 computed over bytes but chars over something else (or vice versa) → `TestFetchCorpus.test_sha256_and_chars` (Task 4).
- Committed data files drifting from the contract (not 27/5 lines, sha not 40-hex, header missing) → `tests.test_corpus_data` (Task 3).
- `secretspec.toml` not matching the 0.21 schema (chain not under `[defaults].providers`, keys not `required = false`) → `tests.test_secretspec` (Task 2); requirements not fully pinned `name==version` → `tests.test_scaffolding` (Task 1).

### Task 1: Repo scaffolding — .python-version, .gitignore, pinned requirements, devenv.sh

**Files:**
- Create: `.python-version`, `.gitignore`, `requirements/base.txt`, `requirements/api.txt`, `requirements/deepseek.txt`, `requirements/mistral.txt`, `devenv.sh`, `tests/__init__.py`, `tests/test_scaffolding.py`
- Modify: none
- Test: `tests/test_scaffolding.py` (run: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_scaffolding`; syntax check: `bash -n devenv.sh`)

**Interfaces:**
- Consumes: none (no upstream plan).
- Produces: the four venvs via `devenv.sh`; pinned `requirements/*.txt` consumed by `devenv.sh`; `.gitignore` (`.venv*`, `__pycache__`, `samples/`, `key.txt`, `*.age`); `.python-version` (`3.14`).

- [ ] **Step 1: write the failing test.** Create `tests/__init__.py` (empty) and `tests/test_scaffolding.py`:
  ```python
  import re
  import unittest
  from pathlib import Path

  ROOT = Path(__file__).resolve().parents[1]
  REQUIREMENTS = ["base", "api", "deepseek", "mistral"]
  PINNED = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*==[A-Za-z0-9_.!+]+$")


  class TestRequirements(unittest.TestCase):
      def test_all_four_exist_and_fully_pinned(self):
          for name in REQUIREMENTS:
              path = ROOT / "requirements" / f"{name}.txt"
              self.assertTrue(path.is_file(), str(path))
              lines = [l for l in path.read_text(encoding="utf-8").splitlines()
                       if l.strip() and not l.startswith("#")]
              self.assertTrue(lines, str(path))
              for line in lines:
                  self.assertRegex(line, PINNED, line)

      def test_base_pins_httpx_and_secretspec(self):
          text = (ROOT / "requirements" / "base.txt").read_text(encoding="utf-8")
          self.assertRegex(text, r"(?m)^httpx==\d")
          self.assertRegex(text, r"(?m)^secretspec==0\.21\.")
  ```
- [ ] **Step 2: run it, expect failure.** `python3 -m unittest tests.test_scaffolding -v` → FAIL: `requirements/base.txt` (and the other three) missing.
- [ ] **Step 3: implement.** Write `.python-version` containing exactly `3.14`; write `.gitignore` with exactly `.venv*`, `__pycache__`, `samples/`, `key.txt`, `*.age` (one per line); generate the pinned requirements with:
  - `printf 'httpx\nsecretspec>=0.21,<0.22\n' | uv pip compile - --python-version 3.14 -o requirements/base.txt`
  - `printf 'httpx\ntenacity\ntiktoken\n' | uv pip compile - --python-version 3.14 -o requirements/api.txt`
  - `printf 'tokenizers\n' | uv pip compile - --python-version 3.14 -o requirements/deepseek.txt`
  - `printf 'tokenizers\n' | uv pip compile - --python-version 3.14 -o requirements/mistral.txt`
  Write `devenv.sh` (bash, `set -euo pipefail`, `chmod +x`): `uv venv .venv` + `uv pip install --python .venv/bin/python -r requirements/base.txt`; same pattern for `.venv-api`/api.txt, `.venv-deepseek`/deepseek.txt, `.venv-mistral`/mistral.txt; then warn-only checks: `command -v sops >/dev/null 2>&1 || echo "warning: sops not on PATH (sops:// provider needs it)" >&2` and warn if neither `SOPS_AGE_KEY`, `SOPS_AGE_KEY_FILE`, nor `$HOME/.config/age/key.txt` exists. Verify syntax: `bash -n devenv.sh`, then run `./devenv.sh` to create the four envs.
- [ ] **Step 4: run tests, expect pass.** `PYTHONPATH=src .venv/bin/python -m unittest tests.test_scaffolding -v` → 2 tests OK (all four files exist, every non-comment line matches `name==version`, base pins `httpx==` and `secretspec==0.21.`); `bash -n devenv.sh` → exit 0.
- [ ] **Step 5: commit.** `git add .python-version .gitignore requirements devenv.sh tests && git commit -m "chore: base environment scaffolding (devenv.sh, pinned requirements, gitignore)"`

### Task 2: Secrets scaffolding — secretspec.toml, .sops.yaml, secrets.enc.yaml

**Files:**
- Create: `secretspec.toml`, `.sops.yaml`, `secrets.enc.yaml`, `tests/test_secretspec.py`
- Modify: none
- Test: `tests/test_secretspec.py` (run: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_secretspec`; stdlib `tomllib` only)

**Interfaces:**
- Consumes: none.
- Produces: `secretspec.toml` (five keys, `required = false`, `[defaults].providers = ["sops", "env"]`), `.sops.yaml` (age creation rule), `secrets.enc.yaml` (SOPS ciphertext; placeholder until a machine with an age identity creates it) — consumed by plan B's `run.py` secrets resolution.

- [ ] **Step 1: write the failing test.** Create `tests/test_secretspec.py`:
  ```python
  import tomllib
  import unittest
  from pathlib import Path

  ROOT = Path(__file__).resolve().parents[1]
  KEYS = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY",
          "Z_AI_API_KEY", "MOONSHOT_API_KEY"]


  class TestSecretspecToml(unittest.TestCase):
      def test_parses_and_declares_five_optional_keys(self):
          data = tomllib.loads((ROOT / "secretspec.toml").read_text(encoding="utf-8"))
          self.assertEqual(["sops", "env"], data["defaults"]["providers"])
          secrets = data["profiles"]["default"]
          self.assertEqual(5, len(secrets))
          for key in KEYS:
              self.assertIn(key, secrets)
              self.assertIs(secrets[key]["required"], False)
  ```
- [ ] **Step 2: run it, expect failure.** `python3 -m unittest tests.test_secretspec -v` → FAIL: `FileNotFoundError: secretspec.toml`.
- [ ] **Step 3: implement.** Write `secretspec.toml` exactly:
  ```toml
  [project]
  name = "token-count"
  revision = "1.0"

  # Provider aliases: sops:// reads secrets.enc.yaml through the sops CLI,
  # env:// reads process environment variables (CI fallback).
  [providers]
  sops = "sops://secrets.enc.yaml"
  env = "env://"

  # secretspec 0.21+ project-level provider chain.
  [defaults]
  providers = ["sops", "env"]

  [profiles.default]
  OPENAI_API_KEY = { description = "OpenAI key for /v1/responses/input_tokens", required = false }
  ANTHROPIC_API_KEY = { description = "Anthropic key for /v1/messages/count_tokens", required = false }
  GOOGLE_API_KEY = { description = "Google key for generativelanguage countTokens", required = false }
  Z_AI_API_KEY = { description = "Z.ai key for /api/paas/v4/tokenizer", required = false }
  MOONSHOT_API_KEY = { description = "Moonshot key for /v1/tokenizers/estimate-token-count (Kimi)", required = false }
  ```
  Write `.sops.yaml` with a comment block (run `age-keygen -o ~/.config/age/key.txt`, `export SOPS_AGE_KEY_FILE=$HOME/.config/age/key.txt`, paste the PUBLIC recipient below) and the rule:
  ```yaml
  creation_rules:
    - path_regex: secrets\.enc\.yaml$
      age: age1REPLACE_WITH_YOUR_PUBLIC_RECIPIENT
  ```
  Write `secrets.enc.yaml` as a commented placeholder (empty values, no secrets) headed by the replacement instructions: `printf 'OPENAI_API_KEY: ""\nANTHROPIC_API_KEY: ""\nGOOGLE_API_KEY: ""\nZ_AI_API_KEY: ""\nMOONSHOT_API_KEY: ""\n' | sops --encrypt --age <recipient-from-.sops.yaml> /dev/stdin > secrets.enc.yaml`. Because `sops` is not on PATH in this environment, add this step for a machine with an age identity: create the real ciphertext with that command, then set each key once with `secretspec set OPENAI_API_KEY --provider sops://secrets.enc.yaml` (likewise ANTHROPIC_API_KEY, GOOGLE_API_KEY, Z_AI_API_KEY, MOONSHOT_API_KEY) and verify with `secretspec check`.
- [ ] **Step 4: run tests, expect pass.** `PYTHONPATH=src .venv/bin/python -m unittest tests.test_secretspec -v` → 1 test OK (tomllib parses; chain `["sops","env"]`; exactly the five keys, each `required = false`).
- [ ] **Step 5: commit.** `git add secretspec.toml .sops.yaml secrets.enc.yaml tests/test_secretspec.py && git commit -m "chore: secretspec manifest + SOPS/age secrets scaffolding"`

### Task 3: Corpus data files — corpus/eu-members.txt and corpus/repos.txt

**Files:**
- Create: `corpus/eu-members.txt`, `corpus/repos.txt`, `tests/test_corpus_data.py`
- Modify: none
- Test: `tests/test_corpus_data.py` (run: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_corpus_data`; stdlib only, no network)

**Interfaces:**
- Consumes: GitHub REST API (read-only verification at execution time).
- Produces: `corpus/eu-members.txt` (27 lines `<file_type> <name> <url>`) and `corpus/repos.txt` (comment header + 5 lines `<file_type> <name> <owner/repo> <git-sha> <path-in-repo>`) — parsed by plan A's `load_entries()` (Task 4) and fetched by plan B's `run.py`.

- [ ] **Step 1: write the failing test.** Create `tests/test_corpus_data.py`:
  ```python
  import unittest
  from pathlib import Path

  ROOT = Path(__file__).resolve().parents[1]
  EU = ["Austria", "Belgium", "Bulgaria", "Croatia", "Cyprus", "Czechia",
        "Denmark", "Estonia", "Finland", "France", "Germany", "Greece",
        "Hungary", "Ireland", "Italy", "Latvia", "Lithuania", "Luxembourg",
        "Malta", "Netherlands", "Poland", "Portugal", "Romania", "Slovakia",
        "Slovenia", "Spain", "Sweden"]


  class TestEuMembers(unittest.TestCase):
      def test_27_wikipedia_entries(self):
          lines = (ROOT / "corpus" / "eu-members.txt").read_text(encoding="utf-8").splitlines()
          self.assertEqual(27, len(lines))
          for line, country in zip(lines, EU):
              self.assertEqual(
                  f"text {country} https://en.wikipedia.org/wiki/{country}", line)


  class TestRepos(unittest.TestCase):
      def test_header_and_5_pinned_entries(self):
          raw = (ROOT / "corpus" / "repos.txt").read_text(encoding="utf-8").splitlines()
          self.assertTrue(any("2026-11-24" in l for l in raw))
          entries = [l for l in raw if l.strip() and not l.startswith("#")]
          self.assertEqual(5, len(entries))
          types = []
          for line in entries:
              parts = line.split()
              self.assertEqual(5, len(parts), line)
              file_type, name, repo, sha, path = parts
              types.append(file_type)
              self.assertRegex(repo, r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
              self.assertRegex(sha, r"^[0-9a-f]{40}$")
              self.assertTrue(path)
          self.assertEqual(["python", "javascript", "shell", "rust", "go"], types)
  ```
- [ ] **Step 2: run it, expect failure.** `python3 -m unittest tests.test_corpus_data -v` → FAIL: `FileNotFoundError: corpus/eu-members.txt`.
- [ ] **Step 3: implement.** Verify the picks with the GitHub API, then write the files. Verification commands (run at execution time; record the then-current HEAD sha):
  - `curl -s "https://api.github.com/search/repositories?q=language:python&sort=stars&per_page=1"` → `public-apis/public-apis`
  - `curl -s "https://api.github.com/search/repositories?q=language:javascript&sort=stars&per_page=1"` → `affaan-m/ECC`; `...?q=language:typescript&sort=stars&per_page=1` → `morluto/rea` (476,080* — wins the combined javascript/typescript slot, see Builder Decisions)
  - `curl -s "https://api.github.com/search/repositories?q=language:shell&sort=stars&per_page=1"` → `mattpocock/skills`
  - `curl -s "https://api.github.com/search/repositories?q=language:rust&sort=stars&per_page=1"` → `ultraworkers/claw-code`
  - `curl -s "https://api.github.com/search/repositories?q=language:go&sort=stars&per_page=1"` → `avelino/awesome-go`
  - per repo: `curl -s "https://api.github.com/repos/<owner>/<repo>/commits/HEAD"` → record `sha`; verify the sample path exists at that sha via `curl -s "https://api.github.com/repos/<owner>/<repo>/contents/<path>" -o /dev/null -w "%{http_code}\n"` (expect 200; or list `git/trees/<sha>?recursive=1`).
  Write `corpus/eu-members.txt` as exactly these 27 lines (no header):
  ```
  text Austria https://en.wikipedia.org/wiki/Austria
  text Belgium https://en.wikipedia.org/wiki/Belgium
  text Bulgaria https://en.wikipedia.org/wiki/Bulgaria
  text Croatia https://en.wikipedia.org/wiki/Croatia
  text Cyprus https://en.wikipedia.org/wiki/Cyprus
  text Czechia https://en.wikipedia.org/wiki/Czechia
  text Denmark https://en.wikipedia.org/wiki/Denmark
  text Estonia https://en.wikipedia.org/wiki/Estonia
  text Finland https://en.wikipedia.org/wiki/Finland
  text France https://en.wikipedia.org/wiki/France
  text Germany https://en.wikipedia.org/wiki/Germany
  text Greece https://en.wikipedia.org/wiki/Greece
  text Hungary https://en.wikipedia.org/wiki/Hungary
  text Ireland https://en.wikipedia.org/wiki/Ireland
  text Italy https://en.wikipedia.org/wiki/Italy
  text Latvia https://en.wikipedia.org/wiki/Latvia
  text Lithuania https://en.wikipedia.org/wiki/Lithuania
  text Luxembourg https://en.wikipedia.org/wiki/Luxembourg
  text Malta https://en.wikipedia.org/wiki/Malta
  text Netherlands https://en.wikipedia.org/wiki/Netherlands
  text Poland https://en.wikipedia.org/wiki/Poland
  text Portugal https://en.wikipedia.org/wiki/Portugal
  text Romania https://en.wikipedia.org/wiki/Romania
  text Slovakia https://en.wikipedia.org/wiki/Slovakia
  text Slovenia https://en.wikipedia.org/wiki/Slovenia
  text Spain https://en.wikipedia.org/wiki/Spain
  text Sweden https://en.wikipedia.org/wiki/Sweden
  ```
  Write `corpus/repos.txt` with the header `# repos.txt — most-starred GitHub repo per language, chosen via the GitHub search API (sort=stars) on 2026-11-24.` / `# Format: <file_type> <name> <owner/repo> <git-sha> <path-in-repo>` and these 5 lines (shas as captured 2026-11-24; refresh if HEAD moved at execution):
  ```
  python public-apis public-apis/public-apis 9fb3bdb62643400aaebee03a2ecce0cd1ec934eb scripts/validate/links.py
  javascript rea morluto/rea b8dd2c47d46419b0d82d03c1de2f261b7ffe3f73 src/adb/AdbCommand.ts
  shell skills mattpocock/skills abeeaf95660ba9e8b7c753eb38f441ca707a8823 scripts/link-skills.sh
  rust claw-code ultraworkers/claw-code a5c2775e81153b42e5e3910cf3f12982879eef78 rust/crates/api/src/lib.rs
  go awesome-go avelino/awesome-go bd23d8783aa140e6ad7da9058d382caabf62175d .github/scripts/check-quality/main.go
  ```
- [ ] **Step 4: run tests, expect pass.** `PYTHONPATH=src .venv/bin/python -m unittest tests.test_corpus_data -v` → 2 tests OK (27 exact member lines; header contains 2026-11-24; 5 repo lines with 5 fields, `owner/repo` shape, 40-hex sha, file types exactly python/javascript/shell/rust/go in order).
- [ ] **Step 5: commit.** `git add corpus tests/test_corpus_data.py && git commit -m "feat: corpus data files (27 EU Wikipedia articles, 5 pinned language repos)"`

### Task 4: src/tokencount/corpus.py + tests/test_corpus.py

**Files:**
- Create: `src/tokencount/__init__.py` (empty), `src/tokencount/corpus.py`, `tests/test_corpus.py`
- Modify: none
- Test: `tests/test_corpus.py` (run: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_corpus` — base `.venv`, httpx + stdlib only)

**Interfaces:**
- Consumes: `corpus/eu-members.txt`, `corpus/repos.txt` (via `load_entries()`).
- Produces (shared contract for plans B and C): `CorpusEntry(file_type: str, name: str, url: str, repo: str|None, sha: str|None, path: str|None)`; `load_entries() -> list[CorpusEntry]`; `Sample(path, file_type, name, sha256, chars, text)`; `fetch_corpus(entries, dest_dir="samples", fresh=False) -> list[Sample]`. Plan B's `run.py` calls these; plan C's `table.py` gets file types from the CSV rows built on `Sample`.

- [ ] **Step 1: write the failing test.** Create `tests/test_corpus.py`:
  ```python
  import hashlib
  import tempfile
  import unittest
  from pathlib import Path
  from unittest.mock import patch

  import httpx

  from tokencount.corpus import CorpusEntry, fetch_corpus, load_entries, parse_entries

  MEMBERS_TXT = ("text Austria https://en.wikipedia.org/wiki/Austria\n"
                 "text Spain https://en.wikipedia.org/wiki/Spain\n")
  REPOS_TXT = ("# repos header\n"
               "python public-apis public-apis/public-apis "
               "9fb3bdb62643400aaebee03a2ecce0cd1ec934eb scripts/validate/links.py\n")


  def _write_tmp(td, members=MEMBERS_TXT, repos=REPOS_TXT):
      m, r = Path(td) / "eu-members.txt", Path(td) / "repos.txt"
      m.write_text(members, encoding="utf-8")
      r.write_text(repos, encoding="utf-8")
      return m, r


  class TestParseEntries(unittest.TestCase):
      def test_member_lines(self):
          with tempfile.TemporaryDirectory() as td:
              m, r = _write_tmp(td)
              entries = parse_entries(m, r)
          self.assertEqual(
              CorpusEntry("text", "Austria", "https://en.wikipedia.org/wiki/Austria",
                          None, None, None), entries[0])
          self.assertEqual(
              CorpusEntry("text", "Spain", "https://en.wikipedia.org/wiki/Spain",
                          None, None, None), entries[1])

      def test_repo_line_builds_raw_url(self):
          with tempfile.TemporaryDirectory() as td:
              m, r = _write_tmp(td)
              e = parse_entries(m, r)[2]
          self.assertEqual("python", e.file_type)
          self.assertEqual("public-apis", e.name)
          self.assertEqual("https://raw.githubusercontent.com/public-apis/public-apis/"
                           "9fb3bdb62643400aaebee03a2ecce0cd1ec934eb/scripts/validate/links.py",
                           e.url)
          self.assertEqual("public-apis/public-apis", e.repo)
          self.assertEqual("9fb3bdb62643400aaebee03a2ecce0cd1ec934eb", e.sha)
          self.assertEqual("scripts/validate/links.py", e.path)

      def test_wrong_field_count_raises(self):
          with tempfile.TemporaryDirectory() as td:
              m, r = _write_tmp(td, members="text Austria\n")
              with self.assertRaises(ValueError):
                  parse_entries(m, r)


  ENTRY = CorpusEntry("text", "Austria", "https://example.test/Austria", None, None, None)


  def _patch_client(handler):
      return patch("tokencount.corpus._make_client",
                   side_effect=lambda: httpx.Client(transport=httpx.MockTransport(handler)))


  class TestFetchCorpus(unittest.TestCase):
      def test_fetch_writes_file_and_hashes(self):
          def handler(request):
              return httpx.Response(200, content=b"hello wikipedia")
          with tempfile.TemporaryDirectory() as td, _patch_client(handler):
              s = fetch_corpus([ENTRY], dest_dir=td)[0]
              self.assertEqual(str(Path(td) / "text" / "Austria"), s.path)
              self.assertTrue((Path(td) / "text" / "Austria").read_bytes() == b"hello wikipedia")
          self.assertEqual("text", s.file_type)
          self.assertEqual("Austria", s.name)
          self.assertEqual(hashlib.sha256(b"hello wikipedia").hexdigest(), s.sha256)
          self.assertEqual(len("hello wikipedia"), s.chars)
          self.assertEqual("hello wikipedia", s.text)

      def test_cache_reuse_makes_no_http_request(self):
          calls = []
          def handler(request):
              calls.append(request)
              return httpx.Response(200, content=b"cached body")
          with tempfile.TemporaryDirectory() as td:
              with _patch_client(handler):
                  first = fetch_corpus([ENTRY], dest_dir=td)
              self.assertEqual(1, len(calls))
              def boom(request):
                  raise AssertionError("HTTP request made on cache hit")
              with _patch_client(boom):
                  second = fetch_corpus([ENTRY], dest_dir=td)
          self.assertEqual(first[0].sha256, second[0].sha256)
          self.assertEqual(hashlib.sha256(b"cached body").hexdigest(), second[0].sha256)

      def test_fresh_redownloads(self):
          calls = []
          def handler(request):
              calls.append(request)
              return httpx.Response(200, content=b"v%d" % len(calls))
          with tempfile.TemporaryDirectory() as td:
              with _patch_client(handler):
                  fetch_corpus([ENTRY], dest_dir=td)
                  fresh = fetch_corpus([ENTRY], dest_dir=td, fresh=True)
          self.assertEqual(2, len(calls))
          self.assertEqual(hashlib.sha256(b"v2").hexdigest(), fresh[0].sha256)

      def test_sha256_and_chars_on_unicode(self):
          body = "héllo wörld".encode("utf-8")
          def handler(request):
              return httpx.Response(200, content=body)
          with tempfile.TemporaryDirectory() as td, _patch_client(handler):
              s = fetch_corpus([ENTRY], dest_dir=td)[0]
          self.assertEqual(hashlib.sha256(body).hexdigest(), s.sha256)
          self.assertEqual(len("héllo wörld"), s.chars)
          self.assertEqual("héllo wörld", s.text)


  class TestLoadEntriesCommitted(unittest.TestCase):
      def test_committed_corpus_loads(self):
          entries = load_entries()
          self.assertEqual(32, len(entries))
          self.assertEqual({"text", "python", "javascript", "shell", "rust", "go"},
                           {e.file_type for e in entries})
          for e in entries:
              if e.repo is None:
                  self.assertTrue(e.url.startswith("https://en.wikipedia.org/wiki/"))
              else:
                  self.assertTrue(e.url.startswith("https://raw.githubusercontent.com/"))
  ```
- [ ] **Step 2: run it, expect failure.** `PYTHONPATH=src python3 -m unittest tests.test_corpus -v` → FAIL: `ModuleNotFoundError: No module named 'tokencount'`.
- [ ] **Step 3: implement.** Create `src/tokencount/__init__.py` (empty) and `src/tokencount/corpus.py` with exactly the contract signatures: `@dataclass CorpusEntry(file_type: str, name: str, url: str, repo: str|None, sha: str|None, path: str|None)`; module constants `REPO_ROOT = Path(__file__).resolve().parents[2]`, `EU_MEMBERS_FILE = REPO_ROOT / "corpus" / "eu-members.txt"`, `REPOS_FILE = REPO_ROOT / "corpus" / "repos.txt"`; `parse_entries(members_path=EU_MEMBERS_FILE, repos_path=REPOS_FILE) -> list[CorpusEntry]` (skip blank/`#` lines; 3 fields → member entry with repo/sha/path None; 5 fields → repo entry with `url = f"https://raw.githubusercontent.com/{repo}/{sha}/{path}"`; any other field count raises `ValueError`); `load_entries()` = `parse_entries()`; `@dataclass Sample(path: str, file_type: str, name: str, sha256: str, chars: int, text: str)`; `_make_client() -> httpx.Client` returning `httpx.Client(timeout=30.0, follow_redirects=True)`; `fetch_corpus(entries, dest_dir="samples", fresh=False) -> list[Sample]` — per entry, dest = `Path(dest_dir)/entry.file_type/entry.name`; if dest exists and not fresh, read cached bytes, else `client.get(entry.url)`, `raise_for_status()`, mkdir parents, write bytes; then `text = data.decode("utf-8")`, `Sample(str(dest), entry.file_type, entry.name, hashlib.sha256(data).hexdigest(), len(text), text)`; return samples in entry order.
- [ ] **Step 4: run tests, expect pass.** `PYTHONPATH=src .venv/bin/python -m unittest tests.test_corpus -v` → 7 tests OK; then the full plan-A suite `PYTHONPATH=src .venv/bin/python -m unittest tests.test_scaffolding tests.test_secretspec tests.test_corpus_data tests.test_corpus` → all OK.
- [ ] **Step 5: commit.** `git add src tests/test_corpus.py && git commit -m "feat: tokencount.corpus load_entries/fetch_corpus with tests"`

### Task 5: README.md setup section

**Files:**
- Create: none
- Modify: `README.md`, `tests/test_scaffolding.py` (add `TestReadme`)
- Test: `tests/test_scaffolding.py` (run: `PYTHONPATH=src .venv/bin/python -m unittest tests.test_scaffolding`)

**Interfaces:**
- Consumes: the spec's Secrets/Environments sections and the owner decisions.
- Produces: `README.md` setup/usage docs for the whole project (plans B/C fill in behavior as they land).

- [ ] **Step 1: write the failing test.** Append to `tests/test_scaffolding.py`:
  ```python
  class TestReadme(unittest.TestCase):
      def test_readme_documents_setup_and_run(self):
          text = (ROOT / "README.md").read_text(encoding="utf-8")
          for needle in ["./devenv.sh",
                         "PYTHONPATH=src .venv/bin/python -m tokencount",
                         "secretspec.toml", "secretspec set", "secretspec check"]:
              self.assertIn(needle, text)
  ```
- [ ] **Step 2: run it, expect failure.** `PYTHONPATH=src .venv/bin/python -m unittest tests.test_scaffolding -v` → `TestReadme` FAILS (current README has none of the needles); `TestRequirements` still OK.
- [ ] **Step 3: implement.** Extend `README.md` (keep the existing title/tagline) with a **Setup** section: prerequisites (`uv`, Python from `.python-version`, `sops` + an `age` identity for secrets); step 1 `./devenv.sh` (creates `.venv`, `.venv-api`, `.venv-deepseek`, `.venv-mistral` from pinned requirements; warns if `sops`/age identity missing); step 2 secrets once per machine — `age-keygen` into `~/.config/age/key.txt` with `SOPS_AGE_KEY_FILE` exported, public recipient in `.sops.yaml`, `secrets.enc.yaml` created with sops, then `secretspec set OPENAI_API_KEY --provider sops://secrets.enc.yaml` (likewise ANTHROPIC_API_KEY, GOOGLE_API_KEY, Z_AI_API_KEY, MOONSHOT_API_KEY) and `secretspec check`; note that the provider chain `["sops","env"]` falls back to environment variables and every key is optional (`missing key <ENV>` per model, never an abort); step 3 run: `PYTHONPATH=src .venv/bin/python -m tokencount`. Add a **Corpus** note (data files `corpus/eu-members.txt` + `corpus/repos.txt` are the committed source of truth; files fetched live into gitignored `samples/`, cached unless `--fresh`; results key on sha256) and a **Tests** section listing `PYTHONPATH=src .venv/bin/python -m unittest tests.test_corpus tests.test_table`, `.venv-api/bin/python -m unittest tests.test_counters`, `.venv-deepseek/bin/python -m unittest tests.test_counters`.
- [ ] **Step 4: run tests, expect pass.** `PYTHONPATH=src .venv/bin/python -m unittest tests.test_scaffolding tests.test_secretspec tests.test_corpus_data tests.test_corpus -v` → all OK including `TestReadme`.
- [ ] **Step 5: commit.** `git add README.md tests/test_scaffolding.py && git commit -m "docs: README setup and run instructions"`

## Handoff

This plan is saved at `docs/superpowers/plans/2026-11-24-plan-a-base-env-and-corpus.md` and awaits the owner's review and execution-method choice.
