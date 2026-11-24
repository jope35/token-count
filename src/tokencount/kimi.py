import json
import os

import tiktoken
from tiktoken.load import load_tiktoken_bpe

# Identical across all four Kimi repos (verified 2026-11-24); from each repo's
# tokenization_kimi.py.
PAT_STR = "|".join([
    r"""[\p{Han}]+""",
    r"""[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}&&[^\p{Han}]]*[\p{Ll}\p{Lm}\p{Lo}\p{M}&&[^\p{Han}]]+(?i:'s|'t|'re|'ve|'m|'ll|'d)?""",
    r"""[^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}&&[^\p{Han}]]+[\p{Ll}\p{Lm}\p{Lo}\p{M}&&[^\p{Han}]]*(?i:'s|'t|'re|'ve|'m|'ll|'d)?""",
    r"""\p{N}{1,3}""",
    r""" ?[^\s\p{L}\p{N}]+[\r\n]*""",
    r"""\s*[\r\n]+""",
    r"""\s+(?!\S)""",
    r"""\s+""",
])

# tiktoken panics above this many chars per encode() call; the repos' own
# wrappers chunk at the same limit.
CHUNK_CHARS = 400_000


def load_encoding(tokenizer_dir: str) -> tiktoken.Encoding:
    ranks = load_tiktoken_bpe(os.path.join(tokenizer_dir, "tiktoken.model"))
    num_base = len(ranks)
    with open(
        os.path.join(tokenizer_dir, "tokenizer_config.json"), encoding="utf-8"
    ) as f:
        config = json.load(f)
    added = config.get("added_tokens_decoder", {})
    # Full reserved range [num_base, num_base + 256): every id is tiktoken-
    # special even when the config flags it special: false (e.g. K3's
    # <|open|> <|close|> <|sep|>), matching the repos' tokenization_kimi.py.
    special_tokens = {
        added[str(i)]["content"] if str(i) in added else f"<|reserved_token_{i}|>": i
        for i in range(num_base, num_base + 256)
    }
    return tiktoken.Encoding(
        name=os.path.basename(os.path.normpath(tokenizer_dir)),
        pat_str=PAT_STR,
        mergeable_ranks=ranks,
        special_tokens=special_tokens,
    )


def count(enc: tiktoken.Encoding, text: str) -> int:
    total = 0
    for start in range(0, len(text), CHUNK_CHARS):
        total += len(enc.encode(text[start : start + CHUNK_CHARS], allowed_special="all"))
    return total
