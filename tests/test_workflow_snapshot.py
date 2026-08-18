"""Tests for create_workflow_snapshot (issue #415).

Tests cover:
  - Basic snapshot creation (files on disk, manifest.json content)
  - Schema validation of manifest.json against WORKFLOW_SNAPSHOT_SCHEMA
  - Idempotency: same run_id + same content -> "existing" status
  - Collision guard: same run_id but different content -> "error" status
  - Source mutation after snapshot: old snapshot unchanged
  - Snapshot corruption: reuse fails loudly
  - artifact_manifest.json updated with workflow_snapshot stage
  - CLI invocation via subprocess
"""

import importlib.util as _ilu
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPTS_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "mapify_cli"
    / "templates"
    / "map"
    / "scripts"
)

sys.path.insert(0, str(SCRIPTS_PATH))

from map_step_runner import create_workflow_snapshot  # type: ignore[import-not-found]

_SCHEMAS_PATH = Path(__file__).resolve().parents[1] / "src" / "mapify_cli" / "schemas.py"
_schemas_spec = _ilu.spec_from_file_location("mapify_cli_schemas", _SCHEMAS_PATH)
assert _schemas_spec is not None and _schemas_spec.loader is not None
_prev_no_bc = sys.dont_write_bytecode
sys.dont_write_bytecode = True
try:
    _schemas_mod = _ilu.module_from_spec(_schemas_spec)
    _schemas_spec.loader.exec_module(_schemas_mod)  # type: ignore[union-attr]
finally:
    sys.dont_write_bytecode = _prev_no_bc
WORKFLOW_SNAPSHOT_SCHEMA = _schemas_mod.WORKFLOW_SNAPSHOT_SCHEMA  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_snapshot_schema(manifest_data: dict) -> list[str]:
    """Validate manifest dict against WORKFLOW_SNAPSHOT_SCHEMA; return error list."""
    try:
        import jsonschema  # type: ignore[import-untyped]

        validator_cls = getattr(
            jsonschema,
            "Draft202012Validator",
            getattr(jsonschema, "Draft7Validator", None),
        )
        if validator_cls is None:
            raise ImportError
        v = validator_cls(WORKFLOW_SNAPSHOT_SCHEMA)
        return [str(e) for e in v.iter_errors(manifest_data)]
    except ImportError:
        required = WORKFLOW_SNAPSHOT_SCHEMA.get("required", [])
        return [f"Missing required field: {f}" for f in required if f not in manifest_data]


def _setup_branch_dir(tmp_path: Path, branch: str = "test-branch") -> Path:
    """Create a minimal .map/<branch>/ structure in tmp_path."""
    branch_dir = tmp_path / ".map" / branch
    branch_dir.mkdir(parents=True)
    (tmp_path / ".git").mkdir(exist_ok=True)
    (tmp_path / ".git" / "HEAD").write_text(f"ref: refs/heads/{branch}\n")
    return branch_dir


