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

    def test_http_error_raises(self):
        def handler(request):
            return httpx.Response(404)
        with tempfile.TemporaryDirectory() as td, _patch_client(handler):
            with self.assertRaises(httpx.HTTPStatusError):
                fetch_corpus([ENTRY], dest_dir=td)

    def test_make_client_sends_descriptive_user_agent(self):
        # Wikipedia 403s the default python-httpx UA; a live fetch needs a
        # descriptive one.
        from tokencount.corpus import _make_client
        client = _make_client()
        try:
            ua = client.headers.get("user-agent", "")
        finally:
            client.close()
        self.assertNotIn("python-httpx", ua)
        self.assertIn("token-count", ua)


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
