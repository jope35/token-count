import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

import httpx
from tqdm import tqdm

REPO_ROOT = Path(__file__).resolve().parents[2]
EU_MEMBERS_FILE = REPO_ROOT / "corpus" / "eu-members.txt"
REPOS_FILE = REPO_ROOT / "corpus" / "repos.txt"


@dataclass
class CorpusEntry:
    file_type: str
    name: str
    url: str
    repo: str | None
    sha: str | None
    path: str | None


@dataclass
class Sample:
    path: str
    file_type: str
    name: str
    sha256: str
    chars: int
    text: str


def parse_entries(
    members_path=EU_MEMBERS_FILE, repos_path=REPOS_FILE
) -> list[CorpusEntry]:
    entries: list[CorpusEntry] = []
    for line in Path(members_path).read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) == 3:
            file_type, name, url = parts
            entries.append(CorpusEntry(file_type, name, url, None, None, None))
        else:
            raise ValueError(f"member line must have 3 fields: {line!r}")
    for line in Path(repos_path).read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) == 5:
            file_type, name, repo, sha, path = parts
            url = f"https://raw.githubusercontent.com/{repo}/{sha}/{path}"
            entries.append(CorpusEntry(file_type, name, url, repo, sha, path))
        else:
            raise ValueError(f"repo line must have 5 fields: {line!r}")
    return entries


def load_entries() -> list[CorpusEntry]:
    return parse_entries()


def _make_client() -> httpx.Client:
    # Wikipedia and other sites 403 the default python-httpx user agent.
    return httpx.Client(
        timeout=30.0,
        follow_redirects=True,
        headers={
            "User-Agent": "token-count/0.1 (+https://github.com/jope35/token-count)"
        },
    )


def fetch_corpus(
    entries: list[CorpusEntry], dest_dir="samples", fresh=False, show_progress=True
) -> list[Sample]:
    client = _make_client()
    samples: list[Sample] = []
    for entry in (tqdm(entries, desc="corpus", unit="file") if show_progress else entries):
        dest = Path(dest_dir) / entry.file_type / entry.name
        if dest.exists() and not fresh:
            data = dest.read_bytes()
        else:
            response = client.get(entry.url)
            response.raise_for_status()
            data = response.content
            dest.parent.mkdir(parents=True, exist_ok=True)
            part = dest.with_name(dest.name + ".part")
            part.write_bytes(data)
            os.replace(part, dest)
        text = data.decode("utf-8")
        samples.append(
            Sample(
                str(dest),
                entry.file_type,
                entry.name,
                hashlib.sha256(data).hexdigest(),
                len(text),
                text,
            )
        )
    return samples