def _run_in(tmp_path: Path, fn, *args, **kwargs):
    """Run fn with cwd set to tmp_path.

    Resolves relative path fields in the result against tmp_path so callers
    can use result["snapshot_path"] etc. as absolute Paths after cwd is restored.
    """
    old_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = fn(*args, **kwargs)
    finally:
        os.chdir(old_cwd)

    resolved: dict = {}
    for key, val in result.items():
        if isinstance(val, str) and val and not os.path.isabs(val) and (
            "path" in key or "dir" in key
        ):
            resolved[key] = str(tmp_path / val)
        else:
            resolved[key] = val
    return resolved


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCreateWorkflowSnapshotBasic:
    def test_success_creates_snapshot_directory(self, tmp_path: Path) -> None:
        _setup_branch_dir(tmp_path, "main")
        result = _run_in(
            tmp_path,
            create_workflow_snapshot,
            "map-efficient",
            provider="claude",
            branch="main",
            run_id="20260101T000000Z",
        )
        assert result["status"] == "success"
        snap_dir = Path(result["snapshot_path"])
        assert snap_dir.exists()

    def test_manifest_json_created(self, tmp_path: Path) -> None:
        _setup_branch_dir(tmp_path, "main")
        result = _run_in(
            tmp_path,
            create_workflow_snapshot,
            "map-efficient",
            branch="main",
            run_id="20260101T000001Z",
        )
        snap_dir = Path(result["snapshot_path"])
        manifest_path = snap_dir / "manifest.json"
        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text())
        assert data["workflow_id"] == "map-efficient"
        assert data["branch"] == "main"
        assert data["run_id"] == "20260101T000001Z"
        assert data["schema_version"] == "1"

    def test_resolved_config_json_created(self, tmp_path: Path) -> None:
        _setup_branch_dir(tmp_path, "main")
        result = _run_in(
            tmp_path,
            create_workflow_snapshot,
            "map-efficient",
            branch="main",
            run_id="20260101T000002Z",
        )
        snap_dir = Path(result["snapshot_path"])
        assert (snap_dir / "resolved-config.json").exists()

    def test_skill_md_captured_when_present(self, tmp_path: Path) -> None:
        _setup_branch_dir(tmp_path, "main")
        skill_dir = tmp_path / ".claude" / "skills" / "map-efficient"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# map-efficient\n\nSkill body here.", encoding="utf-8")

        result = _run_in(
            tmp_path,
            create_workflow_snapshot,
            "map-efficient",
            branch="main",
            run_id="20260101T000003Z",
        )
        snap_dir = Path(result["snapshot_path"])
        assert (snap_dir / "skill.md").exists()
        assert "map-efficient" in (snap_dir / "skill.md").read_text()

    def test_no_skill_md_when_absent(self, tmp_path: Path) -> None:
        _setup_branch_dir(tmp_path, "main")
        result = _run_in(
            tmp_path,
            create_workflow_snapshot,
            "no-such-skill",
            branch="main",
            run_id="20260101T000004Z",
        )
        snap_dir = Path(result["snapshot_path"])
        assert not (snap_dir / "skill.md").exists()
        data = json.loads((snap_dir / "manifest.json").read_text())
        assert data["sources"]["skill_md"]["present"] is False

    def test_content_hash_present_and_hexdigest(self, tmp_path: Path) -> None:
        _setup_branch_dir(tmp_path, "main")
        result = _run_in(
            tmp_path,
            create_workflow_snapshot,
            "map-efficient",
            branch="main",
            run_id="20260101T000005Z",
        )
        content_hash = result["content_hash"]
        assert isinstance(content_hash, str)
        assert len(content_hash) == 64  # SHA-256 hex
        assert all(c in "0123456789abcdef" for c in content_hash)

    def test_artifact_manifest_updated_with_workflow_snapshot_stage(
        self, tmp_path: Path
    ) -> None:
        _setup_branch_dir(tmp_path, "main")
        result = _run_in(
            tmp_path,
            create_workflow_snapshot,
            "map-efficient",
            branch="main",
            run_id="20260101T000006Z",
        )
        manifest_path = Path(result["manifest_path"])
        assert manifest_path.exists()
        artifact_manifest = json.loads(manifest_path.read_text())
        stages = artifact_manifest.get("stages", {})
        assert "workflow_snapshot" in stages
        assert stages["workflow_snapshot"]["status"] == "ready"


class TestWorkflowSnapshotSchemaValidation:
    def test_manifest_validates_against_schema(self, tmp_path: Path) -> None:
        _setup_branch_dir(tmp_path, "main")
        result = _run_in(
            tmp_path,
            create_workflow_snapshot,
            "map-efficient",
            branch="main",
            run_id="20260101T000010Z",
        )
        snap_dir = Path(result["snapshot_path"])
        data = json.loads((snap_dir / "manifest.json").read_text())
        errors = _validate_snapshot_schema(data)
        assert not errors, f"Schema validation errors: {errors}"


