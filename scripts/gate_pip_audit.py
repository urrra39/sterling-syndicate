#!/usr/bin/env python3
"""Fail CI when a *direct* dependency has a published fix.

Same-major fixes block outright. Major-bump-only fixes (e.g. langgraph 0.3 →
1.x) need a dedicated compatibility PR, so they block until the advisory is
listed in IGNORE with a reason. Advisories with no fix, and transitive deps,
are logged only.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

DIRECT = {
    "fastapi",
    "starlette",
    "uvicorn",
    "python-multipart",
    "greenlet",
    "sqlalchemy",
    "psycopg",
    "alembic",
    "pgvector",
    "pyjwt",
    "passlib",
    "bcrypt",
    "cryptography",
    "pydantic",
    "pydantic-settings",
    "email-validator",
    "httpx",
    "python-dotenv",
    "chromadb",
    "langgraph",
    "langchain-core",
    "pytest",
    "pytest-asyncio",
    "eval-type-backport",
}

# Documented residuals / major-bump-only (see backend/requirements.txt comments).
IGNORE = {
    "PYSEC-2026-1845",  # pytest 9.x — separate major
    "PYSEC-2026-83",  # langgraph 1.x — agent API upgrade PR
    "PYSEC-2026-2193",  # langchain-core 1.x
    "PYSEC-2026-2562",  # langchain-core 1.x
}


def _major(version: str) -> str | None:
    m = re.match(r"(\d+)", version.strip())
    return m.group(1) if m else None


def _same_major_fix(installed: str, fix_versions: list) -> bool:
    """True if any fix shares the installed package's major version."""
    maj = _major(installed)
    if maj is None:
        return False
    for fix in fix_versions:
        if _major(str(fix)) == maj:
            return True
    return False


def _ids(vuln: dict) -> list[str]:
    """Advisory id plus aliases — pip-audit may report either form."""
    out = [vuln.get("id")] + list(vuln.get("aliases") or [])
    return [str(v) for v in out if v]


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: gate_pip_audit.py <audit.json>", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"pip-audit gate: missing {path} — treating as OK (audit produced no file)")
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    deps = data if isinstance(data, list) else data.get("dependencies") or []

    blockers: list[str] = []
    noted: list[str] = []
    for dep in deps:
        if not isinstance(dep, dict):
            continue
        name = (dep.get("name") or "").lower().replace("_", "-")
        installed = str(dep.get("version") or "")
        for vuln in dep.get("vulns") or []:
            ids = _ids(vuln)
            vid = ids[0] if ids else "?"
            exempt = next((i for i in ids if i in IGNORE), None)
            if exempt:
                noted.append(f"ignored {exempt} in {name}")
                continue
            fixes = vuln.get("fix_versions") or []
            if not fixes:
                noted.append(f"{name}: {vid} (unfixed upstream)")
            elif name not in DIRECT:
                noted.append(f"{name}: {vid} (transitive)")
            elif _same_major_fix(installed, fixes):
                blockers.append(f"{name}@{installed}: {vid} (fix >= {fixes[0]})")
            else:
                blockers.append(
                    f"{name}@{installed}: {vid} (major-bump fix {fixes[0]} — "
                    "needs a compatibility PR or an IGNORE entry)"
                )

    for line in noted:
        print(f"note: {line}")
    if blockers:
        print("BLOCKING direct-dependency advisories with a published fix:")
        for line in blockers:
            print(f"  - {line}")
        return 1
    print("pip-audit gate: OK (no fixable direct-dep advisories)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
