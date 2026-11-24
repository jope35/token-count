import csv
import os
import tempfile
import unittest

from tokencount import table


def make_row(
    model="m",
    strategy="s",
    file="samples/python/public-apis",
    file_type="python",
    sha256="abc",
    tokens="",
    note="",
    timestamp="2026-11-24T00:00:00+00:00",
):
    return {
        "timestamp": timestamp,
        "provider": "p",
        "model": model,
        "strategy": strategy,
        "file": file,
        "file_type": file_type,
        "sha256": sha256,
        "chars": "5",
        "tokens": tokens,
        "note": note,
    }


def sample_rows():
    return [
        make_row(file="samples/python/a", tokens="10"),
        make_row(file="samples/python/b", tokens="5"),
        make_row(file="samples/json/x", file_type="json", note="error: boom"),
        make_row(file="samples/html/y", file_type="html", note="n/a"),
        make_row(
            file="samples/text/France",
            file_type="text",
            note="missing key OPENAI_API_KEY",
        ),
    ]


FILE_TYPES = ["python", "json", "html", "text"]


class TestPivot(unittest.TestCase):
    def test_pivot_sums_numeric_and_carries_notes(self):
        file_types, cells = table.pivot(sample_rows(), models=["m"], file_types=FILE_TYPES)
        self.assertEqual(file_types, FILE_TYPES)
        self.assertEqual(cells["m"]["python"], 15)
        self.assertEqual(cells["m"]["json"], "error: boom")
        self.assertEqual(cells["m"]["html"], "n/a")
        self.assertEqual(cells["m"]["text"], "missing key OPENAI_API_KEY")
        self.assertNotIn("rust", cells["m"])

    def test_mixed_numeric_and_note_cell_precedence(self):
        rows = [
            make_row(file="samples/python/a", tokens="10"),
            make_row(file="samples/python/b", tokens="5"),
            make_row(file="samples/python/old", sha256="stale", note="error: boom"),
            make_row(file="samples/json/x", file_type="json", note="n/a"),
            make_row(
                file="samples/json/y",
                file_type="json",
                note="missing key OPENAI_API_KEY",
            ),
        ]
        _, cells = table.pivot(rows, models=["m"], file_types=FILE_TYPES)
        # error beats missing key beats n/a; a stale error is not averaged away
        self.assertEqual(cells["m"]["python"], "error: boom")
        self.assertEqual(cells["m"]["json"], "missing key OPENAI_API_KEY")

    def test_default_file_types_follow_load_entries_order(self):
        file_types, _ = table.pivot([])
        self.assertEqual(
            file_types, ["text", "python", "javascript", "shell", "rust", "go"]
        )

    def test_only_latest_run_per_file_counts(self):
        rows = [
            make_row(
                file="samples/python/a",
                sha256="old-sha",
                tokens="10",
                timestamp="2026-11-24T00:00:00+00:00",
            ),
            make_row(
                file="samples/python/a",
                sha256="new-sha",
                tokens="7",
                timestamp="2026-11-25T00:00:00+00:00",
            ),
            make_row(file="samples/python/b", tokens="5"),
        ]
        _, cells = table.pivot(rows, models=["m"], file_types=FILE_TYPES)
        # 7 + 5, not 10 + 7 + 5: the stale-sha row is replaced, not stacked
        self.assertEqual(cells["m"]["python"], 12)

    def test_latest_row_wins_even_when_it_is_an_error(self):
        rows = [
            make_row(
                file="samples/python/a",
                sha256="old-sha",
                tokens="10",
                timestamp="2026-11-24T00:00:00+00:00",
            ),
            make_row(
                file="samples/python/a",
                sha256="new-sha",
                note="error: boom",
                timestamp="2026-11-25T00:00:00+00:00",
            ),
        ]
        _, cells = table.pivot(rows, models=["m"], file_types=FILE_TYPES)
        self.assertEqual(cells["m"]["python"], "error: boom")


class TestRenderMarkdown(unittest.TestCase):
    def test_shape_notes_and_total(self):
        pivot = table.pivot(sample_rows(), models=["m", "m2"], file_types=FILE_TYPES)
        md = table.render_markdown(pivot)
        lines = md.splitlines()
        self.assertEqual(lines[0], "| model | python | json | html | text | Total |")
        self.assertEqual(lines[1], "|---|---|---|---|---|---|")
        self.assertEqual(len(lines), 2 + 2)
        self.assertEqual(lines[2], "| m | 15 | error | n/a | key | 15 |")
        # a model with no rows renders n/a cells and Total 0
        self.assertEqual(lines[3], "| m2 | n/a | n/a | n/a | n/a | 0 |")


class TestDedupKey(unittest.TestCase):
    def test_same_key_ignoring_timestamp_and_tokens(self):
        a = make_row(file="samples/text/France", tokens="10")
        b = make_row(file="samples/text/France", tokens="99")
        b["timestamp"] = "2026-11-25T00:00:00+00:00"
        self.assertEqual(table.dedup_key(a), table.dedup_key(b))
        c = make_row(file="samples/python/public-apis")
        self.assertNotEqual(table.dedup_key(a), table.dedup_key(c))
        d = make_row(file="samples/text/France", sha256="other")
        self.assertNotEqual(table.dedup_key(a), table.dedup_key(d))


class TestWriteTable(unittest.TestCase):
    HEADER = "| model | text | python | javascript | shell | rust | go | Total |"

    def write_csv(self, path, rows, torn=None):
        columns = [
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
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(columns)
            for r in rows:
                w.writerow([r[c] for c in columns])
            if torn:
                f.write(torn)

    def test_write_table_skips_torn_trailing_row(self):
        with tempfile.TemporaryDirectory() as d:
            csv_path = os.path.join(d, "results.csv")
            md_path = os.path.join(d, "table.md")
            good = make_row(
                model="mistral-large-4",
                strategy="hf_local",
                file="samples/python/public-apis",
                file_type="python",
                tokens="7",
            )
            self.write_csv(
                csv_path, [good], torn="2026-11-24T00:00:00+00:00,deepseek-flash"
            )
            md = table.write_table(csv_path=csv_path, out_path=md_path)
        self.assertEqual(md.splitlines()[0], self.HEADER)
        row = next(l for l in md.splitlines() if l.startswith("| mistral-large-4 |"))
        self.assertEqual(
            row, "| mistral-large-4 | n/a | 7 | n/a | n/a | n/a | n/a | 7 |"
        )
        # the torn row's model got no cell derived from it
        ds = next(l for l in md.splitlines() if l.startswith("| deepseek-flash |"))
        self.assertTrue(ds.endswith("| 0 |"))

    def test_write_table_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            csv_path = os.path.join(d, "results.csv")
            md_path = os.path.join(d, "table.md")
            good = make_row(
                model="deepseek-flash",
                strategy="hf_local",
                file="samples/text/France",
                file_type="text",
                tokens="42",
            )
            self.write_csv(csv_path, [good])
            md = table.write_table(csv_path=csv_path, out_path=md_path)
            with open(md_path, encoding="utf-8") as f:
                self.assertEqual(md, f.read())
            self.assertEqual(md.splitlines()[0], self.HEADER)
            row = next(l for l in md.splitlines() if l.startswith("| deepseek-flash |"))
            self.assertEqual(
                row, "| deepseek-flash | 42 | n/a | n/a | n/a | n/a | n/a | 42 |"
            )


if __name__ == "__main__":
    unittest.main()
