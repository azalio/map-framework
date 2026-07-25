"""Tests for grace_eval.sweep contract sweep / stale-anchor audit (#339).

Covers:
  GS1 — anchor extraction
  GS2 — contradiction detection for known signal pairs
  GS3 — no false positives on clean code
  GS4 — lie-variant fixture detection
  GS5 — sweep_variant_sources aggregates across multiple files
  GS6 — SweepFinding severity and location format
  GS7 — invalid variant rejected
"""

from __future__ import annotations

import pytest

from mapify_cli.grace_eval.schema import VARIANT_NAMES
from mapify_cli.grace_eval.sweep import sweep_source, sweep_variant_sources

# ---------------------------------------------------------------------------
# GS1 — anchor extraction (indirect: checks findings are produced for anchors)
# ---------------------------------------------------------------------------


class TestGs1AnchorExtraction:
    def test_contract_keyword_detected(self) -> None:
        source = (
            "def get_value(x):\n"
            "    # CONTRACT: never returns none\n"
            "    return None\n"
        )
        findings = sweep_source(source, variant="lie")
        assert len(findings) == 1

    def test_anchor_keyword_detected(self) -> None:
        source = (
            "def check(x):\n"
            "    # ANCHOR: never returns none\n"
            "    return None\n"
        )
        findings = sweep_source(source, variant="lie")
        assert len(findings) == 1

    def test_case_insensitive_keyword(self) -> None:
        source = (
            "# contract: never returns none\n"
            "return None\n"
        )
        findings = sweep_source(source, variant="lie")
        assert len(findings) == 1

    def test_no_anchors_no_findings(self) -> None:
        source = "def f(x):\n    return x + 1\n"
        findings = sweep_source(source, variant="baseline")
        assert findings == []

    def test_multiple_anchors_in_file(self) -> None:
        source = (
            "# CONTRACT: never returns none\n"
            "return None\n"
            "# CONTRACT: never returns none\n"
            "return None\n"
        )
        findings = sweep_source(source, variant="lie")
        assert len(findings) == 2


# ---------------------------------------------------------------------------
# GS2 — contradiction detection for known signal pairs
# ---------------------------------------------------------------------------


class TestGs2ContradictionDetection:
    def test_returns_none_contradicts_never_returns_none(self) -> None:
        source = "# CONTRACT: never returns none\nreturn None\n"
        findings = sweep_source(source, variant="lie")
        assert any("never returns none" in f.detail.lower() for f in findings)

    def test_returns_true_contradicts_returns_false(self) -> None:
        source = "# CONTRACT: returns false\nreturn True\n"
        findings = sweep_source(source, variant="lie")
        assert len(findings) == 1

    def test_returns_false_contradicts_returns_true(self) -> None:
        source = "# CONTRACT: returns true\nreturn False\n"
        findings = sweep_source(source, variant="lie")
        assert len(findings) == 1

    def test_list_append_contradicts_idempotent(self) -> None:
        source = "# CONTRACT: idempotent\nresults.append(x)\n"
        findings = sweep_source(source, variant="lie")
        assert len(findings) == 1

    def test_self_assignment_contradicts_no_side_effect(self) -> None:
        source = "# CONTRACT: no side effect\nself.count = 0\n"
        findings = sweep_source(source, variant="lie")
        assert len(findings) == 1

    def test_contradiction_beyond_lookahead_not_flagged(self) -> None:
        # Contradiction is placed 20 lines after the anchor, outside the 8-line window.
        filler = "    pass\n" * 15
        source = f"# CONTRACT: never returns none\n{filler}return None\n"
        findings = sweep_source(source, variant="lie")
        assert len(findings) == 0


# ---------------------------------------------------------------------------
# GS3 — no false positives on clean code
# ---------------------------------------------------------------------------


class TestGs3NoFalsePositives:
    def test_correct_never_returns_none(self) -> None:
        source = (
            "# CONTRACT: never returns none\n"
            "def f(x):\n"
            "    if x > 0:\n"
            "        return x\n"
            "    return 0\n"
        )
        findings = sweep_source(source, variant="inline")
        assert findings == []

    def test_correct_idempotent(self) -> None:
        source = (
            "# CONTRACT: idempotent\n"
            "def write(path, data):\n"
            "    path.write_text(data)\n"
        )
        findings = sweep_source(source, variant="min")
        assert findings == []

    def test_clean_code_no_anchor(self) -> None:
        source = "x = 1\ny = x + 2\n"
        findings = sweep_source(source, variant="lex")
        assert findings == []


# ---------------------------------------------------------------------------
# GS4 — lie-variant fixture detection
# ---------------------------------------------------------------------------


