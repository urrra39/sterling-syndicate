"""Load synthetic demo data. Usage: python -m demo.seed (from repo root with DATABASE_URL set)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow running as script with backend on path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models.lead import Lead  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.matching import embed_text, match_score  # noqa: E402


def main() -> None:
    data = json.loads((Path(__file__).parent / "sample_data.json").read_text(encoding="utf-8"))
    demo = data["demo_user"]
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == demo["email"]))
        if user is None:
            portfolio = f"{demo['name']}\nSkills: {', '.join(demo['skills'])}\n{demo['portfolio_summary']}"
            user = User(
                name=demo["name"],
                email=demo["email"],
                password_hash=hash_password(demo["password"]),
                skills=demo["skills"],
                portfolio_summary=demo["portfolio_summary"],
                portfolio_embedding=embed_text(portfolio),
            )
            db.add(user)
            db.flush()
            print(f"Created demo user {demo['email']} / {demo['password']}")
        else:
            print(f"Demo user already exists: {demo['email']}")

        portfolio = f"{user.name}\nSkills: {', '.join(user.skills or [])}\n{user.portfolio_summary or ''}"
        existing_titles = {l.title for l in db.scalars(select(Lead).where(Lead.user_id == user.id)).all()}
        for item in data["leads"]:
            if item["title"] in existing_titles:
                continue
            db.add(
                Lead(
                    user_id=user.id,
                    source=item["source"],
                    title=item["title"],
                    raw_text=item["raw_text"],
                    category=item.get("category"),
                    embedding=embed_text(item["raw_text"]),
                    match_score=match_score(portfolio, item["raw_text"]),
                    pipeline_status=item.get("pipeline_status", "new"),
                )
            )
        db.commit()
        print("Demo leads seeded.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
