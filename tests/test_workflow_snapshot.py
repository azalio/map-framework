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

import pytest

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
    """Validate manifest dict against WORKFLOW_SNAPSHOT_SCHEMA; return error list.

    No required-key fallback: a hand-rolled presence check silently passes every
    constraint the schema actually encodes (enums, anyOf, additionalProperties),
    so the suite would report green while validating almost nothing. Skip the
    test instead of pretending to run it.
    """
    jsonschema = pytest.importorskip("jsonschema")
    validator_cls = getattr(
        jsonschema,
        "Draft202012Validator",
        getattr(jsonschema, "Draft7Validator", None),
    )
    assert validator_cls is not None, "jsonschema is installed but exposes no validator"
    return [str(e) for e in validator_cls(WORKFLOW_SNAPSHOT_SCHEMA).iter_errors(manifest_data)]


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
        """Drive the collision from a REAL input change, not a doctored manifest.

        Overwriting the stored `content_hash` proves only that the comparison
        reads that field. Mutating an actual captured input proves the hash is
        computed over the input at all — the property that matters.
        """
        _setup_branch_dir(tmp_path, "main")
        skill_dir = tmp_path / ".claude" / "skills" / "map-efficient"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# body v1\n", encoding="utf-8")

        r1 = _run_in(
            tmp_path,
            create_workflow_snapshot,
            "map-efficient",
            branch="main",
            run_id="20260101T000021Z",
        )
        assert r1["status"] == "success"

        # Change the real source, keep the run_id.
        (skill_dir / "SKILL.md").write_text("# body v2 — materially different\n", encoding="utf-8")

        r2 = _run_in(
            tmp_path,
            create_workflow_snapshot,
            "map-efficient",
            branch="main",
            run_id="20260101T000021Z",
        )
        assert r2["status"] == "error"
        assert r2["content_hash"] != r1["content_hash"]
        assert "differs" in r2["message"].lower() or "content_hash" in r2["message"].lower()

    def test_changed_extra_source_is_a_collision_not_a_silent_reuse(
        self, tmp_path: Path
    ) -> None:
        """`extra_sources` must be part of the identity hash.

        Omitting them let a rerun under the same run_id return "existing" while
        the stored files still held the PREVIOUS extra-source content — a
        snapshot that silently misrepresents what was captured.
        """
        _setup_branch_dir(tmp_path, "main")
        extra = tmp_path / "notes.md"
        extra.write_text("first\n", encoding="utf-8")

        r1 = _run_in(
            tmp_path,
            create_workflow_snapshot,
            "map-efficient",
            branch="main",
            run_id="20260101T000022Z",
            extra_sources=["notes.md"],
        )
        assert r1["status"] == "success"

        extra.write_text("second\n", encoding="utf-8")
        r2 = _run_in(
            tmp_path,
            create_workflow_snapshot,
            "map-efficient",
            branch="main",
            run_id="20260101T000022Z",
            extra_sources=["notes.md"],
        )
        assert r2["status"] == "error", "changed extra source must not reuse the snapshot"
        assert r2["content_hash"] != r1["content_hash"]

    def test_unchanged_extra_source_still_reuses(self, tmp_path: Path) -> None:
        """The positive half: identical inputs still resolve to "existing"."""
        _setup_branch_dir(tmp_path, "main")
        (tmp_path / "notes.md").write_text("stable\n", encoding="utf-8")

        kwargs = {"branch": "main", "run_id": "20260101T000023Z", "extra_sources": ["notes.md"]}
        r1 = _run_in(tmp_path, create_workflow_snapshot, "map-efficient", **kwargs)
        r2 = _run_in(tmp_path, create_workflow_snapshot, "map-efficient", **kwargs)
        assert r1["status"] == "success"
        assert r2["status"] == "existing"
        assert r1["content_hash"] == r2["content_hash"]


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

    def test_intact_manifest_over_deleted_files_is_not_reused(self, tmp_path: Path) -> None:
        """A matching content_hash must not vouch for files that are gone.

        content_hash proves the INPUTS matched. It says nothing about whether
        the stored payload survived. A half-deleted snapshot keeps its manifest
        intact, so a hash-only check hands a later reader an incomplete
        instruction surface and calls it valid.
        """
        _setup_branch_dir(tmp_path, "main")
        skill_dir = tmp_path / ".claude" / "skills" / "map-efficient"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# captured body\n", encoding="utf-8")

        r1 = _run_in(
            tmp_path,
            create_workflow_snapshot,
            "map-efficient",
            branch="main",
            run_id="20260101T000041Z",
        )
        assert r1["status"] == "success"
        (Path(r1["snapshot_path"]) / "skill.md").unlink()

        r2 = _run_in(
            tmp_path,
            create_workflow_snapshot,
            "map-efficient",
            branch="main",
            run_id="20260101T000041Z",
        )
        assert r2["status"] == "error", "a damaged snapshot must not be reused"
        assert "skill.md" in r2["message"]

    def test_truncated_snapshot_file_is_not_reused(self, tmp_path: Path) -> None:
        """Same guard, digest branch: the file exists but no longer matches."""
        _setup_branch_dir(tmp_path, "main")
        skill_dir = tmp_path / ".claude" / "skills" / "map-efficient"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# captured body\n", encoding="utf-8")

        r1 = _run_in(
            tmp_path,
            create_workflow_snapshot,
            "map-efficient",
            branch="main",
            run_id="20260101T000042Z",
        )
        (Path(r1["snapshot_path"]) / "skill.md").write_text("", encoding="utf-8")

        r2 = _run_in(
            tmp_path,
            create_workflow_snapshot,
            "map-efficient",
            branch="main",
            run_id="20260101T000042Z",
        )
        assert r2["status"] == "error"
        assert "mismatch" in r2["message"].lower()


