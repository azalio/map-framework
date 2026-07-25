"""Tests for drift-aware managed file copier (Step 3 + C2 fence-aware merge).

Tests metadata injection, extraction, drift detection, copy_managed_file(),
and the fence-aware merge (TestFenceAwareMerge — ST-010 VC1-VC5).
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from mapify_cli.delivery.managed_file_copier import (
    CopyResult,
    DriftReport,
    compute_hash,
    copy_managed_file,
    detect_drift,
    extract_metadata,
    inject_metadata,
)


class TestComputeHash:
    def test_string_hash(self):
        h = compute_hash("hello")
        assert len(h) == 64  # SHA-256 hex
        assert h == compute_hash("hello")  # deterministic

    def test_bytes_hash(self):
        h = compute_hash(b"hello")
        assert h == compute_hash("hello")

    def test_different_content_different_hash(self):
        assert compute_hash("a") != compute_hash("b")


class TestInjectMetadata:
    def test_markdown(self):
        result = inject_metadata("# Hello", ".md", "1.0.0", "abc123")
        assert result.startswith("<!-- MAP-MANAGED:")
        assert '"mapify_version":"1.0.0"' in result
        assert '"template_hash":"abc123"' in result
        assert result.endswith("# Hello")

    def test_python_no_shebang(self):
        result = inject_metadata('print("hi")', ".py", "1.0.0", "abc123")
        assert result.startswith("# MAP-MANAGED:")
        assert result.endswith('print("hi")')

    def test_python_with_shebang(self):
        src = '#!/usr/bin/env python3\nprint("hi")'
        result = inject_metadata(src, ".py", "1.0.0", "abc123")
        assert result.startswith("#!/usr/bin/env python3\n")
        assert "# MAP-MANAGED:" in result
        assert result.endswith('print("hi")')

    def test_json(self):
        src = json.dumps({"key": "value"})
        result = inject_metadata(src, ".json", "1.0.0", "abc123")
        data = json.loads(result)
        assert "_map_managed" in data
        assert data["_map_managed"]["mapify_version"] == "1.0.0"
        assert data["key"] == "value"

    def test_json_non_dict(self):
        src = json.dumps([1, 2, 3])
        result = inject_metadata(src, ".json", "1.0.0", "abc123")
        assert result == src  # unchanged for non-dict JSON

    def test_unknown_extension(self):
        result = inject_metadata("content", ".txt", "1.0.0", "abc123")
        assert result == "content"  # unchanged


class TestExtractMetadata:
    def test_markdown_roundtrip(self):
        original = "# Hello World\nSome content."
        injected = inject_metadata(original, ".md", "1.0.0", "abc123")
        meta, clean = extract_metadata(injected, ".md")
        assert meta is not None
        assert meta["mapify_version"] == "1.0.0"
        assert meta["template_hash"] == "abc123"
        assert clean == original

    def test_python_roundtrip(self):
        original = 'print("hi")\n'
        injected = inject_metadata(original, ".py", "1.0.0", "abc123")
        meta, clean = extract_metadata(injected, ".py")
        assert meta is not None
        assert meta["template_hash"] == "abc123"
        assert clean == original

    def test_python_shebang_roundtrip(self):
        original = '#!/usr/bin/env python3\nprint("hi")\n'
        injected = inject_metadata(original, ".py", "1.0.0", "abc123")
        meta, clean = extract_metadata(injected, ".py")
        assert meta is not None
        assert meta["template_hash"] == "abc123"
        assert "#!/usr/bin/env python3" in clean
        assert 'print("hi")' in clean

    def test_json_roundtrip(self):
        original_data = {"key": "value", "nested": {"a": 1}}
        original = json.dumps(original_data)
        injected = inject_metadata(original, ".json", "1.0.0", "abc123")
        meta, clean = extract_metadata(injected, ".json")
        assert meta is not None
        assert meta["template_hash"] == "abc123"
        clean_data = json.loads(clean)
        assert "_map_managed" not in clean_data
        assert clean_data["key"] == "value"

    def test_no_metadata_md(self):
        meta, clean = extract_metadata("# Just content", ".md")
        assert meta is None
        assert clean == "# Just content"

    def test_no_metadata_py(self):
        meta, clean = extract_metadata('print("hi")', ".py")
        assert meta is None
        assert clean == 'print("hi")'

    def test_no_metadata_json(self):
        src = json.dumps({"key": "val"})
        meta, _ = extract_metadata(src, ".json")
        assert meta is None


class TestDetectDrift:
    def test_no_dest_file(self, tmp_path):
        src = tmp_path / "src.md"
        src.write_text("# Content")
        dest = tmp_path / "dest.md"
        result = detect_drift(src, dest)
        assert result.first_install
        assert not result.drifted

    def test_no_metadata_in_dest(self, tmp_path):
        src = tmp_path / "src.md"
        src.write_text("# Content")
        dest = tmp_path / "dest.md"
        dest.write_text("# Old content without metadata")
        result = detect_drift(src, dest)
        assert not result.drifted
        assert "no metadata" in result.reason

    def test_unmodified_file(self, tmp_path):
        src = tmp_path / "src.md"
        original = "# Content"
        src.write_text(original)
        template_hash = compute_hash(original)

        dest = tmp_path / "dest.md"
        dest.write_text(inject_metadata(original, ".md", "1.0.0", template_hash))

        result = detect_drift(src, dest)
        assert not result.drifted

    def test_modified_file_detected(self, tmp_path):
        src = tmp_path / "src.md"
        original = "# Content"
        src.write_text(original)
        template_hash = compute_hash(original)

        # Install original with metadata
        dest = tmp_path / "dest.md"
        injected = inject_metadata(original, ".md", "1.0.0", template_hash)
        # User modifies the content
        modified = injected.replace("# Content", "# Modified by user")
        dest.write_text(modified)

        result = detect_drift(src, dest)
        assert result.drifted
        assert "modified" in result.reason


class TestCopyManagedFile:
    def test_first_install_md(self, tmp_path):
        src = tmp_path / "template.md"
        src.write_text("# Agent Template\nDo things.")
        dest = tmp_path / "output" / "agent.md"

        result = copy_managed_file(src, dest, "3.5.0")
        assert result.success
        assert not result.drifted
        assert dest.exists()

        content = dest.read_text()
        assert "MAP-MANAGED" in content
        assert "# Agent Template" in content

    def test_first_install_py(self, tmp_path):
        src = tmp_path / "hook.py"
        src.write_text('#!/usr/bin/env python3\nprint("hook")\n')
        dest = tmp_path / "output" / "hook.py"

        result = copy_managed_file(src, dest, "3.5.0")
        assert result.success
        content = dest.read_text()
        assert content.startswith("#!/usr/bin/env python3\n")
        assert "MAP-MANAGED" in content

    def test_first_install_json(self, tmp_path):
        src = tmp_path / "config.json"
        src.write_text(json.dumps({"key": "val"}))
        dest = tmp_path / "output" / "config.json"

        result = copy_managed_file(src, dest, "3.5.0")
        assert result.success
        data = json.loads(dest.read_text())
        assert "_map_managed" in data
        assert data["key"] == "val"

    def test_upgrade_no_drift(self, tmp_path):
        src = tmp_path / "template.md"
        original = "# Content"
        src.write_text(original)
        dest = tmp_path / "dest.md"

        # First install
        copy_managed_file(src, dest, "3.5.0")

        # Upgrade (same template)
        result = copy_managed_file(src, dest, "3.6.0")
        assert result.success
        assert not result.drifted
        assert not result.backed_up

    def test_upgrade_with_drift_creates_backup(self, tmp_path):
        src = tmp_path / "template.md"
        original = "# Content"
        src.write_text(original)
        dest = tmp_path / "dest.md"

        # First install
        copy_managed_file(src, dest, "3.5.0")

        # User modifies
        content = dest.read_text()
        dest.write_text(content.replace("# Content", "# My custom content"))

        # Upgrade
        result = copy_managed_file(src, dest, "3.6.0")
        assert result.success
        assert result.drifted
        assert result.backed_up
        assert result.backup_path is not None
        assert result.backup_path.exists()
        assert "My custom content" in result.backup_path.read_text()

    def test_unknown_ext_plain_copy(self, tmp_path):
        src = tmp_path / "data.bin"
        src.write_bytes(b"\x00\x01\x02")
        dest = tmp_path / "output" / "data.bin"

        result = copy_managed_file(src, dest, "3.5.0", inject_meta=False)
        assert result.success
        assert dest.read_bytes() == b"\x00\x01\x02"

    def test_yaml_file_has_metadata_and_fence(self, tmp_path):
        """Phase C2: yaml is now fence-supported with # MAP-MANAGED and # map:start/end."""
        src = tmp_path / "config.yaml"
        src.write_text("key: value\n")
        dest = tmp_path / "output" / "config.yaml"

        result = copy_managed_file(src, dest, "3.5.0")
        assert result.success
        content = dest.read_text()
        assert "MAP-MANAGED" in content, "yaml must now have MAP-MANAGED metadata"
        assert "# map:start" in content, "yaml must have fence start token"
        assert "# map:end" in content, "yaml must have fence end token"

    def test_repeated_upgrade_no_backup_collision(self, tmp_path):
        """Two upgrades on a drifted file must create separate backups."""
        import time

        src = tmp_path / "template.md"
        src.write_text("# Original")
        dest = tmp_path / "dest.md"

        # First install
        copy_managed_file(src, dest, "3.5.0")

        # User modifies
        content = dest.read_text()
        dest.write_text(content.replace("# Original", "# User v1"))

        # First upgrade — creates backup
        result1 = copy_managed_file(src, dest, "3.6.0")
        assert result1.backed_up
        backup1 = result1.backup_path

        # User modifies again
        content = dest.read_text()
        dest.write_text(content.replace("# Original", "# User v2"))

        # Small delay to ensure different timestamp
        time.sleep(1.1)

        # Second upgrade — must NOT overwrite first backup
        result2 = copy_managed_file(src, dest, "3.7.0")
        assert result2.backed_up
        backup2 = result2.backup_path

        assert backup1 is not None
        assert backup2 is not None
        assert backup1 != backup2, "Second backup must have a different path"
        assert backup1.exists(), "First backup must still exist"
        assert backup2.exists(), "Second backup must exist"
        assert "User v1" in backup1.read_text()
        assert "User v2" in backup2.read_text()


