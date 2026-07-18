# Synthetic demo data for public screenshots and local walkthroughs.
# Never put real client information here.

Seed with Postgres running and migrations applied:

```bash
# from repo root, with DATABASE_URL pointing at your DB
cd backend && alembic upgrade head
cd .. && python demo/seed.py
```

Login: see `sample_data.json` → `demo_user`.
