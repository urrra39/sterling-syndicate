from __future__ import annotations

"""Semantic AST chunking for portfolio RAG — keep logic, drop boilerplate."""

import ast
import logging
import re
from pathlib import PurePosixPath
from typing import Dict, List, Optional

logger = logging.getLogger("sterling.ast_chunk")

BOILERPLATE_NAMES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "composer.lock",
    "cargo.lock",
    "poetry.lock",
    "go.sum",
    ".gitignore",
    ".gitattributes",
    ".editorconfig",
    ".dockerignore",
    ".eslintrc",
    ".eslintrc.js",
    ".eslintrc.cjs",
    ".prettierrc",
    ".babelrc",
    "thumbs.db",
    "license",
    "license.md",
    "changelog.md",
    "changelog",
}

BOILERPLATE_SUFFIXES = {
    ".min.js",
    ".min.css",
    ".map",
    ".lock",
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
}

BOILERPLATE_DIR_PARTS = {
    "node_modules",
    "dist",
    "build",
    ".git",
    "vendor",
    "__pycache__",
    ".venv",
    "venv",
    "coverage",
    ".next",
    ".nuxt",
    "target",
}


def is_boilerplate_path(path: str) -> bool:
    p = PurePosixPath(path.replace("\\", "/"))
    name = p.name.lower()
    if name in BOILERPLATE_NAMES:
        return True
    if any(name.endswith(suf) for suf in BOILERPLATE_SUFFIXES):
        return True
    parts = {part.lower() for part in p.parts}
    if parts & BOILERPLATE_DIR_PARTS:
        return True
    # Auto-generated / config dumps
    if name.endswith(".generated.ts") or name.endswith(".generated.js"):
        return True
    if name in {"package.json", "tsconfig.json", "pyproject.toml"} and False:
        # Keep package.json briefly? No — usually noise for proposals. Exclude.
        pass
    if name in {
        "package.json",
        "tsconfig.json",
        "jsconfig.json",
        "webpack.config.js",
        "vite.config.ts",
        "vite.config.js",
        "rollup.config.js",
        "dockerfile",
    }:
        return True
    return False


def chunk_source_file(path: str, content: str, *, max_chunks: int = 12) -> List[Dict[str, str]]:
    """Extract architecture-relevant chunks from a source file."""
    if is_boilerplate_path(path) or not content.strip():
        return []

    lower = path.lower()
    if lower.endswith(".py"):
        chunks = _chunk_python(path, content)
    elif lower.endswith((".ts", ".tsx", ".js", ".jsx")):
        chunks = _chunk_js_like(path, content)
    elif lower.endswith((".md", ".mdx", ".rst")):
        chunks = _chunk_markdown(path, content)
    else:
        chunks = _chunk_generic(path, content)

    return chunks[:max_chunks]


def _chunk_python(path: str, content: str) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return _chunk_generic(path, content)

    # Module docstring
    mod_doc = ast.get_docstring(tree)
    if mod_doc:
        out.append(
            {
                "id": f"{path}::module_doc",
                "title": f"{path} (module)",
                "source": f"ast:{path}",
                "text": f"Module docstring for {path}:\n{mod_doc}",
            }
        )

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(_py_func_chunk(path, content, node))
        elif isinstance(node, ast.ClassDef):
            out.append(_py_class_chunk(path, content, node))
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if item.name.startswith("_") and item.name != "__init__":
                        continue
                    out.append(_py_func_chunk(path, content, item, parent=node.name))
    return [c for c in out if c.get("text")]


def _py_func_chunk(
    path: str,
    source: str,
    node: ast.AST,
    parent: Optional[str] = None,
) -> Dict[str, str]:
    assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    doc = ast.get_docstring(node) or ""
    end = node.end_lineno or node.lineno
    cap = node.lineno + 40
    snippet = _slice_lines(source, node.lineno, min(end, cap))
    if end > cap:
        # Tell downstream RAG consumers the snippet is partial instead of
        # presenting a silently truncated body as complete.
        snippet += f"\n# ... [truncated {end - cap} lines]"
    qual = f"{parent}.{node.name}" if parent else node.name
    text = f"Function `{qual}` in {path}\n"
    if doc:
        text += f"Docstring: {doc}\n"
    text += f"Code:\n{snippet}"
    return {
        # Disambiguate by line number: a @property getter and its @x.setter are
        # two class-body defs with the same qualified name and would otherwise
        # collide into one chunk id (and abort the Chroma batch).
        "id": f"{path}::{qual}:{node.lineno}",
        "title": f"{qual} ({path})",
        "source": f"ast:{path}",
        "text": text[:8000],
    }


def _py_class_chunk(path: str, source: str, node: ast.ClassDef) -> Dict[str, str]:
    doc = ast.get_docstring(node) or ""
    end = node.end_lineno or node.lineno
    cap = node.lineno + 25
    snippet = _slice_lines(source, node.lineno, min(end, cap))
    if end > cap:
        snippet += f"\n# ... [truncated {end - cap} lines]"
    text = f"Class `{node.name}` in {path}\n"
    if doc:
        text += f"Docstring: {doc}\n"
    text += f"Code:\n{snippet}"
    return {
        "id": f"{path}::{node.name}",
        "title": f"{node.name} ({path})",
        "source": f"ast:{path}",
        "text": text[:8000],
    }


def _chunk_js_like(path: str, content: str) -> List[Dict[str, str]]:
    """Lightweight function/class extraction without a full JS parser."""
    out: List[Dict[str, str]] = []
    # Exported functions / classes
    patterns = [
        re.compile(
            r"(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\([^)]*\)\s*\{",
            re.M,
        ),
        re.compile(r"(?:export\s+)?class\s+(\w+)", re.M),
        re.compile(
            r"(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>",
            re.M,
        ),
    ]
    for pattern in patterns:
        for m in pattern.finditer(content):
            name = m.group(1)
            start = m.start()
            snippet = content[start : start + 1200]
            out.append(
                {
                    "id": f"{path}::{name}:{start}",
                    "title": f"{name} ({path})",
                    "source": f"ast:{path}",
                    "text": f"Symbol `{name}` in {path}:\n{snippet}",
                }
            )
    if not out:
        return _chunk_generic(path, content)
    return out


def _chunk_markdown(path: str, content: str) -> List[Dict[str, str]]:
    # Keep README architecture sections; skip giant changelogs already filtered by name
    sections = re.split(r"(?m)^#{1,3}\s+", content)
    out: List[Dict[str, str]] = []
    for i, sec in enumerate(sections):
        sec = sec.strip()
        if len(sec) < 80:
            continue
        title_line = sec.split("\n", 1)[0][:80]
        out.append(
            {
                "id": f"{path}::sec{i}",
                "title": f"{title_line} ({path})",
                "source": f"md:{path}",
                "text": sec[:6000],
            }
        )
    return out[:8] or [
        {
            "id": f"{path}::full",
            "title": path,
            "source": f"md:{path}",
            "text": content[:6000],
        }
    ]


def _chunk_generic(path: str, content: str) -> List[Dict[str, str]]:
    if len(content) < 60:
        return []
    return [
        {
            "id": f"{path}::body",
            "title": path,
            "source": f"file:{path}",
            "text": content[:6000],
        }
    ]


def _slice_lines(source: str, start: int, end: int) -> str:
    lines = source.splitlines()
    start_i = max(0, start - 1)
    end_i = min(len(lines), end)
    return "\n".join(lines[start_i:end_i])