class TestDriftReport:
    def test_empty_report(self):
        report = DriftReport()
        assert not report.has_drift
        assert report.drifted_files == []

    def test_with_drifted_file(self):
        report = DriftReport()
        report.results.append(
            CopyResult(src=Path("a"), dest=Path("b"), drifted=True, backed_up=True)
        )
        report.results.append(CopyResult(src=Path("c"), dest=Path("d"), drifted=False))
        assert report.has_drift
        assert len(report.drifted_files) == 1
        assert len(report.backed_up_files) == 1


class TestFrontmatterPreservation:
    """Tests that .md files with YAML frontmatter get MAP-MANAGED after closing ---."""

    def test_inject_after_frontmatter(self):
        src = "---\nname: actor\ndescription: test\n---\n\n# Content"
        result = inject_metadata(src, ".md", "1.0.0", "abc123")
        # Must start with --- (frontmatter intact)
        assert result.startswith("---\n")
        # MAP-MANAGED must come after closing ---
        lines = result.split("\n")
        fm_close_idx = None
        for i, line in enumerate(lines):
            if i > 0 and line == "---":
                fm_close_idx = i
                break
        assert fm_close_idx is not None
        # Next line after closing --- should be MAP-MANAGED comment
        assert lines[fm_close_idx + 1].startswith("<!-- MAP-MANAGED:")
        # Original content must be preserved
        assert "# Content" in result

    def test_inject_no_frontmatter_unchanged(self):
        src = "# Just a heading\nNo frontmatter here."
        result = inject_metadata(src, ".md", "1.0.0", "abc123")
        # Should prepend as before (no frontmatter)
        assert result.startswith("<!-- MAP-MANAGED:")

    def test_extract_after_frontmatter_roundtrip(self):
        original = "---\nname: monitor\ndescription: test agent\n---\n\n# Monitor"
        injected = inject_metadata(original, ".md", "1.0.0", "abc123")
        meta, clean = extract_metadata(injected, ".md")
        assert meta is not None
        assert meta["mapify_version"] == "1.0.0"
        assert meta["template_hash"] == "abc123"
        assert clean == original

    def test_extract_legacy_prepended_still_works(self):
        """Backward compat: files with MAP-MANAGED at start still extract."""
        legacy = '<!-- MAP-MANAGED: {"mapify_version":"1.0.0","template_hash":"abc"} -->\n# Content'
        meta, clean = extract_metadata(legacy, ".md")
        assert meta is not None
        assert meta["mapify_version"] == "1.0.0"
        assert clean == "# Content"

    def test_copy_managed_file_frontmatter(self, tmp_path):
        src = tmp_path / "agent.md"
        src.write_text(
            "---\nname: actor\ndescription: Generates code\nmodel: sonnet\n---\n\n# Actor Agent\n"
        )
        dest = tmp_path / "output" / "actor.md"

        result = copy_managed_file(src, dest, "3.6.0")
        assert result.success
        content = dest.read_text()
        # File must start with --- for Claude Code to parse frontmatter
        assert content.startswith("---\n")
        assert "MAP-MANAGED" in content
        assert "# Actor Agent" in content

    def test_drift_detection_frontmatter(self, tmp_path):
        """Drift detection works with frontmatter-aware metadata position."""
        src = tmp_path / "agent.md"
        original = "---\nname: test\n---\n\n# Content"
        src.write_text(original)
        template_hash = compute_hash(original)

        dest = tmp_path / "dest.md"
        dest.write_text(inject_metadata(original, ".md", "1.0.0", template_hash))

        # No drift
        result = detect_drift(src, dest)
        assert not result.drifted

        # User modifies
        content = dest.read_text()
        dest.write_text(content.replace("# Content", "# Modified by user"))
        result = detect_drift(src, dest)
        assert result.drifted

    def test_frontmatter_eof_no_trailing_newline_roundtrip(self):
        """Regression: file ending with closing --- and no trailing newline.

        inject_metadata must not alter the 'clean' content hash for templates
        that end immediately after the closing frontmatter delimiter, otherwise
        detect_drift reports false positives and triggers unnecessary backups.
        """
        original = "---\nname: test\ndescription: edge case\n---"
        template_hash = compute_hash(original)

        injected = inject_metadata(original, ".md", "1.0.0", template_hash)
        meta, clean = extract_metadata(injected, ".md")

        assert meta is not None
        assert meta["template_hash"] == template_hash
        assert clean == original, (
            f"clean content differs from original after roundtrip: "
            f"{clean!r} != {original!r}"
        )
        assert compute_hash(clean) == template_hash

    def test_frontmatter_eof_no_trailing_newline_no_false_drift(self, tmp_path):
        """Regression: no false drift for frontmatter-at-EOF templates."""
        original = "---\nname: agent\n---"
        src = tmp_path / "agent.md"
        src.write_text(original)
        template_hash = compute_hash(original)

        dest = tmp_path / "dest.md"
        dest.write_text(inject_metadata(original, ".md", "1.0.0", template_hash))

        result = detect_drift(src, dest)
        assert (
            not result.drifted
        ), f"False drift detected for frontmatter-at-EOF template: {result.reason}"

    def test_frontmatter_with_trailing_newline_still_works(self):
        """Ensure fix doesn't break the normal case (trailing newline present)."""
        original = "---\nname: test\n---\n\n# Body content\n"
        template_hash = compute_hash(original)

        injected = inject_metadata(original, ".md", "1.0.0", template_hash)
        meta, clean = extract_metadata(injected, ".md")

        assert meta is not None
        assert clean == original
        assert compute_hash(clean) == template_hash


