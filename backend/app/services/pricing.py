from __future__ import annotations

"""Dynamic bid pricing from complexity + market heuristics.

bid = clamp(base_hourly * estimated_hours * complexity * scarcity, min, max)
"""

import math
import re
from dataclasses import dataclass
from typing import List, Optional

from app.core.config import settings

COMPLEXITY_KEYWORDS = {
    "simple": ["landing page", "bug fix", "small change", "quick", "one page"],
    "medium": ["api", "dashboard", "integration", "crud", "mvp", "react", "fastapi"],
    "complex": [
        "microservice",
        "distributed",
        "realtime",
        "machine learning",
        "ml",
        "kubernetes",
        "security audit",
        "migration",
        "scale",
        "enterprise",
    ],
}


@dataclass(frozen=True)
class PriceQuote:
    recommended_bid: float
    currency: str
    estimated_hours: float
    complexity: float
    scarcity: float
    rationale: str


def estimate_complexity(text: str) -> float:
    t = text.lower()
    score = 1.0
    if any(k in t for k in COMPLEXITY_KEYWORDS["complex"]):
        score += 0.55
    if any(k in t for k in COMPLEXITY_KEYWORDS["medium"]):
        score += 0.25
    if any(k in t for k in COMPLEXITY_KEYWORDS["simple"]):
        score -= 0.2
    # Length proxy for scope
    words = len(re.findall(r"\w+", t))
    score += min(0.35, words / 2000.0)
    return max(0.7, min(2.2, score))


def estimate_hours(text: str, complexity: float) -> float:
    t = text.lower()
    # Explicit week mentions
    weeks = re.search(r"(\d+)\s*-\s*(\d+)\s*weeks?", t) or re.search(r"(\d+)\s*weeks?", t)
    if weeks:
        if weeks.lastindex == 2:
            w = (float(weeks.group(1)) + float(weeks.group(2))) / 2.0
        else:
            w = float(weeks.group(1))
        return max(8.0, w * 20.0 * (0.7 + 0.3 * complexity))
    hours = re.search(r"(\d+)\s*hrs?(?:/| per )?week", t)
    if hours:
        return max(8.0, float(hours.group(1)) * 4.0)
    # Default from complexity
    return round(12.0 * complexity, 1)


def estimate_scarcity(skills: List[str], text: str) -> float:
    """Higher when job asks for rare skills the freelancer has."""
    t = text.lower()
    if not skills:
        return 1.0
    hits = sum(1 for s in skills if s.lower() in t)
    return 1.0 + min(0.4, hits * 0.08)


def recommend_bid(text: str, skills: Optional[List[str]] = None) -> PriceQuote:
    skills = skills or []
    complexity = estimate_complexity(text)
    hours = estimate_hours(text, complexity)
    scarcity = estimate_scarcity(skills, text)
    raw = settings.base_hourly_rate * hours * complexity * scarcity
    # Mild log dampening for huge scopes
    dampened = raw if raw < 5000 else 5000 + math.log1p(raw - 5000) * 400
    bid = max(settings.min_bid, min(settings.max_bid, round(dampened, -1)))  # nearest $10
    rationale = (
        f"base=${settings.base_hourly_rate}/hr × {hours:.0f}h × complexity {complexity:.2f} "
        f"× scarcity {scarcity:.2f} → ${bid:.0f}"
    )
    return PriceQuote(
        recommended_bid=float(bid),
        currency="USD",
        estimated_hours=hours,
        complexity=complexity,
        scarcity=scarcity,
        rationale=rationale,
    )
