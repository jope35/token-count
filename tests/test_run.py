import csv
import hashlib
import os
import subprocess
import tempfile
import unittest
from unittest import mock

import httpx

from tokencount import counters, run
from tokencount.corpus import Sample

# Plan A contract shape: member names carry no extension and Sample.path is
# the relative string samples/<file_type>/<name>. sha256 is over the raw bytes
# while chars is len() of the decoded text, so the fixture is non-ASCII to
# pin the units (5 characters, 6 bytes).
SAMPLE = Sample(
    path="samples/text/France",
    file_type="text",
    name="France",
    sha256=hashlib.sha256("héllo".encode("utf-8")).hexdigest(),
    chars=5,
    text="héllo",
)


def fake_corpus(*args, **kwargs):
    return [SAMPLE]


FAMILY_KEY = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "glm": "Z_AI_API_KEY",
    "kimi": "MOONSHOT_API_KEY",
}
LOCAL_FAMILIES = {"deepseek", "mistral", "glm_local", "kimi_local"}
ALL_SECRETS = {k: k.lower() for k in FAMILY_KEY.values()}


class TestRouteEnv(unittest.TestCase):
    def test_all_families_route_to_single_venv(self):
        for family in list(FAMILY_KEY) + sorted(LOCAL_FAMILIES):
            self.assertEqual(run.route_env(family), ".venv")


class TestFamilyEnv(unittest.TestCase):
    def test_least_privilege(self):
        for family, key_env in FAMILY_KEY.items():
            env = run.family_env(family, ALL_SECRETS)
            self.assertEqual(env["PYTHONPATH"], "src")
            self.assertEqual(env[key_env], ALL_SECRETS[key_env])
            self.assertEqual(set(env) - {"PYTHONPATH", key_env}, set())

    def test_missing_key_omitted(self):
        self.assertEqual(run.family_env("glm", {}), {"PYTHONPATH": "src"})

    def test_local_family_gets_no_key(self):
        for family in LOCAL_FAMILIES:
            self.assertEqual(run.family_env(family, ALL_SECRETS), {"PYTHONPATH": "src"})


class TestRenderResults(unittest.TestCase):
    def test_render_results_calls_write_table(self):
        with mock.patch("tokencount.table.write_table") as wt:
            run.render_results()
        wt.assert_called_once_with()


