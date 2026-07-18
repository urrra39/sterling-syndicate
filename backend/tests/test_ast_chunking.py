from __future__ import annotations

from app.services.ast_chunking import chunk_source_file, is_boilerplate_path


def test_boilerplate_filtered() -> None:
    assert is_boilerplate_path("frontend/package-lock.json")
    assert is_boilerplate_path("node_modules/lodash/index.js")
    assert is_boilerplate_path(".gitignore")
    assert not is_boilerplate_path("backend/app/services/pricing.py")


def test_python_ast_extracts_functions() -> None:
    src = '''
"""Module for pricing."""

def recommend_bid(text: str) -> float:
    """Compute a bid."""
    return 100.0

class Engine:
    """Pricing engine."""

    def run(self) -> None:
        """Execute."""
        pass
'''
    chunks = chunk_source_file("app/pricing.py", src)
    ids = " ".join(c["id"] for c in chunks)
    assert "recommend_bid" in ids
    assert "Engine" in ids
    assert any("Docstring" in c["text"] or "docstring" in c["text"].lower() for c in chunks)


def test_lockfile_yields_no_chunks() -> None:
    assert chunk_source_file("package-lock.json", '{"name": "x"}') == []
