import argparse
import csv
import os
import subprocess
from datetime import datetime, timezone

from tokencount import counters
from tokencount.corpus import CorpusEntry, Sample, fetch_corpus, load_entries
from tokencount.models import REGISTRY, models_for_family

CSV_COLUMNS = ["timestamp", "provider", "model", "strategy", "file", "file_type", "sha256", "chars", "tokens", "note"]
RESULTS_CSV = "results/results.csv"

SECRET_KEYS = sorted({m.key_env for m in REGISTRY})


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
            if _is_numeric(row["tokens"]) or note == "n/a" or note.startswith("missing key "):
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
        tokens = counters.count_tokens(model.strategy, model.model, sample.text, key=key)
        return str(tokens), ""
    except counters.MissingKeyError as e:
        return "", f"missing key {e.env}"
    except counters.UnsupportedModelError:
        return "", "n/a"
    except Exception as e:
        return "", f"error: {e}"


def run_worker(family: str, fresh: bool = False, results_csv: str = None) -> int:
    csv_path = results_csv or RESULTS_CSV
    samples = fetch_corpus(load_entries(), fresh=fresh)
    deduped = set() if fresh else read_dedup_keys(csv_path)
    key = os.environ.get(models_for_family(family)[0].key_env)
    for model in models_for_family(family):
        for sample in samples:
            if (model.model, model.strategy, sample.path, sample.sha256) in deduped:
                continue
            tokens, note = count_sample(model, sample, key)
            append_row(csv_path, {
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
            })
    return 0


def render_results() -> None:
    # PLAN C HOOK: table.py implements this
    return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="tokencount")
    parser.add_argument("--family")
    parser.add_argument("--fresh", action="store_true")
    args = parser.parse_args(argv)

    if args.family:
        return run_worker(args.family, fresh=args.fresh)

    secrets = resolve_secrets()
    fetch_corpus(load_entries(), fresh=args.fresh)
    families = sorted({m.family for m in REGISTRY})
    returncodes = []
    for family in families:
        cmd = [f"{route_env(family)}/bin/python", "-m", "tokencount", "--family", family]
        if args.fresh:
            cmd.append("--fresh")
        proc = subprocess.run(cmd, env=family_env(family, secrets), check=False)
        returncodes.append(proc.returncode)
    render_results()
    return 0 if all(rc == 0 for rc in returncodes) else 1