class TestWorkflowSnapshotIdempotency:
    def test_same_content_returns_existing(self, tmp_path: Path) -> None:
        _setup_branch_dir(tmp_path, "main")
        shared_kwargs: dict = {"branch": "main", "run_id": "20260101T000020Z"}
        r1 = _run_in(tmp_path, create_workflow_snapshot, "map-efficient", **shared_kwargs)
        r2 = _run_in(tmp_path, create_workflow_snapshot, "map-efficient", **shared_kwargs)
        assert r1["status"] == "success"
        assert r2["status"] == "existing"
        assert r1["content_hash"] == r2["content_hash"]

    def test_collision_with_different_content_returns_error(
        self, tmp_path: Path
    ) -> None:
        _setup_branch_dir(tmp_path, "main")
        r1 = _run_in(
            tmp_path,
            create_workflow_snapshot,
            "map-efficient",
            branch="main",
            run_id="20260101T000021Z",
        )
        assert r1["status"] == "success"

        # Tamper the on-disk content_hash so a second call sees a collision
        snap_dir = Path(r1["snapshot_path"])
        manifest_path = snap_dir / "manifest.json"
        data = json.loads(manifest_path.read_text())
        data["content_hash"] = "a" * 64
        manifest_path.write_text(json.dumps(data), encoding="utf-8")

        r2 = _run_in(
            tmp_path,
            create_workflow_snapshot,
            "map-efficient",
            branch="main",
            run_id="20260101T000021Z",
        )
        assert r2["status"] == "error"
        assert "differs" in r2["message"].lower() or "content_hash" in r2["message"].lower()


class TestWorkflowSnapshotMutationIsolation:
    """Source mutation after snapshot creation must not affect the snapshot."""

    def test_skill_md_mutation_does_not_change_snapshot(self, tmp_path: Path) -> None:
        _setup_branch_dir(tmp_path, "main")
        skill_dir = tmp_path / ".claude" / "skills" / "map-test"
        skill_dir.mkdir(parents=True)
        original_body = "# Original skill body\n"
        (skill_dir / "SKILL.md").write_text(original_body, encoding="utf-8")

        result = _run_in(
            tmp_path,
            create_workflow_snapshot,
            "map-test",
            branch="main",
            run_id="20260101T000030Z",
        )
        snap_dir = Path(result["snapshot_path"])
        original_hash = result["content_hash"]

        # Mutate the source skill after snapshot
        (skill_dir / "SKILL.md").write_text("# MUTATED skill body\n", encoding="utf-8")

        # Snapshot on disk must still reflect the original content
        snap_skill = snap_dir / "skill.md"
        assert snap_skill.read_text() == original_body

        # content_hash in the snapshot manifest must still reflect original
        data = json.loads((snap_dir / "manifest.json").read_text())
        assert data["content_hash"] == original_hash


class TestWorkflowSnapshotCorruption:
    """A corrupted snapshot manifest must fail loudly on reuse attempt."""

    def test_corrupt_manifest_returns_error_on_reuse(self, tmp_path: Path) -> None:
        _setup_branch_dir(tmp_path, "main")
        result = _run_in(
            tmp_path,
            create_workflow_snapshot,
            "map-efficient",
            branch="main",
            run_id="20260101T000040Z",
        )
        snap_dir = Path(result["snapshot_path"])
        manifest_path = snap_dir / "manifest.json"
        manifest_path.write_text("NOT VALID JSON {{{", encoding="utf-8")

        r2 = _run_in(
            tmp_path,
            create_workflow_snapshot,
            "map-efficient",
            branch="main",
            run_id="20260101T000040Z",
        )
        assert r2["status"] == "error"
        assert "unreadable" in r2["message"].lower() or "manifest" in r2["message"].lower()


class TestWorkflowSnapshotCLI:
    """Integration: CLI invocation via subprocess."""

    def test_cli_returns_json_with_success_status(self, tmp_path: Path) -> None:
        _setup_branch_dir(tmp_path, "main")
        proc = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS_PATH / "map_step_runner.py"),
                "create_workflow_snapshot",
                "map-efficient",
                "--branch",
                "main",
                "--run-id",
                "20260101T000050Z",
                "--provider",
                "claude",
            ],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, f"CLI failed: {proc.stderr}"
        data = json.loads(proc.stdout)
        assert data["status"] in ("success", "existing")
        assert "snapshot_path" in data
