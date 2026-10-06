"""Deterministic installation tests; no live agents or network research."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import mapify_cli
from mapify_cli import app

SESSION = "install-coordinator"
QUESTION = "Which local storage format is configured?"
GIST = "Use the configured JSON storage format."


def _install(project: Path, provider: str, *, upgrade: bool = False) -> None:
    expected_package = Path(__file__).resolve().parents[1] / "src" / "mapify_cli"
    assert mapify_cli.__file__ is not None
    assert Path(mapify_cli.__file__).resolve().parent == expected_package
    args = ["init", ".", "--force", "--no-git", "--mcp", "none", "--provider", provider]
    if upgrade:
        args.append("--refresh-existing")
    previous_cwd = Path.cwd()
    try:
        os.chdir(project)
        result = CliRunner().invoke(app, args)
    finally:
        os.chdir(previous_cwd)
    assert result.exit_code == 0, result.output
    skill_root = project / (
        ".claude/skills" if provider == "claude" else ".agents/skills"
    )
    assert (skill_root / "map-wayfind" / "SKILL.md").is_file()
    assert (skill_root / "map-wayfind" / "wayfind-reference.md").is_file()
    if provider == "claude":
        rules = json.loads(
            (skill_root / "skill-rules.json").read_text(encoding="utf-8")
        )
        assert rules["skills"]["map-wayfind"]["skillClass"] == "task"
    assert (project / ".map/scripts/wayfind_runner.py").is_file()
    if provider == "codex":
        assert not (project / ".claude").exists()
    else:
        assert not (project / ".codex").exists()


def _run(project: Path, *args: str, success: bool = True) -> dict[str, Any]:
    """Each command starts a fresh installed runner, with no in-memory state."""
    completed = subprocess.run(
        [sys.executable, str(project / ".map/scripts/wayfind_runner.py"), *args],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == (0 if success else 1), (
        completed.stdout + completed.stderr
    )
    payload: dict[str, Any] = json.loads(completed.stdout)
    assert payload["status"] == ("success" if success else "error"), payload
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record_evidence(project: Path, slug: str, ticket_id: str, mode: str) -> str:
    map_dir = project / ".map/wayfind" / slug
    context = _run(project, "research_context", slug, ticket_id)["context"]
    _run(
        project,
        "configure_research",
        slug,
        ticket_id,
        SESSION,
        mode,
        "Narrow factual lookup."
        if mode == "direct"
        else "Consequential storage choice.",
    )
    brief_path = f"research/{ticket_id}/brief.json"
    _write_json(
        map_dir / brief_path,
        {
            "protocol_version": 1,
            "ticket_id": ticket_id,
            "question": context["question"],
            "dependency_bindings": context["dependency_bindings"],
            "constraints": ["Inspect only the local configuration."],
            "settling_criteria": ["Identify the configured format from source."],
            "verification_target": None,
        },
    )
    source = project / "storage.py"
    source.write_text('STORAGE_FORMAT = "json"\n', encoding="utf-8")
    bindings = []
    for index in range(1 if mode == "direct" else 2):
        reservation = _run(
            project,
            "reserve_research_attempt",
            slug,
            ticket_id,
            SESSION,
            f"request-{index}",
            "initial",
            f"investigator-{index}",
            brief_path,
        )
        assert reservation["created"] is True
        attempt_id = reservation["attempt_id"]
        report_path = f"research/{ticket_id}/{attempt_id}/report.json"
        _write_json(
            map_dir / report_path,
            {
                "protocol_version": 1,
                "ticket_id": ticket_id,
                "attempt_id": attempt_id,
                "brief_sha256": reservation["attempt"]["brief_sha256"],
                "answer": GIST,
                "claims": [{"id": "format", "text": GIST, "evidence": ["config"]}],
                "sources": [
                    {
                        "id": "config",
                        "kind": "local_code",
                        "path": "storage.py",
                        "sha256": _sha256(source),
                    }
                ],
                "decisive_assumptions": ["This configuration is authoritative."],
                "falsification_conditions": ["The configured format changes."],
                "uncertainty": [],
            },
        )
        _run(
            project,
            "record_research_attempt",
            slug,
            ticket_id,
            SESSION,
            attempt_id,
            "completed",
            "--result-path",
            report_path,
        )
        bindings.append(
            {"attempt_id": attempt_id, "report_sha256": _sha256(map_dir / report_path)}
        )
    resolution_path = f"research/{ticket_id}/resolution.md"
    (map_dir / resolution_path).write_text(
        "# Storage decision\n\nUse JSON, as configured in storage.py.\n",
        encoding="utf-8",
    )
    assessment_path = f"research/{ticket_id}/assessment.json"
    _write_json(
        map_dir / assessment_path,
        {
            "protocol_version": 1,
            "ticket_id": ticket_id,
            "assessment_id": "storage-assessment",
            "attempt_bindings": bindings,
            "verdict": "sufficient",
            "gist": GIST,
            "resolution_path": resolution_path,
            "resolution_sha256": _sha256(map_dir / resolution_path),
            "material_disputes": [],
            "remaining_uncertainty": [],
            "no_further_verification_rationale": "All reports cite the configured format.",
        },
    )
    _run(
        project, "record_research_assessment", slug, ticket_id, SESSION, assessment_path
    )
    return resolution_path


@pytest.mark.parametrize("provider", ["claude", "codex"])
@pytest.mark.parametrize("mode", ["direct", "independent"])
def test_fresh_install_persists_research_and_rejects_stale_handoff(
    tmp_path: Path, provider: str, mode: str
) -> None:
    _install(tmp_path, provider)
    slug = "storage-decision"
    _run(tmp_path, "create_wayfind_map", slug, "Storage decision", "Select storage")
    ticket_id = _run(
        tmp_path, "add_ticket", slug, "Configured format", "research", QUESTION
    )["ticket_id"]
    _run(tmp_path, "claim_ticket", slug, ticket_id, SESSION)
    map_dir = tmp_path / ".map/wayfind" / slug
    (map_dir / "unsupported.md").write_text(
        "A guess without evidence.\n", encoding="utf-8"
    )
    rejected = _run(
        tmp_path,
        "resolve_ticket",
        slug,
        ticket_id,
        SESSION,
        GIST,
        "unsupported.md",
        success=False,
    )
    assert rejected["code"] == "research_assessment_required"
    resolution_path = _record_evidence(tmp_path, slug, ticket_id, mode)
    research = _run(tmp_path, "show_ticket", slug, ticket_id)["ticket"]["research"]
    assert research["budget_limit"] == 4
    assert len(research["attempts"]) == (1 if mode == "direct" else 2)
    assert all(attempt["outcome"] == "completed" for attempt in research["attempts"])
    _run(tmp_path, "resolve_ticket", slug, ticket_id, SESSION, GIST, resolution_path)
    _run(tmp_path, "emit_wayfind_handoff", slug)
    before_validation = {
        path: path.read_bytes() for path in map_dir.rglob("*") if path.is_file()
    }
    validated = _run(tmp_path, "validate_wayfind_handoff", slug)
    assert validated["evidence_status"] == "recorded"
    assert all(
        path.read_bytes() == content for path, content in before_validation.items()
    )
    handoff = json.loads((map_dir / "handoff.json").read_text(encoding="utf-8"))
    assert handoff["decisions"][0]["gist"] == GIST
    assert handoff["decisions"][0]["ticket_id"] == ticket_id
    (tmp_path / "storage.py").write_text(
        'STORAGE_FORMAT = "sqlite"\n', encoding="utf-8"
    )
    stale = _run(tmp_path, "validate_wayfind_handoff", slug, success=False)
    assert stale["status"] == "error"
    _run(tmp_path, "emit_wayfind_handoff", slug, success=False)
    assert (map_dir / "handoff.json").read_bytes() == before_validation[
        map_dir / "handoff.json"
    ]


def _seed_legacy_map(project: Path, slug: str, *, completed: bool) -> Path:
    map_dir = project / ".map/wayfind" / slug
    ticket = {
        "title": "Configured format",
        "type": "research",
        "question": QUESTION,
        "status": "resolved" if completed else "open",
        "blocked_by": [],
        "claimed_by": None,
        "claimed_at": None,
        "created_at": "2026-01-01T00:00:00Z",
        "resolved_at": "2026-01-01T01:00:00Z" if completed else None,
        "human_input_path": None,
        "from_fog": None,
        "resolution": {"gist": GIST, "path": "resolution.md"} if completed else None,
    }
    state = {
        "schema_version": "1.0",
        "backend": "local",
        "revision": 3,
        "map_id": f"legacy-{slug}",
        "slug": slug,
        "title": "Old map",
        "status": "handed_off" if completed else "charting",
        "destination": "Select storage",
        "notes": "User-owned old map",
        "fog": [],
        "out_of_scope": [],
        "tickets": {"T-1": ticket},
        "sessions": {},
    }
    _write_json(map_dir / "state.json", state)
    (map_dir / "map.md").write_text(
        "User notes from before upgrade.\n", encoding="utf-8"
    )
    (map_dir / "resolution.md").write_text("Old answer.\n", encoding="utf-8")
    if completed:
        _write_json(
            map_dir / "handoff.json",
            {
                "schema_version": "1.0",
                "slug": slug,
                "map_id": state["map_id"],
                "title": "Old map",
                "destination": "Select storage",
                "generated_at": "2026-01-01T01:00:00Z",
                "early": False,
                "decisions": [
                    {
                        "ticket_id": "T-1",
                        **ticket,
                        "gist": GIST,
                        "resolution_path": "resolution.md",
                    }
                ],
                "out_of_scope": [],
                "remaining_risks": [],
            },
        )
        (map_dir / "handoff.md").write_text("Old handoff.\n", encoding="utf-8")
    return map_dir


@pytest.mark.parametrize("provider", ["claude", "codex"])
def test_upgrade_preserves_old_maps_and_gates_old_open_research(
    tmp_path: Path, provider: str
) -> None:
    _install(tmp_path, provider)
    open_map = _seed_legacy_map(tmp_path, "old-open", completed=False)
    completed_map = _seed_legacy_map(tmp_path, "old-completed", completed=True)
    snapshot = {
        path: path.read_bytes()
        for root in (open_map, completed_map)
        for path in root.rglob("*")
        if path.is_file()
    }
    installed_runner = tmp_path / ".map/scripts/wayfind_runner.py"
    installed_runner.write_text("# obsolete pre-upgrade runtime\n", encoding="utf-8")
    _install(tmp_path, provider, upgrade=True)
    assert (
        installed_runner.read_text(encoding="utf-8")
        != "# obsolete pre-upgrade runtime\n"
    )
    assert all(path.read_bytes() == content for path, content in snapshot.items())
    assert "research" not in _run(tmp_path, "show_ticket", "old-open", "T-1")["ticket"]
    legacy = _run(tmp_path, "validate_wayfind_handoff", "old-completed")
    assert legacy["evidence_status"] == "legacy_unrecorded"
    assert legacy["warnings"]
    assert all(path.read_bytes() == content for path, content in snapshot.items())
    _run(tmp_path, "claim_ticket", "old-open", "T-1", SESSION)
    research = _run(tmp_path, "show_ticket", "old-open", "T-1")["ticket"]["research"]
    assert research["protocol_version"] == 1
    assert research["budget_limit"] == 4
    assert research["attempts"] == []
    rejected = _run(
        tmp_path,
        "resolve_ticket",
        "old-open",
        "T-1",
        SESSION,
        GIST,
        "resolution.md",
        success=False,
    )
    assert rejected["code"] == "research_assessment_required"
    assert (
        _run(tmp_path, "show_ticket", "old-open", "T-1")["ticket"]["status"] == "open"
    )
    assert all(
        path.read_bytes() == content
        for path, content in snapshot.items()
        if path.is_relative_to(completed_map)
    )
