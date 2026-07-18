#!/usr/bin/env python3
"""Global workspace rebrand script — legacy name -> The Sterling Syndicate."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SKIP_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    "dist",
    "build",
    ".vite",
    "coverage",
    "htmlcov",
    ".nyc_output",
    "postgres_data",
    "chroma_db",
    ".idea",
    ".vscode",
}

TEXT_SUFFIXES = {
    ".md", ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json",
    ".yml", ".yaml", ".toml", ".txt", ".html", ".htm", ".css", ".scss",
    ".env", ".example", ".ps1", ".bat", ".cmd", ".sh", ".ini", ".cfg",
    ".conf", ".sql", ".rst", ".svg", ".xml", ".dockerignore", ".gitignore",
    ".editorconfig", ".npmrc",
}

TEXT_NAMES = {
    "Dockerfile", "Makefile", "LICENSE", "README", "Procfile",
    ".env", ".env.example", ".gitignore", ".dockerignore",
    "docker-compose.yml", "docker-compose.yaml", "package.json",
    "package-lock.json", "requirements.txt", "alembic.ini", "ci.workflow.yml",
}

# Verification needles (legacy brand fragments — not applied as replacements)
_LEGACY_NEEDLES = (
    "The Sterling Syndicate", "sterling-syndicate", "sterlingSyndicate", "The Sterling Syndicate", "the sterling syndicate",
    "sterling-syndicate", "sterling_syndicate", "THE STERLING SYNDICATE", "THE STERLING SYNDICATE", "sterling-syndicate-",
)


def is_text_file(path: Path) -> bool:
    if path.name.startswith(".env") or path.name in TEXT_NAMES:
        return True
    if path.suffix.lower() in TEXT_SUFFIXES:
        return True
    return path.name.lower() in {"dockerfile", "makefile", "license", "readme"}


def should_skip_dir(name: str) -> bool:
    return name in SKIP_DIRS or name.endswith(".egg-info")


def transform(content: str) -> str:
    """User-specified global replacements (longest / most specific first)."""
    out = content
    pairs = [
        # Spaced variants
        ("The Sterling Syndicate", "The Sterling Syndicate"),
        ("the sterling syndicate", "the sterling syndicate"),
        ("THE STERLING SYNDICATE", "THE STERLING SYNDICATE"),
        # Kebab / snake slugs
        ("sterling-syndicate", "sterling-syndicate"),
        ("Sterling-Syndicate", "Sterling-Syndicate"),
        ("STERLING-SYNDICATE", "STERLING-SYNDICATE"),
        ("sterling_syndicate", "sterling_syndicate"),
        ("Sterling_Syndicate", "Sterling_Syndicate"),
        ("STERLING_SYNDICATE", "STERLING_SYNDICATE"),
        # Exact user rules
        ("sterlingSyndicate", "sterlingSyndicate"),
        ("The Sterling Syndicate", "The Sterling Syndicate"),
        ("THE STERLING SYNDICATE", "THE STERLING SYNDICATE"),
        ("sterling-syndicate", "sterling-syndicate"),
        # Legacy docker container naming
        ("sterling-syndicate-db", "sterling-syndicate-db"),
        ("sterling-syndicate-dind", "sterling-syndicate-dind"),
        ("sterling-syndicate-backend", "sterling-syndicate-backend"),
        ("sterling-syndicate-frontend", "sterling-syndicate-frontend"),
        ("sterling-syndicate-db", "sterling-syndicate-db"),
        ("sterling-syndicate-dind", "sterling-syndicate-dind"),
        ("sterling-syndicate-backend", "sterling-syndicate-backend"),
        ("sterling-syndicate-frontend", "sterling-syndicate-frontend"),
    ]
    for old, new in pairs:
        out = out.replace(old, new)
    return out


def main() -> int:
    changed: list[str] = []
    scanned = 0
    errors: list[str] = []
    self_path = Path(__file__).resolve()

    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if not should_skip_dir(d)]
        for fname in filenames:
            path = Path(dirpath) / fname
            if not is_text_file(path):
                continue
            scanned += 1
            try:
                raw = path.read_bytes()
            except OSError as e:
                errors.append(f"read {path}: {e}")
                continue
            if b"\x00" in raw[:4096]:
                continue
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    text = raw.decode("latin-1")
                except Exception as e:
                    errors.append(f"decode {path}: {e}")
                    continue
            new_text = transform(text)
            if new_text != text:
                try:
                    path.write_bytes(new_text.encode("utf-8"))
                    changed.append(str(path.relative_to(ROOT)))
                except OSError as e:
                    errors.append(f"write {path}: {e}")

    print(f"ROOT: {ROOT}")
    print(f"Scanned: {scanned}")
    print(f"Modified: {len(changed)}")
    for rel in changed:
        print(f"  UPDATED: {rel}")
    if errors:
        for e in errors[:20]:
            print(f"  ERR: {e}")
        return 1

    leftovers: list[str] = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if not should_skip_dir(d)]
        for fname in filenames:
            path = Path(dirpath) / fname
            if path.resolve() == self_path:
                continue
            if not is_text_file(path):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for needle in _LEGACY_NEEDLES:
                if needle in text:
                    leftovers.append(f"{path.relative_to(ROOT)} :: {needle!r}")
                    break

    if leftovers:
        print(f"VERIFY FAIL: {len(leftovers)}")
        for line in leftovers[:80]:
            print(f"  {line}")
        return 2

    print("VERIFY OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
