"""Deterministic boundary-quality evaluation for architecture-heavy MAP blueprints.

Produces a boundary_quality_report from blueprint.json data alone — no network
access, no external model calls, no structural code-map required.

The report is ADVISORY by default: findings are warnings or informational, not
hard errors.  Hard errors (hallucinated paths, duplicate IDs, cycle detection)
remain in validate_blueprint_contract.

Checks implemented
------------------
FILE_SHARED_ACROSS_BOUNDARIES (warn)
    The same file appears in two subtasks that are not in a dependency
    relationship.  Ownership is ambiguous; concurrent writes will conflict.

CROSS_BOUNDARY_DEP_PRESSURE (warn)
    Two high-risk or large-diff subtasks touch the same top-level module
    directory but have no declared dependency between them.  Their order
    of execution may matter even though the graph does not encode it.

REFACTOR_WITHOUT_TEST_PAIR (info)
    A subtask with concern_type=refactor has no test subtask that declares
    it as a dependency.  Refactors without an explicit test gate are harder
    to verify as behavior-preserving.

LOW_COHESION_SUBTASK (info)
    A subtask's affected_files span three or more distinct top-level module
    directories without a concern_type that justifies cross-cutting changes
    (refactor, docs, release, cross-repo, config).  Consider splitting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BoundaryFinding:
    """A single boundary-quality finding."""

    severity: str
    code: str
    message: str
    subtask_ids: tuple[str, ...]
    evidence: tuple[str, ...]


@dataclass
class BoundaryQualityReport:
    """Aggregated boundary-quality report for one blueprint."""

    is_architecture_heavy: bool
    findings: list[BoundaryFinding] = field(default_factory=list)

    @property
    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for f in self.findings:
            counts[f.severity] = counts.get(f.severity, 0) + 1
        return counts

    def as_dict(self) -> dict[str, Any]:
        return {
            "is_architecture_heavy": self.is_architecture_heavy,
            "findings": [
                {
                    "severity": f.severity,
                    "code": f.code,
                    "message": f.message,
                    "subtask_ids": list(f.subtask_ids),
                    "evidence": list(f.evidence),
                }
                for f in self.findings
            ],
            "summary": self.summary,
        }


# ---------------------------------------------------------------------------
# Architecture-heavy detection
# ---------------------------------------------------------------------------

_ARCH_CONCERN_TYPES: frozenset[str] = frozenset({"refactor", "api", "data", "cross-repo"})
_LARGE_DIFF_SIZES: frozenset[str] = frozenset({"medium", "large"})
_PERMISSIVE_COHESION_TYPES: frozenset[str] = frozenset(
    {"refactor", "docs", "release", "cross-repo", "config"}
)


def is_architecture_heavy(blueprint: dict[str, Any]) -> bool:
    """Return True if the blueprint is architecture/refactor-heavy.

    A blueprint is considered architecture-heavy when either:
    - Any subtask combines concern_type=refactor with expected_diff_size=large, or
    - Three or more subtasks have an architecture-oriented concern_type
      (refactor, api, data, cross-repo).
    """
    subtasks: list[dict[str, Any]] = blueprint.get("subtasks", [])
    arch_count = sum(
        1 for st in subtasks if st.get("concern_type", "") in _ARCH_CONCERN_TYPES
    )
    has_heavy_refactor = any(
        st.get("concern_type") == "refactor" and st.get("expected_diff_size") == "large"
        for st in subtasks
    )
    return has_heavy_refactor or arch_count >= 3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_dep_pairs(subtasks: list[dict[str, Any]]) -> set[tuple[str, str]]:
    """Return all (child_id, parent_id) dependency pairs from the blueprint."""
    pairs: set[tuple[str, str]] = set()
    for st in subtasks:
        for dep in st.get("dependencies", []):
            pairs.add((st["id"], dep))
    return pairs


def _are_related(a_id: str, b_id: str, dep_pairs: set[tuple[str, str]]) -> bool:
    """True if a directly depends on b OR b directly depends on a."""
    return (a_id, b_id) in dep_pairs or (b_id, a_id) in dep_pairs


def _top_module(path: str) -> str:
    """Return the top-two-segment module path (e.g. 'src/mapify_cli') for a file path."""
    parts = PurePosixPath(path).parts
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return parts[0] if parts else ""


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_file_shared_across_boundaries(
    subtasks: list[dict[str, Any]],
    dep_pairs: set[tuple[str, str]],
) -> list[BoundaryFinding]:
    file_to_subtasks: dict[str, list[str]] = {}
    for st in subtasks:
        for f in st.get("affected_files", []):
            file_to_subtasks.setdefault(f, []).append(st["id"])

    findings: list[BoundaryFinding] = []
    seen: set[tuple[str, str, str]] = set()
    for file, owners in file_to_subtasks.items():
        if len(owners) < 2:
            continue
        for i in range(len(owners)):
            for j in range(i + 1, len(owners)):
                a, b = owners[i], owners[j]
                if _are_related(a, b, dep_pairs):
                    continue
                key = (min(a, b), max(a, b), file)
                if key in seen:
                    continue
                seen.add(key)
                findings.append(
                    BoundaryFinding(
                        severity="warn",
                        code="FILE_SHARED_ACROSS_BOUNDARIES",
                        message=(
                            f"'{file}' appears in both {a} and {b}, which are not "
                            "in a dependency relationship. Assign sole ownership "
                            "to one subtask or add an explicit dependency."
                        ),
                        subtask_ids=(a, b),
                        evidence=(file,),
                    )
                )
    return findings


def _check_cross_boundary_dep_pressure(
    subtasks: list[dict[str, Any]],
    dep_pairs: set[tuple[str, str]],
) -> list[BoundaryFinding]:
    heavy = [
        st
        for st in subtasks
        if st.get("risk") == "high" or st.get("expected_diff_size") == "large"
    ]

    findings: list[BoundaryFinding] = []
    for i in range(len(heavy)):
        for j in range(i + 1, len(heavy)):
            a, b = heavy[i], heavy[j]
            if _are_related(a["id"], b["id"], dep_pairs):
                continue
            prefixes_a = {_top_module(f) for f in a.get("affected_files", [])}
            prefixes_b = {_top_module(f) for f in b.get("affected_files", [])}
            shared = prefixes_a & prefixes_b
            if not shared:
                continue
            findings.append(
                BoundaryFinding(
                    severity="warn",
                    code="CROSS_BOUNDARY_DEP_PRESSURE",
                    message=(
                        f"{a['id']} and {b['id']} both touch "
                        f"{', '.join(sorted(shared))} but have no declared "
                        "dependency. Verify they can execute in any order "
                        "without write conflicts."
                    ),
                    subtask_ids=(a["id"], b["id"]),
                    evidence=tuple(sorted(shared)),
                )
            )
    return findings


def _check_refactor_without_test_coverage(
    subtasks: list[dict[str, Any]],
    dep_pairs: set[tuple[str, str]],
) -> list[BoundaryFinding]:
    refactor_ids = {st["id"] for st in subtasks if st.get("concern_type") == "refactor"}
    test_ids = {st["id"] for st in subtasks if st.get("concern_type") == "tests"}

    findings: list[BoundaryFinding] = []
    for r_id in sorted(refactor_ids):
        covered = any((t_id, r_id) in dep_pairs for t_id in test_ids)
        if not covered:
            findings.append(
                BoundaryFinding(
                    severity="info",
                    code="REFACTOR_WITHOUT_TEST_PAIR",
                    message=(
                        f"{r_id} has concern_type=refactor but no tests subtask "
                        "declares it as a dependency. Add or pair a tests subtask "
                        "to verify behavior is preserved."
                    ),
                    subtask_ids=(r_id,),
                    evidence=(),
                )
            )
    return findings


def _check_low_cohesion(subtasks: list[dict[str, Any]]) -> list[BoundaryFinding]:
    findings: list[BoundaryFinding] = []
    for st in subtasks:
        if st.get("concern_type") in _PERMISSIVE_COHESION_TYPES:
            continue
        prefixes = {_top_module(f) for f in st.get("affected_files", [])}
        if len(prefixes) >= 3:
            findings.append(
                BoundaryFinding(
                    severity="info",
                    code="LOW_COHESION_SUBTASK",
                    message=(
                        f"{st['id']} touches {len(prefixes)} distinct top-level "
                        f"directories ({', '.join(sorted(prefixes))}). Consider "
                        "splitting along module boundaries."
                    ),
                    subtask_ids=(st["id"],),
                    evidence=tuple(sorted(prefixes)),
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def report_boundary_quality(blueprint: dict[str, Any]) -> BoundaryQualityReport:
    """Produce a deterministic boundary-quality report from blueprint.json data.

    No network access, model calls, or external tools required.  The report
    is advisory: findings are warn or info, never hard errors.

    Args:
        blueprint: Parsed blueprint.json dict.

    Returns:
        BoundaryQualityReport with is_architecture_heavy flag, findings list,
        and a severity-count summary.
    """
    subtasks: list[dict[str, Any]] = blueprint.get("subtasks", [])
    dep_pairs = _build_dep_pairs(subtasks)
    heavy = is_architecture_heavy(blueprint)

    findings: list[BoundaryFinding] = []
    findings.extend(_check_file_shared_across_boundaries(subtasks, dep_pairs))
    findings.extend(_check_cross_boundary_dep_pressure(subtasks, dep_pairs))
    findings.extend(_check_refactor_without_test_coverage(subtasks, dep_pairs))
    findings.extend(_check_low_cohesion(subtasks))

    # Sort: warn before info, then by subtask_ids for determinism
    findings.sort(key=lambda f: (0 if f.severity == "warn" else 1, f.subtask_ids))

    return BoundaryQualityReport(is_architecture_heavy=heavy, findings=findings)