class TestWorkflowSnapshotPathSafety:
    """`run_id`, `branch` and extra-source paths all become filesystem paths."""

    # NOTE: "" is deliberately absent — an empty run_id is falsy and falls back
    # to the UTC-timestamp default, which is intended behavior, not an escape.
    @pytest.mark.parametrize(
        "bad_run_id",
        ["../../../tmp/x", "..", "a/b", "with space", ".hidden", "x" * 65],
    )
    def test_unsafe_run_id_is_refused_without_writing(
        self, tmp_path: Path, bad_run_id: str
    ) -> None:
        _setup_branch_dir(tmp_path, "main")
        result = _run_in(
            tmp_path,
            create_workflow_snapshot,
            "map-efficient",
            branch="main",
            run_id=bad_run_id,
        )
        assert result["status"] == "error"
        assert "run_id" in result["message"]
        # Nothing may be created anywhere outside the branch snapshots dir.
        assert not (tmp_path.parent / "tmp" / "x").exists()
        assert list((tmp_path / ".map" / "main").glob("snapshots/*")) == []

    def test_slashed_branch_stays_inside_one_directory(self, tmp_path: Path) -> None:
        """`feat/foo` must not create a nested .map/feat/foo/ tree."""
        _setup_branch_dir(tmp_path, "feat-foo")
        result = _run_in(
            tmp_path,
            create_workflow_snapshot,
            "map-efficient",
            branch="feat/foo",
            run_id="20260101T000060Z",
        )
        assert result["status"] == "success"
        assert not (tmp_path / ".map" / "feat" / "foo").exists()
        assert Path(result["snapshot_path"]).is_relative_to(tmp_path / ".map" / "feat-foo")

    def test_extra_source_outside_project_root_is_refused(self, tmp_path: Path) -> None:
        _setup_branch_dir(tmp_path, "main")
        # Name deliberately innocent: the deny-list runs first (blocklist before
        # allowlist), so a credential-shaped name would mask the boundary check.
        outside = tmp_path.parent / "outside-notes.txt"
        outside.write_text("data\n", encoding="utf-8")
        try:
            result = _run_in(
                tmp_path,
                create_workflow_snapshot,
                "map-efficient",
                branch="main",
                run_id="20260101T000061Z",
                extra_sources=[str(outside)],
            )
        finally:
            outside.unlink()
        assert result["status"] == "error"
        assert "outside the project root" in result["message"]

    def test_same_basename_in_two_directories_does_not_collide(
        self, tmp_path: Path
    ) -> None:
        """Keying by basename let a/config.yaml and b/config.yaml overwrite."""
        _setup_branch_dir(tmp_path, "main")
        for sub, body in (("a", "from a\n"), ("b", "from b\n")):
            (tmp_path / sub).mkdir()
            (tmp_path / sub / "config.yaml").write_text(body, encoding="utf-8")

        result = _run_in(
            tmp_path,
            create_workflow_snapshot,
            "map-efficient",
            branch="main",
            run_id="20260101T000062Z",
            extra_sources=["a/config.yaml", "b/config.yaml"],
        )
        assert result["status"] == "success"
        snap = Path(result["snapshot_path"])
        assert (snap / "a" / "config.yaml").read_text() == "from a\n"
        assert (snap / "b" / "config.yaml").read_text() == "from b\n"

        manifest = json.loads((snap / "manifest.json").read_text())
        assert set(manifest["extra_sources"]) == {"a/config.yaml", "b/config.yaml"}

    @pytest.mark.parametrize(
        "bad_workflow_id",
        ["../../../../etc", "..", "a/b", "../.ssh"],
    )
    def test_unsafe_workflow_id_is_refused(
        self, tmp_path: Path, bad_workflow_id: str
    ) -> None:
        """`workflow_id` is interpolated into the skill candidate paths.

        Unvalidated it lets the runner probe OUTSIDE the project and persist
        whatever it finds as `skill.md`. `Path.relative_to` is lexical, so the
        recorded path would keep the `..` segments rather than fail.
        """
        _setup_branch_dir(tmp_path, "main")
        result = _run_in(
            tmp_path,
            create_workflow_snapshot,
            bad_workflow_id,
            branch="main",
            run_id="20260101T000064Z",
        )
        assert result["status"] == "error"
        assert "workflow_id" in result["message"]
        assert list((tmp_path / ".map" / "main").glob("snapshots/*")) == []

    @pytest.mark.parametrize(
        "reserved", ["manifest.json", "resolved-config.json", "skill.md"]
    )
    def test_extra_source_may_not_claim_a_reserved_name(
        self, tmp_path: Path, reserved: str
    ) -> None:
        _setup_branch_dir(tmp_path, "main")
        (tmp_path / reserved).write_text("impostor\n", encoding="utf-8")
        result = _run_in(
            tmp_path,
            create_workflow_snapshot,
            "map-efficient",
            branch="main",
            run_id="20260101T000063Z",
            extra_sources=[reserved],
        )
        assert result["status"] == "error"
        assert "reserved" in result["message"]


