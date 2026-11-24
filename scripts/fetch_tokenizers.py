"""Vendor the HF-format tokenizer files for the hf_local models.

Holds the pinned repo/revision/file table as data. Run once when the registry
changes: .venv/bin/python scripts/fetch_tokenizers.py
Stdlib only; no huggingface-hub. Mistral repos also ship tekken.json
(mistral-common format, not loadable by the tokenizers library), so we vendor
their HF-format tokenizer.json at the same pinned revision.
"""

import hashlib
import json
import os
import urllib.request

# local name, HF repo, pinned revision sha, HF file
TOKENIZERS = [
    (
        "deepseek-flash",
        "deepseek-ai/DeepSeek-V4.1-Flash-1017",
        "08c8657f02291e11b6f6b63e0e16014f8e748518",
        "tokenizer.json",
    ),
    (
        "deepseek-v4-pro",
        "deepseek-ai/DeepSeek-V4-Pro-0813",
        "72e1d3230f6c080a530b0a1d46f8eb4602340597",
        "tokenizer.json",
    ),
    (
        "mistral-large-4",
        "mistralai/Mistral-Large-4-1T-A52B",
        "af26e7869af601441d5cdf75a1272469ddc3d059",
        "tokenizer.json",
    ),
    (
        "mistral-small-2603",
        "mistralai/Mistral-Small-4-119B-2603",
        "a11f36bebf709121056b1dbcc943d1c6afbe494d",
        "tokenizer.json",
    ),
    (
        "mistral-medium-3-5",
        "mistralai/Mistral-Medium-3.5-128B",
        "22b2b868a15677cfa6061277ed2f653d1349a9ab",
        "tokenizer.json",
    ),
]


def main() -> None:
    out_dir = os.path.join(os.path.dirname(__file__), "..", "tokenizers")
    os.makedirs(out_dir, exist_ok=True)
    for local_name, repo, sha, hf_file in TOKENIZERS:
        url = f"https://huggingface.co/{repo}/resolve/{sha}/{hf_file}"
        with urllib.request.urlopen(url) as response:
            data = response.read()
        json.loads(data)  # must be valid JSON
        path = os.path.join(out_dir, f"{local_name}.json")
        with open(path, "wb") as f:
            f.write(data)
        print(path, len(data), hashlib.sha256(data).hexdigest())


if __name__ == "__main__":
    main()