class TestGs4LieVariant:
    def _lie_source(self) -> str:
        return (
            "def validate(value):\n"
            "    # CONTRACT: returns false when value is negative\n"
            "    if value < 0:\n"
            "        return True   # lie: says False but code returns True\n"
        )

    def test_lie_variant_flagged(self) -> None:
        findings = sweep_source(self._lie_source(), variant="lie")
        assert len(findings) == 1
        assert findings[0].variant == "lie"
        assert findings[0].severity == "critical"

    def test_same_source_inline_also_flagged(self) -> None:
        # The sweep does not distinguish lie from other variants in detection logic;
        # lie just represents a source known to contain stale contracts.
        findings = sweep_source(self._lie_source(), variant="inline")
        assert len(findings) == 1
        assert findings[0].variant == "inline"

    def test_location_prefix_included(self) -> None:
        source = "# CONTRACT: returns false when value is negative\nreturn True\n"
        findings = sweep_source(source, variant="lie", location_prefix="src/utils.py")
        assert len(findings) == 1
        assert "src/utils.py" in findings[0].location

    def test_location_has_line_number(self) -> None:
        source = "# CONTRACT: returns false when value is negative\nreturn True\n"
        findings = sweep_source(source, variant="lie", location_prefix="f.py")
        assert "L1" in findings[0].location


# ---------------------------------------------------------------------------
# GS5 — sweep_variant_sources aggregates across multiple files
# ---------------------------------------------------------------------------


class TestGs5SweepVariantSources:
    def test_empty_sources(self) -> None:
        findings = sweep_variant_sources({}, variant="lie")
        assert findings == []

    def test_single_clean_file(self) -> None:
        findings = sweep_variant_sources({"src/a.py": "x = 1\n"}, variant="lex")
        assert findings == []

    def test_single_file_with_finding(self) -> None:
        sources = {
            "src/a.py": "# CONTRACT: never returns none\nreturn None\n",
        }
        findings = sweep_variant_sources(sources, variant="lie")
        assert len(findings) == 1
        assert "src/a.py" in findings[0].location

    def test_multiple_files_findings_aggregated(self) -> None:
        sources = {
            "src/a.py": "# CONTRACT: never returns none\nreturn None\n",
            "src/b.py": "# CONTRACT: returns false\nreturn True\n",
        }
        findings = sweep_variant_sources(sources, variant="lie")
        assert len(findings) == 2
        locs = {f.location for f in findings}
        assert any("src/a.py" in loc for loc in locs)
        assert any("src/b.py" in loc for loc in locs)

    def test_non_string_values_skipped(self) -> None:
        sources = {
            "src/a.py": "# CONTRACT: never returns none\nreturn None\n",
            "src/b.py": 42,  # non-str, should be skipped
        }
        findings = sweep_variant_sources(sources, variant="lie")  # type: ignore[arg-type]
        assert len(findings) == 1

    def test_clean_and_stale_mix(self) -> None:
        sources = {
            "src/clean.py": "def f(x):\n    return x\n",
            "src/stale.py": "# CONTRACT: never returns none\nreturn None\n",
        }
        findings = sweep_variant_sources(sources, variant="lie")
        assert len(findings) == 1
        assert "src/stale.py" in findings[0].location


# ---------------------------------------------------------------------------
# GS6 — SweepFinding severity and location format
# ---------------------------------------------------------------------------


class TestGs6FindingFormat:
    def test_finding_is_critical_for_contradiction(self) -> None:
        source = "# CONTRACT: never returns none\nreturn None\n"
        findings = sweep_source(source, variant="lie")
        assert all(f.severity == "critical" for f in findings)

    def test_detail_is_non_empty(self) -> None:
        source = "# CONTRACT: never returns none\nreturn None\n"
        findings = sweep_source(source, variant="lie")
        assert all(f.detail for f in findings)

    def test_variant_matches_input(self) -> None:
        source = "# CONTRACT: never returns none\nreturn None\n"
        for variant in ("lie", "inline", "lex"):
            findings = sweep_source(source, variant=variant)
            for f in findings:
                assert f.variant == variant


# ---------------------------------------------------------------------------
# GS7 — invalid variant rejected
# ---------------------------------------------------------------------------


class TestGs7InvalidVariant:
    def test_sweep_source_invalid_variant(self) -> None:
        with pytest.raises(ValueError, match="variant"):
            sweep_source("x = 1\n", variant="unknown")

    def test_sweep_variant_sources_invalid_variant(self) -> None:
        with pytest.raises(ValueError, match="variant"):
            sweep_variant_sources({"f.py": "x = 1\n"}, variant="bad")

    @pytest.mark.parametrize("variant", VARIANT_NAMES)
    def test_all_valid_variants_accepted(self, variant: str) -> None:
        findings = sweep_source("def f(): pass\n", variant=variant)
        assert isinstance(findings, list)
