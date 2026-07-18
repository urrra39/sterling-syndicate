from __future__ import annotations

from app.services.pricing import estimate_complexity, recommend_bid


def test_complex_job_scores_higher() -> None:
    simple = estimate_complexity("Quick bug fix on a landing page")
    hard = estimate_complexity(
        "Build distributed microservices with Kubernetes, realtime ML pipeline, enterprise security audit"
    )
    assert hard > simple


def test_recommend_bid_clamped() -> None:
    q = recommend_bid(
        "Need a FastAPI microservice and React dashboard over 6 weeks",
        skills=["python", "fastapi", "react"],
    )
    assert q.recommended_bid >= 150
    assert q.currency == "USD"
    assert q.estimated_hours > 0
