import csv
import os

from tokencount.corpus import load_entries
from tokencount.models import REGISTRY


def dedup_key(row: dict) -> tuple:
    return (row["model"], row["strategy"], row["file"], row["sha256"])


def _note_rank(note: str) -> int:
    if note.startswith("error:"):
        return 0
    if note.startswith("missing key"):
        return 1
    return 2


def _latest_rows(rows: list) -> list:
    # results.csv is append-only and chronological: for a given
    # (model, strategy, file) only the newest row counts, so a rerun against
    # a re-downloaded corpus replaces the stale-sha rows instead of stacking.
    latest = {}
    for row in rows:
        key = (row["model"], row["strategy"], row["file"])
        if key not in latest or row["timestamp"] >= latest[key]["timestamp"]:
            latest[key] = row
    return list(latest.values())


def pivot(rows: list, models: list = None, file_types: list = None) -> tuple:
    if models is None:
        models = [m.model for m in REGISTRY]
    if file_types is None:
        file_types = []
        for entry in load_entries():
            if entry.file_type not in file_types:
                file_types.append(entry.file_type)
    sums = {m: {} for m in models}
    notes = {m: {} for m in models}
    for row in _latest_rows(rows):
        model, file_type = row["model"], row["file_type"]
        if model not in sums or file_type not in file_types:
            continue
        try:
            sums[model][file_type] = sums[model].get(file_type, 0) + int(row["tokens"])
        except (ValueError, TypeError):
            pass
        if row["note"]:
            cell_notes = notes[model].setdefault(file_type, [])
            cell_notes.append(row["note"])
    cells = {m: {} for m in models}
    for m in models:
        for file_type in file_types:
            if notes[m].get(file_type):
                cells[m][file_type] = min(notes[m][file_type], key=_note_rank)
            elif file_type in sums[m]:
                cells[m][file_type] = sums[m][file_type]
    return file_types, cells


def _render_note(note: str) -> str:
    if note.startswith("error:"):
        return "error"
    if note.startswith("missing key"):
        return "key"
    return "n/a"


def render_markdown(pivot_result: tuple) -> str:
    file_types, cells = pivot_result
    lines = [
        "| model | " + " | ".join(file_types) + " | Total |",
        "|" + "---|" * (len(file_types) + 2),
    ]
    for model, model_cells in cells.items():
        values = []
        total = 0
        for file_type in file_types:
            value = model_cells.get(file_type, "n/a")
            if isinstance(value, int):
                values.append(str(value))
                total += value
            else:
                values.append(_render_note(value))
        values.append(str(total))
        lines.append("| " + model + " | " + " | ".join(values) + " |")
    return "\n".join(lines) + "\n"


def write_table(csv_path: str = "results/results.csv", out_path: str = "results/table.md") -> str:
    rows = []
    if os.path.exists(csv_path):
        with open(csv_path, newline="") as f:
            for row in csv.DictReader(f):
                if None in row or any(v is None for v in row.values()):
                    continue  # torn trailing line from a killed process
                rows.append(row)
    markdown = render_markdown(pivot(rows))
    dirname = os.path.dirname(out_path)
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(markdown)
    print(markdown)
    return markdown