class TestWorker(unittest.TestCase):
    def run_worker(self, family, csv_path, fresh=False, env=None):
        with (
            mock.patch.object(run, "RESULTS_CSV", csv_path),
            mock.patch.object(run, "load_entries", return_value=[]),
            mock.patch.object(run, "fetch_corpus", fake_corpus),
            mock.patch.dict(os.environ, env or {}, clear=True),
            mock.patch("tokencount.counters.count_tokens", return_value=7) as ct,
        ):
            rc = run.run_worker(family, fresh=fresh, results_csv=csv_path)
        return rc, ct

    def read_rows(self, csv_path):
        with open(csv_path, newline="") as f:
            return list(csv.DictReader(f))

    def test_appends_rows_with_exact_columns(self):
        with tempfile.TemporaryDirectory() as d:
            csv_path = os.path.join(d, "results.csv")
            rc, ct = self.run_worker("openai", csv_path, env={"OPENAI_API_KEY": "k"})
            self.assertEqual(rc, 0)
            self.assertEqual(ct.call_count, 4)
            rows = self.read_rows(csv_path)
            self.assertEqual(len(rows), 4)
            self.assertEqual(list(rows[0].keys()), run.CSV_COLUMNS)
            r = rows[0]
            self.assertTrue(r["file"].startswith("samples/"))
            self.assertEqual(
                (
                    r["provider"],
                    r["model"],
                    r["strategy"],
                    r["file"],
                    r["file_type"],
                    r["sha256"],
                    r["chars"],
                    r["tokens"],
                    r["note"],
                ),
                (
                    "openai",
                    "gpt-6.2-astra",
                    "openai_api",
                    "samples/text/France",
                    "text",
                    SAMPLE.sha256,
                    "5",
                    "7",
                    "",
                ),
            )

    def write_existing(self, csv_path):
        with open(csv_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(run.CSV_COLUMNS)
            w.writerow(
                [
                    "2026-11-24T00:00:00+00:00",
                    "openai",
                    "gpt-6.2-astra",
                    "openai_api",
                    "samples/text/France",
                    "text",
                    SAMPLE.sha256,
                    "5",
                    "7",
                    "",
                ]
            )

    def test_dedup_skips_existing_pair(self):
        with tempfile.TemporaryDirectory() as d:
            csv_path = os.path.join(d, "results.csv")
            self.write_existing(csv_path)
            rc, ct = self.run_worker("openai", csv_path, env={"OPENAI_API_KEY": "k"})
            self.assertEqual(ct.call_count, 3)
            self.assertEqual(len(self.read_rows(csv_path)), 4)

    def test_fresh_recounts_everything(self):
        with tempfile.TemporaryDirectory() as d:
            csv_path = os.path.join(d, "results.csv")
            self.write_existing(csv_path)
            rc, ct = self.run_worker(
                "openai", csv_path, fresh=True, env={"OPENAI_API_KEY": "k"}
            )
            self.assertEqual(ct.call_count, 4)

    def test_error_note_row(self):
        with tempfile.TemporaryDirectory() as d:
            csv_path = os.path.join(d, "results.csv")
            with (
                mock.patch.object(run, "load_entries", return_value=[]),
                mock.patch.object(run, "fetch_corpus", fake_corpus),
                mock.patch.dict(os.environ, {"GOOGLE_API_KEY": "k"}, clear=True),
                mock.patch(
                    "tokencount.counters.count_tokens", side_effect=RuntimeError("boom")
                ),
            ):
                run.run_worker("google", results_csv=csv_path)
            rows = self.read_rows(csv_path)
            self.assertEqual(len(rows), 3)
            for r in rows:
                self.assertEqual(r["tokens"], "")
                self.assertEqual(r["note"], "error: boom")

    def test_error_rows_are_recounted_on_rerun(self):
        with tempfile.TemporaryDirectory() as d:
            csv_path = os.path.join(d, "results.csv")
            with (
                mock.patch.object(run, "load_entries", return_value=[]),
                mock.patch.object(run, "fetch_corpus", fake_corpus),
                mock.patch.dict(os.environ, {"GOOGLE_API_KEY": "k"}, clear=True),
                mock.patch(
                    "tokencount.counters.count_tokens", side_effect=RuntimeError("boom")
                ),
            ):
                run.run_worker("google", results_csv=csv_path)
            rc, ct = self.run_worker("google", csv_path, env={"GOOGLE_API_KEY": "k"})
            self.assertEqual(ct.call_count, 3)
            rows = self.read_rows(csv_path)
            self.assertEqual(len(rows), 6)
            self.assertEqual([r["tokens"] for r in rows[3:]], ["7", "7", "7"])
            rc, ct = self.run_worker("google", csv_path, env={"GOOGLE_API_KEY": "k"})
            self.assertEqual(ct.call_count, 0)
            self.assertEqual(len(self.read_rows(csv_path)), 6)

    def test_torn_trailing_row_is_not_a_dedup_key(self):
        with tempfile.TemporaryDirectory() as d:
            csv_path = os.path.join(d, "results.csv")
            with open(csv_path, "w", newline="") as f:
                f.write(",".join(run.CSV_COLUMNS) + "\n")
                f.write(
                    "2026-11-24T00:00:00+00:00,openai,gpt-6.2-astra,openai_api,"
                    "samples/text/France,text,%s,5,7,\n" % SAMPLE.sha256
                )
                f.write(
                    "2026-11-24T00:00:00+00:00,openai,gpt-6.2-sol"
                )  # torn line, no newline
            keys = run.read_dedup_keys(csv_path)
            self.assertEqual(
                keys,
                {("gpt-6.2-astra", "openai_api", "samples/text/France", SAMPLE.sha256)},
            )
            rc, ct = self.run_worker("openai", csv_path, env={"OPENAI_API_KEY": "k"})
            self.assertEqual(ct.call_count, 3)  # the torn row's model is recounted

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


class TestSplitFamilies(unittest.TestCase):
    def test_split_families_from_registry(self):
        families = sorted({m.family for m in run.REGISTRY})
        api, local = run.split_families(families)
        self.assertEqual(set(api), {"openai", "anthropic", "google", "glm", "kimi"})
        self.assertEqual(
            set(local), {"deepseek", "mistral", "glm_local", "kimi_local"}
        )


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


class TestOrchestrator(unittest.TestCase):
    def _run_main(self, argv=None, popen_rcs=(0,) * 5, run_rcs=(0,) * 4):
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

    def test_popen_five_api_and_run_four_local(self):
        rc, popens, runs, calls, agg, rr = self._run_main()
        self.assertEqual(rc, 0)
        self.assertEqual(len(popens), 5)
        self.assertEqual(len(runs), 4)
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
            pending.append(f"results/pending/{family}.csv")
            self.assertEqual(set(env), {"PYTHONPATH"})  # local: no key
        self.assertEqual(local_families, LOCAL_FAMILIES)
        self.assertEqual(len(set(pending)), 9)  # every worker its own file
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
                after = open(csv_path, "rb").read()
            finally:
                os.chdir(cwd)
        self.assertEqual(len(procs), 5)
        for p in procs:
            p.terminate.assert_called_once_with()
        agg.assert_not_called()
        rr.assert_not_called()
        self.assertNotEqual(rc, 0)
        self.assertEqual(after, before)  # results.csv untouched


class TestSecretsGuard(unittest.TestCase):
    def test_dotenv_loaded_and_process_env_wins(self):
        import os as _os, tempfile as _tf

        with _tf.NamedTemporaryFile("w", suffix=".env", delete=False) as f:
            f.write("OPENAI_API_KEY=from-dotenv\n# comment\n")
            path = f.name
        try:
            with mock.patch.dict(_os.environ, {"OPENAI_API_KEY": "from-env"}):
                self.assertEqual(
                    run.resolve_secrets(dotenv_path=path)["OPENAI_API_KEY"], "from-env"
                )
            with mock.patch.dict(_os.environ, {}, clear=True):
                self.assertEqual(
                    run.resolve_secrets(dotenv_path=path)["OPENAI_API_KEY"],
                    "from-dotenv",
                )
        finally:
            _os.unlink(path)

    def test_missing_dotenv_and_keys_yield_empty_dict(self):
        import os as _os

        with mock.patch.dict(_os.environ, {}, clear=True):
            self.assertEqual(run.resolve_secrets(dotenv_path="/nonexistent/.env"), {})


class TestOfflinePartialRun(unittest.TestCase):
    def test_missing_key_rows_and_exit_zero(self):
        def no_network(request):
            raise AssertionError("no HTTP call expected")

        counters.TRANSPORT = httpx.MockTransport(no_network)
        try:
            with tempfile.TemporaryDirectory() as d:
                csv_path = os.path.join(d, "results.csv")
                with (
                    mock.patch.object(run, "RESULTS_CSV", csv_path),
                    mock.patch.object(run, "load_entries", return_value=[]),
                    mock.patch.object(run, "fetch_corpus", fake_corpus),
                    mock.patch.dict(os.environ, {}, clear=True),
                ):
                    rc = run.main(["--family", "glm"])
                self.assertEqual(rc, 0)
                with open(csv_path, newline="") as f:
                    rows = list(csv.DictReader(f))
                self.assertEqual(len(rows), 1)
                for r in rows:
                    self.assertEqual(r["tokens"], "")
                    self.assertEqual(r["note"], "missing key Z_AI_API_KEY")
        finally:
            counters.TRANSPORT = None