class TestWorkflowSnapshotSecrets:
    """Snapshots are durable, reviewer-visible artifacts. Secrets stay out."""

    @pytest.mark.parametrize(
        "name",
        [".env", ".env.production", "id_rsa", "server.pem", "app.key",
         "aws_credentials", "my_secret.txt", ".netrc"],
    )
    def test_credential_shaped_path_is_refused_before_reading(
        self, tmp_path: Path, name: str
    ) -> None:
        _setup_branch_dir(tmp_path, "main")
        (tmp_path / name).write_text("SUPER_SECRET=1\n", encoding="utf-8")
        result = _run_in(
            tmp_path,
            create_workflow_snapshot,
            "map-efficient",
            branch="main",
            run_id="20260101T000070Z",
            extra_sources=[name],
        )
        assert result["status"] == "error"
        assert "credential-shaped" in result["message"]
        assert list((tmp_path / ".map" / "main").glob("snapshots/*")) == []

    def test_high_confidence_secret_in_an_innocent_file_is_refused(
        self, tmp_path: Path
    ) -> None:
        """A token pasted into a normal file must not be persisted either."""
        _setup_branch_dir(tmp_path, "main")
        (tmp_path / "notes.md").write_text(
            "deploy with AKIAIOSFODNN7EXAMPLE\n", encoding="utf-8"
        )
        result = _run_in(
            tmp_path,
            create_workflow_snapshot,
            "map-efficient",
            branch="main",
            run_id="20260101T000071Z",
            extra_sources=["notes.md"],
        )
        assert result["status"] == "error"
        assert "aws_access_key_id" in result["message"]
        # The pattern NAME is reported, never the value.
        assert "AKIAIOSFODNN7EXAMPLE" not in result["message"]

    def test_symlink_to_a_credential_file_is_refused(self, tmp_path: Path) -> None:
        """The deny-list must see the RESOLVED target, not the caller's spelling."""
        _setup_branch_dir(tmp_path, "main")
        (tmp_path / ".env").write_text("API_TOKEN=hunter2\n", encoding="utf-8")
        link = tmp_path / "notes.md"
        try:
            link.symlink_to(tmp_path / ".env")
        except (OSError, NotImplementedError):
            pytest.skip("symlinks unavailable on this platform")

        result = _run_in(
            tmp_path,
            create_workflow_snapshot,
            "map-efficient",
            branch="main",
            run_id="20260101T000073Z",
            extra_sources=["notes.md"],
        )
        assert result["status"] == "error"
        assert "credential-shaped" in result["message"]
        assert list((tmp_path / ".map" / "main").glob("snapshots/*")) == []

    def test_secret_value_under_an_innocuous_config_key_is_redacted(
        self, tmp_path: Path
    ) -> None:
        """Key-name redaction alone leaves a token under `ca_bundle` in the clear."""
        _setup_branch_dir(tmp_path, "main")
        (tmp_path / ".map" / "config.yaml").write_text(
            "ca_bundle: ghp_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n"
            "harmless: just a string\n",
            encoding="utf-8",
        )
        result = _run_in(
            tmp_path,
            create_workflow_snapshot,
            "map-efficient",
            branch="main",
            run_id="20260101T000074Z",
        )
        assert result["status"] == "success"
        body = (Path(result["snapshot_path"]) / "resolved-config.json").read_text()
        assert "ghp_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" not in body
        assert "[REDACTED]" in body
        assert "just a string" in body, "non-secret values must survive untouched"

    def test_secret_shaped_config_values_are_redacted_but_keys_kept(
        self, tmp_path: Path
    ) -> None:
        """Keys stay (they are part of the surface); values do not."""
        _setup_branch_dir(tmp_path, "main")
        (tmp_path / ".map" / "config.yaml").write_text(
            "review:\n"
            "  cross_ai:\n"
            "    api_key: sk-live-abcdef123456\n"
            "  enabled: true\n"
            "sofa_token: ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n",
            encoding="utf-8",
        )
        result = _run_in(
            tmp_path,
            create_workflow_snapshot,
            "map-efficient",
            branch="main",
            run_id="20260101T000072Z",
        )
        assert result["status"] == "success"
        body = (Path(result["snapshot_path"]) / "resolved-config.json").read_text()
        assert "sk-live-abcdef123456" not in body
        assert "ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" not in body
        # Structure survives: a reviewer can still see WHAT was configured.
        assert "api_key" in body and "sofa_token" in body
        assert "[REDACTED]" in body
        assert '"enabled": true' in body


