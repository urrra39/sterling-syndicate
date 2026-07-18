#!/usr/bin/env python3
"""Force Old Money aesthetic: replace blue/teal Tailwind with zinc/amber."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "frontend" / "src"
SKIP = {"node_modules", ".vite", "dist"}

# Exact class-token replacements (word-boundary via regex)
CLASS_MAP = [
    # backgrounds
    (r"\bbg-slate-950\b", "bg-zinc-950"),
    (r"\bbg-slate-900\b", "bg-zinc-900"),
    (r"\bbg-slate-800\b", "bg-zinc-800"),
    (r"\bbg-blue-\d+\b", "bg-zinc-950"),
    (r"\bbg-indigo-\d+\b", "bg-zinc-950"),
    (r"\bbg-sky-\d+\b", "bg-zinc-900"),
    (r"\bbg-cyan-\d+\b", "bg-zinc-900"),
    (r"\bbg-teal-\d+\b", "bg-amber-900/40"),
    (r"\bbg-emerald-\d+\b", "bg-amber-900/40"),
    # text
    (r"\btext-blue-\d+\b", "text-amber-500"),
    (r"\btext-indigo-\d+\b", "text-amber-500"),
    (r"\btext-sky-\d+\b", "text-amber-400"),
    (r"\btext-cyan-\d+\b", "text-amber-400"),
    (r"\btext-teal-\d+\b", "text-amber-500"),
    (r"\btext-emerald-\d+\b", "text-amber-500"),
    (r"\btext-slate-100\b", "text-zinc-100"),
    (r"\btext-slate-200\b", "text-zinc-200"),
    (r"\btext-slate-300\b", "text-zinc-300"),
    (r"\btext-slate-400\b", "text-zinc-400"),
    (r"\btext-slate-500\b", "text-zinc-500"),
    # borders
    (r"\bborder-blue-\d+\b", "border-amber-700"),
    (r"\bborder-indigo-\d+\b", "border-amber-700"),
    (r"\bborder-sky-\d+\b", "border-amber-700/50"),
    (r"\bborder-cyan-\d+\b", "border-amber-700/50"),
    (r"\bborder-teal-\d+\b", "border-amber-700"),
    (r"\bborder-emerald-\d+\b", "border-amber-700"),
    (r"\bborder-slate-700\b", "border-zinc-700"),
    (r"\bborder-slate-800\b", "border-zinc-800"),
    # rings / accents that were teal-ish
    (r"\bring-teal-\d+\b", "ring-amber-600"),
    (r"\bring-cyan-\d+\b", "ring-amber-600"),
    (r"\bring-emerald-\d+\b", "ring-amber-600"),
    # hex fills in charts
    (r"#2dd4bf", "#b45309"),
    (r"#14b8a6", "#b45309"),
    (r"#0d9488", "#92400e"),
    (r"#38bdf8", "#d97706"),
    (r"#0ea5e9", "#d97706"),
    (r"#22d3ee", "#f59e0b"),
]

# Map custom ink-* tokens still used in JSX to zinc equivalents (longest first)
INK_MAP = [
    (r"\bbg-ink-900/50\b", "bg-zinc-950/80"),
    (r"\bbg-ink-900/40\b", "bg-zinc-950/60"),
    (r"\bbg-ink-950/80\b", "bg-zinc-950/80"),
    (r"\bbg-ink-950\b", "bg-zinc-950"),
    (r"\bbg-ink-900\b", "bg-zinc-900"),
    (r"\bbg-ink-800\b", "bg-zinc-800"),
    (r"\bborder-ink-800\b", "border-zinc-800"),
    (r"\bborder-ink-700\b", "border-zinc-700"),
    (r"\bborder-ink-600\b", "border-zinc-600"),
    (r"\btext-ink-950\b", "text-zinc-950"),
]


# Custom accent token (already gold in config) → explicit amber for clarity
ACCENT_MAP = [
    (r"\bbg-accent\b", "bg-zinc-800"),
    (r"\btext-accent\b", "text-amber-500"),
    (r"\bborder-accent\b", "border-amber-700"),
    (r"\bhover:border-accent\b", "hover:border-amber-700"),
    (r"\bhover:border-accent/60\b", "hover:border-amber-700/60"),
    (r"\bring-accent\b", "ring-amber-600"),
]


def transform(text: str) -> str:
    out = text
    for pat, repl in ACCENT_MAP + INK_MAP + CLASS_MAP:
        out = re.sub(pat, repl, out)
    # Ensure h1/h2 with font-display get amber-ish titles when still white
    out = re.sub(
        r'(<(?:h1|h2)[^>]*className="[^"]*font-display[^"]*)\btext-white\b',
        r"\1text-zinc-100",
        out,
    )
    return out


def main() -> int:
    if not ROOT.is_dir():
        print(f"Missing {ROOT}", file=sys.stderr)
        return 1
    changed = []
    for dp, dns, fns in os.walk(ROOT):
        dns[:] = [d for d in dns if d not in SKIP]
        for f in fns:
            if not f.endswith((".tsx", ".ts", ".jsx", ".js", ".css")):
                continue
            path = Path(dp) / f
            raw = path.read_text(encoding="utf-8")
            new = transform(raw)
            if new != raw:
                path.write_bytes(new.encode("utf-8"))
                changed.append(str(path.relative_to(ROOT.parent.parent)))
    print(f"Old Money pass — modified {len(changed)} files")
    for c in changed:
        print(f"  UPDATED: {c}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
