"""Dependency-light text embeddings via the hashing trick.

Real embedding models (sentence-transformers, an API embeddings endpoint,
etc.) need either a network call or a multi-hundred-MB local model. To keep
MyRuflo installable with just `anthropic` + `numpy`, we hash tokens into a
fixed-size bag-of-words vector and L2-normalize it. This is good enough for
"has this agent seen something like this before" recall over a local
memory store — swap in a real embedding model behind this same function
signature if you need stronger semantic recall.
"""
from __future__ import annotations

import hashlib
import re

import numpy as np

DIM = 256
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def embed(text: str, dim: int = DIM) -> np.ndarray:
    vector = np.zeros(dim, dtype=np.float32)
    for token in _tokenize(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest, "big") % dim
        sign = 1.0 if digest[0] % 2 == 0 else -1.0
        vector[index] += sign
    norm = np.linalg.norm(vector)
    if norm > 0:
        vector /= norm
    return vector


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)