class TestWorkflowSnapshotConfigState:
    """`absent`, `unreadable` and `present` are three different states."""

    def test_absent_config_is_reported_absent_not_present(self, tmp_path: Path) -> None:
        _setup_branch_dir(tmp_path, "main")
        result = _run_in(
            tmp_path,
            create_workflow_snapshot,
            "map-efficient",
            branch="main",
            run_id="20260101T000080Z",
        )
        manifest = json.loads((Path(result["snapshot_path"]) / "manifest.json").read_text())
        entry = manifest["sources"]["resolved_config"]
        assert entry["present"] is False
        assert entry["state"] == "absent"

    def test_unreadable_config_does_not_hash_equal_to_an_absent_one(
        self, tmp_path: Path
    ) -> None:
        """Both used to collapse to {} and share a content_hash."""
        _setup_branch_dir(tmp_path, "main")
        absent = _run_in(
            tmp_path,
            create_workflow_snapshot,
            "map-efficient",
            branch="main",
            run_id="20260101T000081Z",
        )

        (tmp_path / ".map" / "config.yaml").write_text("{[not: valid: yaml\n", encoding="utf-8")
        broken = _run_in(
            tmp_path,
            create_workflow_snapshot,
            "map-efficient",
            branch="main",
            run_id="20260101T000082Z",
        )
        manifest = json.loads((Path(broken["snapshot_path"]) / "manifest.json").read_text())
        assert manifest["sources"]["resolved_config"]["state"] == "unreadable"
        assert manifest["sources"]["resolved_config"]["present"] is False
        assert broken["content_hash"] != absent["content_hash"]

    def test_map_identity_is_always_present(self, tmp_path: Path) -> None:
        """A manifest with neither identity cannot reconstruct the MAP surface."""
        _setup_branch_dir(tmp_path, "main")
        result = _run_in(
            tmp_path,
            create_workflow_snapshot,
            "map-efficient",
            branch="main",
            run_id="20260101T000083Z",
        )
        manifest = json.loads((Path(result["snapshot_path"]) / "manifest.json").read_text())
        assert manifest["map_version"] or manifest["map_source_sha256"]
        assert _validate_snapshot_schema(manifest) == []

    def test_schema_rejects_a_manifest_with_no_map_identity(self) -> None:
        """Negative proof that the anyOf actually binds."""
        manifest = {
            "schema_version": "1",
            "run_id": "20260101T000084Z",
            "workflow_id": "map-efficient",
            "provider": "claude",
            "branch": "main",
            "map_version": None,
            "map_source_sha256": None,
            "content_hash": "0" * 64,
            "captured_at": "2026-01-01T00:00:00Z",
            "sources": {
                "skill_md": {"path": None, "sha256": None, "present": False},
                "resolved_config": {
                    "path": ".map/config.yaml",
                    "sha256": "0" * 64,
                    "present": False,
                    "state": "absent",
                },
            },
            "extra_sources": {},
        }
        assert _validate_snapshot_schema(manifest), (
            "a manifest carrying neither map_version nor map_source_sha256 must be rejected"
        )