# ---------------------------------------------------------------------------
# ST-010 C2: Fence-aware merge tests
# ---------------------------------------------------------------------------

# Parametrize over all formats that get fence tokens.
_FENCE_FORMATS = [
    (".md", "<!-- map:start -->", "<!-- map:end -->"),
    (".py", "# map:start", "# map:end"),
    (".sh", "# map:start", "# map:end"),
    (".toml", "# map:start", "# map:end"),
]


def _src_body_for(ext: str) -> str:
    """Return a plausible template body string for the given extension."""
    bodies = {
        ".md": "# Managed heading\nSome managed content.\n",
        ".py": 'def hello():\n    print("hello")\n',
        ".sh": "#!/bin/sh\necho hello\n",
        ".toml": '[section]\nkey = "value"\n',
    }
    return bodies.get(ext, "managed content\n")


def _user_tail_for(ext: str) -> str:
    """Return sample user-added content below the fence."""
    tails = {
        ".md": "\n## My Custom Section\nUser-added notes.\n",
        ".py": "\n# My customisation\nmy_var = 42\n",
        ".sh": "\n# user additions\nexport MY_VAR=1\n",
        ".toml": "\n[my_section]\nmy_key = true\n",
    }
    return tails.get(ext, "\n# user content\n")


class TestFenceAwareMerge:
    """ST-010 fence-aware merge: VC1-VC5."""

    # ------------------------------------------------------------------ VC1
    @pytest.mark.parametrize("ext,start_tok,end_tok", _FENCE_FORMATS)
    def test_vc1_user_tail_preserved_byte_for_byte(
        self, tmp_path, ext: str, start_tok: str, end_tok: str
    ) -> None:
        """VC1 [INV-5]: re-copy refreshes managed region, user tail unchanged."""
        user_tail = _user_tail_for(ext)
        src_body_v1 = _src_body_for(ext)
        src_body_v2 = src_body_v1 + "# NEW LINE added to template\n"

        # --- first install (v1) ---
        src = tmp_path / f"tmpl{ext}"
        src.write_text(src_body_v1, encoding="utf-8")
        dest = tmp_path / f"dest{ext}"
        r1 = copy_managed_file(src, dest, "1.0.0")
        assert r1.success, f"First install failed: {r1.reason}"

        # Manually append user tail below the closing fence
        current = dest.read_text(encoding="utf-8")
        assert start_tok in current, "Opening fence token must be present after first install"
        assert end_tok in current, "Closing fence token must be present after first install"
        dest.write_text(current + user_tail, encoding="utf-8")

        # Snapshot the user tail bytes
        after_fence_snapshot = dest.read_text(encoding="utf-8").split(end_tok + "\n", 1)
        assert len(after_fence_snapshot) == 2, "Could not split on end_tok"
        user_section_before = after_fence_snapshot[1]

        # --- re-copy with changed template (v2) ---
        src.write_text(src_body_v2, encoding="utf-8")
        r2 = copy_managed_file(src, dest, "1.1.0")
        assert r2.success, f"Re-copy failed: {r2.reason}"

        dest_after = dest.read_text(encoding="utf-8")

        # Managed region must contain new line
        assert "NEW LINE added to template" in dest_after, (
            "Managed region was not refreshed with new template content"
        )

        # User tail must be byte-for-byte identical (INV-5)
        after_fence_after = dest_after.split(end_tok + "\n", 1)
        assert len(after_fence_after) == 2, "Closing fence token missing after re-copy"
        user_section_after = after_fence_after[1]
        assert user_section_after == user_section_before, (
            f"User tail changed after re-copy!\n"
            f"Before: {user_section_before!r}\n"
            f"After:  {user_section_after!r}"
        )

    # ------------------------------------------------------------------ VC2
    @pytest.mark.parametrize("ext,start_tok,end_tok", _FENCE_FORMATS)
    def test_vc2_correct_fence_tokens_emitted(
        self, tmp_path, ext: str, start_tok: str, end_tok: str
    ) -> None:
        """VC2 [SC-2]: correct per-format fence tokens appear; JSON gets no fence."""
        src = tmp_path / f"tmpl{ext}"
        src.write_text(_src_body_for(ext), encoding="utf-8")
        dest = tmp_path / f"dest{ext}"

        r = copy_managed_file(src, dest, "1.0.0")
        assert r.success

        content = dest.read_text(encoding="utf-8")
        assert start_tok in content, f"start token {start_tok!r} missing in {ext} output"
        assert end_tok in content, f"end token {end_tok!r} missing in {ext} output"

    def test_vc2_json_no_fence_uses_map_managed_key(self, tmp_path: Path) -> None:
        """VC2 [SC-2]: JSON uses _map_managed root key — no fence tokens."""
        src = tmp_path / "config.json"
        src.write_text(json.dumps({"key": "val"}), encoding="utf-8")
        dest = tmp_path / "out" / "config.json"

        r = copy_managed_file(src, dest, "1.0.0")
        assert r.success

        content = dest.read_text(encoding="utf-8")
        data = json.loads(content)
        assert "_map_managed" in data, "JSON must use _map_managed root key"
        # No fence tokens in JSON output
        assert "map:start" not in content
        assert "map:end" not in content

    def test_vc2_json_drift_creates_bak(self, tmp_path: Path) -> None:
        """VC2 [SC-2]: JSON drift → .bak.<ts> timestamped backup."""
        import time

        src = tmp_path / "config.json"
        original_data = {"key": "val"}
        src.write_text(json.dumps(original_data), encoding="utf-8")
        dest = tmp_path / "config.json"

        copy_managed_file(src, dest, "1.0.0")

        # User modifies JSON file
        data = json.loads(dest.read_text())
        data["user_key"] = "user_value"
        dest.write_text(json.dumps(data, indent=2), encoding="utf-8")

        time.sleep(1.1)  # ensure distinct timestamp

        r2 = copy_managed_file(src, dest, "1.1.0")
        assert r2.drifted
        assert r2.backed_up
        assert r2.backup_path is not None
        assert r2.backup_path.name.endswith(".bak")
        assert r2.backup_path.exists()

    # ------------------------------------------------------------------ VC3
    @pytest.mark.parametrize("ext,start_tok,end_tok", _FENCE_FORMATS)
    def test_vc3_legacy_unfenced_upgraded_to_fenced_silently(
        self, tmp_path, ext: str, start_tok: str, end_tok: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """VC3 [INV-T]: legacy unfenced file (metadata, no fence) is silently upgraded
        to the fenced layout — fence markers added, no alarming per-file stderr output,
        and the migration is one-time (idempotent on re-copy)."""
        src_body = _src_body_for(ext)
        src = tmp_path / f"tmpl{ext}"
        src.write_text(src_body, encoding="utf-8")
        dest = tmp_path / f"dest{ext}"

        # Simulate a legacy install: inject metadata but NO fence
        template_hash = compute_hash(src_body)
        phase_b_content = inject_metadata(src_body, ext, "1.0.0", template_hash)
        dest.write_text(phase_b_content, encoding="utf-8")

        # Re-copy: migration should complete by adding the fence
        r = copy_managed_file(src, dest, "1.1.0")
        assert r.success, f"legacy → fenced migration failed: {r.reason}"
        assert r.migrated, "result must flag the one-time legacy → fenced migration"

        content = dest.read_text(encoding="utf-8")
        assert "MAP-MANAGED" in content, "Metadata must be present after migration"
        # The migration must now write the fence markers (the whole point of the fix).
        assert start_tok in content, f"start fence {start_tok!r} missing after migration"
        assert end_tok in content, f"end fence {end_tok!r} missing after migration"
        # Check key lines of the managed body are present (shebang may be reordered)
        for line in src_body.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#!"):
                assert stripped in content, (
                    f"Body line {stripped!r} missing from migrated content"
                )

        # No alarming per-file notice should reach stderr — the upgrade is silent.
        stderr_out = capsys.readouterr().err
        assert "MIGRATION" not in stderr_out and "Phase B" not in stderr_out, (
            f"legacy upgrade must be silent; got stderr: {stderr_out!r}"
        )

        # Idempotent: a second copy now finds a proper fence (state == 'found'),
        # so it takes the normal merge path and does NOT re-migrate.
        r2 = copy_managed_file(src, dest, "1.1.0")
        assert r2.success
        assert not r2.migrated, "migration must be one-time, not repeated on every copy"
        assert capsys.readouterr().err == "", "re-copy of a fenced file must be silent"

    # ------------------------------------------------------------------ VC4
    @pytest.mark.parametrize("ext,start_tok,end_tok", _FENCE_FORMATS)
    def test_vc4_deleted_fence_user_owned_not_overwritten(
        self, tmp_path, ext: str, start_tok: str, end_tok: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """VC4 [D12]: deleted/malformed fence → user-owned, managed region not overwritten, warning emitted."""
        src_body = _src_body_for(ext)
        src = tmp_path / f"tmpl{ext}"
        src.write_text(src_body, encoding="utf-8")
        dest = tmp_path / f"dest{ext}"

        # First install to get a properly fenced file
        r1 = copy_managed_file(src, dest, "1.0.0")
        assert r1.success

        # User deletes the fence end marker (malformed: start present, end gone)
        content = dest.read_text(encoding="utf-8")
        assert start_tok in content, "Start fence token must be present after first install"
        assert end_tok in content, "End fence token must be present after first install"
        malformed = content.replace(end_tok, "")
        dest.write_text(malformed, encoding="utf-8")
        snapshot_before = dest.read_text(encoding="utf-8")

        # Re-copy must skip (user-owned)
        r2 = copy_managed_file(src, dest, "1.1.0")
        assert r2.success, "Result must be success=True (skipped, not hard error)"

        # File must NOT be overwritten
        content_after = dest.read_text(encoding="utf-8")
        assert content_after == snapshot_before, (
            "File content must NOT change when fence is malformed (D12)"
        )

        # Warning must appear on stderr
        stderr_out = capsys.readouterr().err
        assert "WARNING" in stderr_out or "malformed" in stderr_out.lower() or "user-owned" in stderr_out.lower(), (
            f"Warning expected in stderr; got: {stderr_out!r}"
        )

    @pytest.mark.parametrize("ext,start_tok,end_tok", _FENCE_FORMATS)
    def test_vc4_fence_merge_never_writes_outside_target(
        self, tmp_path, ext: str, start_tok: str, end_tok: str
    ) -> None:
        """VC4 / security: fence merge must never write to a path other than dest."""
        src = tmp_path / f"tmpl{ext}"
        src.write_text(_src_body_for(ext), encoding="utf-8")
        dest = tmp_path / f"dest{ext}"

        r = copy_managed_file(src, dest, "1.0.0")
        assert r.success

        # Fence tokens must appear in dest (confirms fence-aware merge ran correctly)
        content = dest.read_text(encoding="utf-8")
        assert start_tok in content, f"Start fence token {start_tok!r} missing from dest"
        assert end_tok in content, f"End fence token {end_tok!r} missing from dest"

        # List all files in tmp_path — only src and dest should exist
        all_files = list(tmp_path.rglob("*"))
        expected = {src, dest}
        unexpected = {f for f in all_files if f.is_file() and f not in expected}
        assert not unexpected, (
            f"Fence merge wrote unexpected files outside target: {unexpected}"
        )

    # ------------------------------------------------------------------ VC5
    @pytest.mark.parametrize("ext,start_tok,end_tok", _FENCE_FORMATS)
    def test_vc5_symlink_dest_refused(
        self, tmp_path, ext: str, start_tok: str, end_tok: str
    ) -> None:
        """VC5 [security]: write to symlink dest must be refused (O_NOFOLLOW guard)."""
        del start_tok, end_tok  # parametrized for format coverage; not needed in body
        src = tmp_path / f"tmpl{ext}"
        src.write_text(_src_body_for(ext), encoding="utf-8")

        # Create real target file and symlink to it
        real_target = tmp_path / f"real_target{ext}"
        real_target.write_text("real content\n", encoding="utf-8")
        symlink_dest = tmp_path / f"symlink{ext}"
        symlink_dest.symlink_to(real_target)

        # Attempt to copy to the symlink — must fail (success=False or raise)
        try:
            r = copy_managed_file(src, symlink_dest, "1.0.0")
            assert not r.success, (
                "copy_managed_file must refuse to write to a symlink dest"
            )
        except OSError:
            pass  # raising OSError is also acceptable

        # Real target must not have been modified
        assert real_target.read_text(encoding="utf-8") == "real content\n", (
            "Symlink target must not be modified when write to symlink is refused"
        )

    def test_vc5_no_write_outside_target_path_traversal(self, tmp_path: Path) -> None:
        """VC5 [security]: fence merge never writes outside the target file path."""
        src = tmp_path / "tmpl.md"
        src.write_text("# Managed content\n", encoding="utf-8")
        dest = tmp_path / "subdir" / "dest.md"

        r = copy_managed_file(src, dest, "1.0.0")
        assert r.success

        # Only dest and src should exist; no files written outside their directories
        all_files = list(tmp_path.rglob("*"))
        written = {f for f in all_files if f.is_file() and f != src}
        assert written == {dest}, (
            f"Expected only dest to be written; found: {written}"
        )

    # ------------------------------------------------------------------ INV-5 sentinel-in-tail
    @pytest.mark.parametrize("ext,start_tok,end_tok", _FENCE_FORMATS)
    def test_sentinel_in_tail_roundtrip(
        self, tmp_path: Path, ext: str, start_tok: str, end_tok: str
    ) -> None:
        """INV-5 data-loss fix: user tail containing literal fence sentinel lines
        must survive re-copy byte-for-byte.

        Regression: naive end_indices[-1] would mis-identify the sentinel in the
        user tail as the closing fence boundary, dropping or duplicating user content.
        """
        src_body_v1 = _src_body_for(ext)
        src_body_v2 = src_body_v1 + "# NEW LINE added to template\n"

        # Build a user tail that contains BOTH sentinel lines verbatim.
        # This is realistic: a markdown file documenting MAP fence syntax, a shell
        # heredoc, or a .toml comment block.
        sentinel_tail = (
            "\n# Below is user content that documents fence syntax:\n"
            f"{start_tok}\n"
            "some user content\n"
            f"{end_tok}\n"
            "more user content after\n"
        )

        # --- first install ---
        src = tmp_path / f"tmpl{ext}"
        src.write_text(src_body_v1, encoding="utf-8")
        dest = tmp_path / f"dest{ext}"
        r1 = copy_managed_file(src, dest, "1.0.0")
        assert r1.success, f"First install failed: {r1.reason}"

        # Append the sentinel-containing user tail below the closing fence
        current = dest.read_text(encoding="utf-8")
        assert end_tok in current, "Closing fence token must be present after first install"
        dest.write_text(current + sentinel_tail, encoding="utf-8")

        # Snapshot the exact bytes of the user tail
        full_before = dest.read_text(encoding="utf-8")
        # The closing fence appears FIRST; split on it to isolate user tail
        parts = full_before.split(end_tok + "\n", 1)
        assert len(parts) == 2, "Could not locate closing fence in seeded file"
        user_tail_before = parts[1]
        assert start_tok in user_tail_before, (
            "Test setup error: start sentinel not in user tail"
        )
        assert end_tok in user_tail_before, (
            "Test setup error: end sentinel not in user tail"
        )

        # --- re-copy with changed template ---
        src.write_text(src_body_v2, encoding="utf-8")
        r2 = copy_managed_file(src, dest, "1.1.0")
        assert r2.success, f"Re-copy failed: {r2.reason}"

        dest_after = dest.read_text(encoding="utf-8")

        # Managed region must be updated
        assert "NEW LINE added to template" in dest_after, (
            "Managed region was not refreshed"
        )

        # User tail must be byte-for-byte identical (INV-5)
        parts_after = dest_after.split(end_tok + "\n", 1)
        assert len(parts_after) == 2, "Closing fence token missing after re-copy"
        user_tail_after = parts_after[1]
        assert user_tail_after == user_tail_before, (
            f"User tail changed after re-copy (INV-5 violation)!\n"
            f"Before: {user_tail_before!r}\n"
            f"After:  {user_tail_after!r}"
        )

    # ------------------------------------------------------------------ INV-5 malformed: duplicate start
    @pytest.mark.parametrize("ext,start_tok,end_tok", _FENCE_FORMATS)
    def test_duplicate_start_before_end_is_malformed(
        self,
        tmp_path: Path,
        ext: str,
        start_tok: str,
        end_tok: str,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """D12: a file with two standalone start lines before the end is malformed →
        treated as user-owned (content unchanged), warning emitted."""
        src = tmp_path / f"tmpl{ext}"
        src.write_text(_src_body_for(ext), encoding="utf-8")
        dest = tmp_path / f"dest{ext}"

        # First install to get a well-formed fenced file
        r1 = copy_managed_file(src, dest, "1.0.0")
        assert r1.success

        # Corrupt the managed region by injecting a second standalone start token
        content = dest.read_text(encoding="utf-8")
        # Insert a duplicate start_tok line just before the real end_tok
        corrupted = content.replace(
            end_tok,
            f"{start_tok}\n{end_tok}",
            1,
        )
        dest.write_text(corrupted, encoding="utf-8")
        snapshot_before = dest.read_text(encoding="utf-8")

        # Re-copy must treat as user-owned (D12)
        r2 = copy_managed_file(src, dest, "1.1.0")
        assert r2.success, "D12 skip must still report success=True (not hard error)"

        content_after = dest.read_text(encoding="utf-8")
        assert content_after == snapshot_before, (
            "File must NOT be overwritten when duplicate start marker found (D12)"
        )

        stderr_out = capsys.readouterr().err
        assert (
            "WARNING" in stderr_out
            or "malformed" in stderr_out.lower()
            or "user-owned" in stderr_out.lower()
        ), f"Warning expected in stderr for malformed fence; got: {stderr_out!r}"

    # ------------------------------------------------------------------ INV-5 missing end
    @pytest.mark.parametrize("ext,start_tok,end_tok", _FENCE_FORMATS)
    def test_missing_end_after_start_is_malformed(
        self,
        tmp_path: Path,
        ext: str,
        start_tok: str,
        end_tok: str,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """D12: a file whose end marker was moved ABOVE the start (or absent) is
        treated as user-owned — content unchanged, warning emitted."""
        del start_tok  # parametrize tuple param; unused in this case (pytest matches positionally)
        src = tmp_path / f"tmpl{ext}"
        src.write_text(_src_body_for(ext), encoding="utf-8")
        dest = tmp_path / f"dest{ext}"

        r1 = copy_managed_file(src, dest, "1.0.0")
        assert r1.success

        # Remove the end marker entirely so no end exists after start
        content = dest.read_text(encoding="utf-8")
        broken = content.replace(end_tok, "")
        dest.write_text(broken, encoding="utf-8")
        snapshot_before = dest.read_text(encoding="utf-8")

        r2 = copy_managed_file(src, dest, "1.1.0")
        assert r2.success, "D12 skip must be success=True"
        assert dest.read_text(encoding="utf-8") == snapshot_before, (
            "File must NOT change when end marker is absent (D12)"
        )
        stderr_out = capsys.readouterr().err
        assert (
            "WARNING" in stderr_out
            or "malformed" in stderr_out.lower()
            or "user-owned" in stderr_out.lower()
        ), f"Warning expected in stderr; got: {stderr_out!r}"

    # ------------------------------------------------------------------ Regression guard
    def test_existing_extract_inject_detect_drift_unchanged(self, tmp_path: Path) -> None:
        """Confirm extract_metadata / inject_metadata / detect_drift behavior is unchanged."""
        original = "# Hello World\nSome content.\n"
        injected = inject_metadata(original, ".md", "2.0.0", "hashxyz")
        meta, clean = extract_metadata(injected, ".md")

        assert meta is not None
        assert meta["mapify_version"] == "2.0.0"
        assert meta["template_hash"] == "hashxyz"
        assert clean == original

        # detect_drift on a fresh install (dest absent)
        src = tmp_path / "src.md"
        src.write_text(original)
        dest = tmp_path / "dest.md"
        dr = detect_drift(src, dest)
        assert dr.first_install
        assert not dr.drifted

        # detect_drift on unmodified file
        dest.write_text(inject_metadata(original, ".md", "2.0.0", compute_hash(original)))
        dr2 = detect_drift(src, dest)
        assert not dr2.drifted
