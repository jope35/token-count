import subprocess
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TestUvProject(unittest.TestCase):
    def test_pyproject_and_lock_exist(self):
        self.assertTrue((ROOT / "pyproject.toml").is_file())
        self.assertTrue((ROOT / "uv.lock").is_file())

    def test_lock_is_up_to_date(self):
        result = subprocess.run(
            ["uv", "lock", "--check"], cwd=ROOT, capture_output=True, text=True
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_pyproject_declares_all_deps_in_one_env(self):
        data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        deps = data["project"]["dependencies"]
        for pkg in ["httpx", "tenacity", "tiktoken", "tokenizers"]:
            self.assertTrue(any(d.startswith(pkg) for d in deps), deps)
        self.assertNotIn("secretspec", " ".join(deps))
        self.assertNotIn("dependency-groups", data)

    def test_devenv_and_secretspec_files_removed(self):
        for name in [
            "devenv.nix",
            "devenv.yaml",
            "devenv.lock",
            "secretspec.toml",
            ".sops.yaml",
            "secrets.enc.yaml",
        ]:
            self.assertFalse((ROOT / name).exists(), name)

    def test_gitignore(self):
        lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        for needle in [".venv*", "__pycache__", "samples/", ".env"]:
            self.assertIn(needle, lines)


class TestDotenvExample(unittest.TestCase):
    def test_env_example_lists_five_keys_and_env_stays_ignored(self):
        text = (ROOT / ".env.example").read_text(encoding="utf-8")
        for key in [
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "GOOGLE_API_KEY",
            "Z_AI_API_KEY",
            "MOONSHOT_API_KEY",
        ]:
            self.assertIn(key, text)
        lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn(".env", lines)
        self.assertNotIn(".env.example", lines)


class TestReadme(unittest.TestCase):
    def test_readme_documents_setup_and_run(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        for needle in [
            "uv sync",
            "uv.lock",
            "PYTHONPATH=src .venv/bin/python -m tokencount",
            "fetch_corpus(load_entries())",
            ".env.example",
            "OPENAI_API_KEY",
        ]:
            self.assertIn(needle, text)
