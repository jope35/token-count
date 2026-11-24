import argparse
import csv
import os
import shutil
import subprocess
from subprocess import TimeoutExpired
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import partial

from tqdm import tqdm

from tokencount import counters, table
from tokencount.corpus import fetch_corpus, load_entries
from tokencount.models import REGISTRY, models_for_family

CSV_COLUMNS = [
    "timestamp",
    "provider",
    "model",
    "strategy",
    "file",
    "file_type",
    "sha256",
    "chars",
    "tokens",
    "note",
]
RESULTS_CSV = "results/results.csv"
PENDING_DIR = "results/pending/"
API_CONCURRENCY = 4

SECRET_KEYS = sorted({m.key_env for m in REGISTRY if m.key_env})


def route_env(family: str) -> str:
    return ".venv"


def family_env(family: str, secrets: dict) -> dict:
    env = {"PYTHONPATH": "src"}
    key_env = models_for_family(family)[0].key_env
    if key_env in secrets:
        env[key_env] = secrets[key_env]
    return env


def _parse_dotenv(path: str) -> dict:
    values = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise ValueError(f"malformed line in {path}: {line!r}")
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            values[key] = value
    return values


def resolve_secrets(dotenv_path: str = ".env") -> dict:
    dotenv = _parse_dotenv(dotenv_path) if os.path.exists(dotenv_path) else {}
    secrets = {}
    for key in SECRET_KEYS:
        value = os.environ.get(key, dotenv.get(key))
        if value is not None:
            secrets[key] = value
    return secrets


def _is_numeric(tokens: str) -> bool:
    try:
        int(tokens)
        return True
    except ValueError:
        return False


def read_dedup_keys(csv_path: str) -> set:
    keys = set()
    if not os.path.exists(csv_path):
        return keys
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            if any(row.get(col) is None for col in CSV_COLUMNS):
                continue  # torn trailing line from a killed process
            note = row["note"]
            if (
                _is_numeric(row["tokens"])
                or note == "n/a"
                or note.startswith("missing key ")
            ):
                keys.add((row["model"], row["strategy"], row["file"], row["sha256"]))
    return keys


def append_row(csv_path: str, row: dict) -> None:
    dirname = os.path.dirname(csv_path)
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    new_file = not os.path.exists(csv_path)
    with open(csv_path, "a", newline="") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(CSV_COLUMNS)
        writer.writerow([row[col] for col in CSV_COLUMNS])


def count_sample(model, sample, key) -> tuple:
    try:
        tokens = counters.count_tokens(
            model.strategy,
            model.model,
            sample.text,
            key=key,
            tokenizer_file=model.tokenizer_file,
        )
        return str(tokens), ""
    except counters.MissingKeyError as e:
        return "", f"missing key {e.env}"
    except counters.UnsupportedModelError:
        return "", "n/a"
    except Exception as e:
        return "", f"error: {e}"


def _count_one(item, key) -> dict:
    model, sample = item
    tokens, note = count_sample(model, sample, key)
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provider": model.provider,
        "model": model.model,
        "strategy": model.strategy,
        "file": sample.path,
        "file_type": sample.file_type,
        "sha256": sample.sha256,
        "chars": str(sample.chars),
        "tokens": tokens,
        "note": note,
    }


def run_worker(
    family: str, fresh: bool = False, results_csv: str = None, bar_position: int = 0
) -> int:
    csv_path = results_csv or RESULTS_CSV
    samples = fetch_corpus(load_entries(), fresh=fresh, show_progress=False)
    # dedup reads the main results.csv, not the pending write target
    deduped = set() if fresh else read_dedup_keys(RESULTS_CSV)
    models = models_for_family(family)
    key = os.environ.get(models[0].key_env) if models[0].key_env else None
    items = [
        (model, sample)
        for model in models
        for sample in samples
        if (model.model, model.strategy, sample.path, sample.sha256) not in deduped
    ]
    bar = dict(desc=family, unit="pair", position=bar_position, leave=True, disable=None)
    if models[0].strategy == "hf_local":
        for item in tqdm(items, **bar):
            append_row(csv_path, _count_one(item, key))
    else:
        # only the main thread appends rows, so append_row needs no lock
        with ThreadPoolExecutor(max_workers=API_CONCURRENCY) as pool:
            for row in tqdm(pool.map(partial(_count_one, key=key), items), **bar):
                append_row(csv_path, row)
    return 0


def split_families(families) -> tuple[list, list]:
    api_families = []
    local_families = []
    for family in families:
        # all models of a family share a strategy
        if models_for_family(family)[0].strategy == "hf_local":
            local_families.append(family)
        else:
            api_families.append(family)
    return api_families, local_families


def aggregate_results(pending_dir=PENDING_DIR, csv_path=RESULTS_CSV) -> int:
    count = 0
    if os.path.isdir(pending_dir):
        for name in sorted(os.listdir(pending_dir)):
            if not name.endswith(".csv"):
                continue
            with open(os.path.join(pending_dir, name), newline="") as f:
                for row in csv.DictReader(f):
                    if any(row.get(col) is None for col in CSV_COLUMNS):
                        continue  # torn trailing line from a killed process
                    append_row(csv_path, row)
                    count += 1
    if os.path.exists(pending_dir):
        shutil.rmtree(pending_dir)
    return count


def render_results() -> None:
    table.write_table()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="tokencount")
    parser.add_argument("--family")
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--results-csv", default=None)
    parser.add_argument("--bar-position", type=int, default=0)
    args = parser.parse_args(argv)

    if args.family:
        return run_worker(
            args.family,
            fresh=args.fresh,
            results_csv=args.results_csv,
            bar_position=args.bar_position,
        )

    secrets = resolve_secrets()
    shutil.rmtree(PENDING_DIR, ignore_errors=True)  # wipe stale pending rows
    fetch_corpus(load_entries(), fresh=args.fresh)
    families = sorted({m.family for m in REGISTRY})
    api_families, local_families = split_families(families)
    returncodes = []
    procs = []
    for i, family in enumerate(api_families):
        cmd = [
            f"{route_env(family)}/bin/python",
            "-m",
            "tokencount",
            "--family",
            family,
            "--bar-position",
            str(i),
            "--results-csv",
            os.path.join(PENDING_DIR, f"{family}.csv"),
        ]
        if args.fresh:
            cmd.append("--fresh")
        procs.append(subprocess.Popen(cmd, env=family_env(family, secrets)))
    try:
        for proc in procs:
            returncodes.append(proc.wait())
    except KeyboardInterrupt:
        for proc in procs:
            if proc.poll() is None:
                proc.terminate()
        for proc in procs:
            try:
                proc.wait(timeout=5)
            except TimeoutExpired:
                proc.kill()
                proc.wait()
            except KeyboardInterrupt:
                pass  # a second Ctrl-C while reaping must not escape the handler
        return 1  # no aggregation, no render; results/results.csv untouched
    for family in local_families:
        cmd = [
            f"{route_env(family)}/bin/python",
            "-m",
            "tokencount",
            "--family",
            family,
            "--bar-position",
            "0",
            "--results-csv",
            os.path.join(PENDING_DIR, f"{family}.csv"),
        ]
        if args.fresh:
            cmd.append("--fresh")
        proc = subprocess.run(cmd, env=family_env(family, secrets), check=False)
        returncodes.append(proc.returncode)
    aggregate_results(PENDING_DIR, RESULTS_CSV)
    render_results()
    return 0 if all(rc == 0 for rc in returncodes) else 1
