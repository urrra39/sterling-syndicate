"""Regression tests for the second-pass bug fixes."""

import app.core.config as config_mod
from app.services.ast_chunking import chunk_source_file
from app.services.compliance import check_tos_compliance
from app.services.matching import match_score
from app.services.sast import scan_code


# --- compliance: defensive-security false positive (#14) ---
def test_defensive_security_post_allowed():
    # No attacker verb before "unauthorized access" -> not a hacking_hire match.
    assert check_tos_compliance("Build auth to prevent unauthorized access to user data").allowed
    # Raw "bypass 2fa" phrase, but a defensive verb ("block") precedes it.
    assert check_tos_compliance("Harden the API to block bypass 2fa attempts").allowed


def test_offensive_hacking_still_blocked():
    assert not check_tos_compliance("I need you to gain unauthorized access to my ex's gmail").allowed
    assert not check_tos_compliance("hack into someone's instagram account").allowed


# --- matching: clamp, no 0.5 baseline for unrelated (#15) ---
def test_unrelated_scores_below_half():
    # Two unrelated texts must not sit at the old 0.5 baseline.
    s = match_score("expert French pastry chef, croissants", "quantum chromodynamics lattice gauge")
    assert 0.0 <= s <= 1.0
    assert s < 0.5


def test_empty_portfolio_scores_zero():
    assert match_score("", "python fastapi backend") == 0.0


# --- sast: f-string SQL now detected (#8) ---
def test_fstring_sql_flagged():
    code = 'q = f"SELECT * FROM users WHERE name=\'{name}\'"\ncursor.execute(q)\n'
    report = scan_code(code)
    assert not report.passed
    assert any("fstring" in f.rule_id or "SQL" in f.message for f in report.findings)


# --- ast chunking: property/setter get distinct ids (#4) ---
def test_property_setter_distinct_ids():
    src = (
        "class C:\n"
        "    @property\n"
        "    def value(self):\n"
        "        return self._v\n"
        "    @value.setter\n"
        "    def value(self, v):\n"
        "        self._v = v\n"
    )
    chunks = chunk_source_file("pkg/c.py", src)
    ids = [c["id"] for c in chunks]
    assert len(ids) == len(set(ids)), f"duplicate chunk ids: {ids}"
