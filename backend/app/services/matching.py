from __future__ import annotations

"""Deterministic hashing embedder + cosine similarity.

ponytail: hashing embedder (no torch). Swap to MiniLM via EMBEDDING_BACKEND=minilm
when you need semantic quality and can install sentence-transformers.
"""

import hashlib
import math
import re
from typing import List, Sequence

EMBEDDING_DIM = 384
_TOKEN_RE = re.compile(r"[a-z0-9+#.]{2,}", re.I)


def tokenize(text: str) -> List[str]:
    return _TOKEN_RE.findall(text.lower())


def embed_text(text: str, dim: int = EMBEDDING_DIM) -> List[float]:
    """Hashing trick embedding — stable, offline, no model download."""
    vec = [0.0] * dim
    tokens = tokenize(text)
    if not tokens:
        return vec
    for tok in tokens:
        h = hashlib.sha256(tok.encode("utf-8")).digest()
        idx = int.from_bytes(h[:4], "big") % dim
        sign = 1.0 if h[4] % 2 == 0 else -1.0
        vec[idx] += sign
    # L2 normalize
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (na * nb)))


def match_score(portfolio_text: str, lead_text: str) -> float:
    """Embed both sides and return cosine similarity clamped to [0, 1]."""
    score = cosine_similarity(embed_text(portfolio_text), embed_text(lead_text))
    # Clamp negatives to 0 rather than linearly stretching [-1,1]→[0,1]: this
    # hashing embedder assigns random signs, so meaningful matches are
    # non-negative. Stretching gave unrelated/empty text a spurious 0.5 baseline,
    # making every absolute threshold (scout's `score < 0.5`) meaningless.
    return round(max(0.0, score), 4)
