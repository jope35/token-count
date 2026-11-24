import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EU = [
    "Austria",
    "Belgium",
    "Bulgaria",
    "Croatia",
    "Cyprus",
    "Czechia",
    "Denmark",
    "Estonia",
    "Finland",
    "France",
    "Germany",
    "Greece",
    "Hungary",
    "Ireland",
    "Italy",
    "Latvia",
    "Lithuania",
    "Luxembourg",
    "Malta",
    "Netherlands",
    "Poland",
    "Portugal",
    "Romania",
    "Slovakia",
    "Slovenia",
    "Spain",
    "Sweden",
]


class TestEuMembers(unittest.TestCase):
    def test_27_wikipedia_entries(self):
        lines = (
            (ROOT / "corpus" / "eu-members.txt")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        self.assertEqual(27, len(lines))
        for line, country in zip(lines, EU):
            self.assertEqual(
                f"text {country} https://en.wikipedia.org/wiki/{country}", line
            )


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