class TestWorkflowSnapshotManifestRegistration:
    """The stage reference is what a follow-up slice resolves the snapshot by."""

    def test_reuse_path_also_registers_the_stage(self, tmp_path: Path) -> None:
        """A reused snapshot still needs its manifest entry for THAT run.

        Returning `existing` before the registration left `artifact_manifest.json`
        with no snapshot reference, so downstream consumers could not resolve the
        path or content_hash at all.
        """
        _setup_branch_dir(tmp_path, "main")
        kwargs = {"branch": "main", "run_id": "20260101T000090Z"}
        first = _run_in(tmp_path, create_workflow_snapshot, "map-efficient", **kwargs)
        assert first["status"] == "success"

        # Drop the manifest so only the reuse path could restore the reference.
        manifest_path = tmp_path / ".map" / "main" / "artifact_manifest.json"
        manifest_path.unlink()

        second = _run_in(tmp_path, create_workflow_snapshot, "map-efficient", **kwargs)
        assert second["status"] == "existing"
        assert "manifest_error" not in second, second.get("manifest_error")
        stage = json.loads(manifest_path.read_text())["stages"]["workflow_snapshot"]
        assert stage["metadata"]["content_hash"] == second["content_hash"]
        assert stage["metadata"]["run_id"] == "20260101T000090Z"

    def test_manifest_failure_degrades_instead_of_raising(self, tmp_path: Path) -> None:
        """The snapshot is already durable; a manifest error must not erase it.

        An unguarded write raised out of `create_workflow_snapshot`, so the CLI
        got a traceback while the snapshot directory existed on disk — and a
        rerun then took the reuse branch, so the stage was never registered.
        """
        _setup_branch_dir(tmp_path, "main")
        # A directory where the manifest file must go makes the write fail.
        (tmp_path / ".map" / "main" / "artifact_manifest.json").mkdir()

        result = _run_in(
            tmp_path,
            create_workflow_snapshot,
            "map-efficient",
            branch="main",
            run_id="20260101T000091Z",
        )
        assert result["status"] == "success", "the snapshot itself still succeeded"
        assert "manifest_error" in result, "the degradation must be reported, not hidden"
        assert (Path(result["snapshot_path"]) / "manifest.json").exists()


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

    def test_cli_error_path_exits_1_with_parseable_json(self, tmp_path: Path) -> None:
        """The error path must keep the JSON contract, not emit a traceback.

        A `ValueError` escaping `_snapshot_dir` would reach the CLI as a stack
        trace on stderr with EMPTY stdout, so a caller parsing stdout gets a
        JSONDecodeError instead of the documented error dict.
        """
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
                "../../../tmp/escape",
            ],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 1, f"expected exit 1, got {proc.returncode}: {proc.stderr}"
        assert "Traceback" not in proc.stderr
        data = json.loads(proc.stdout)
        assert data["status"] == "error"
        assert "run_id" in data["message"]
