"""Tests for drift-aware managed file copier (Step 3).

Tests metadata injection, extraction, drift detection, and copy_managed_file().
"""

import json
import sys
from pathlib import Path


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
        meta, clean = extract_metadata(src, ".json")
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
        first_content = dest.read_text()

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

    def test_yaml_file_no_metadata(self, tmp_path):
        src = tmp_path / "config.yaml"
        src.write_text("key: value\n")
        dest = tmp_path / "output" / "config.yaml"

        result = copy_managed_file(src, dest, "3.5.0")
        assert result.success
        assert "MAP-MANAGED" not in dest.read_text()  # yaml not supported yet


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
        report.results.append(
            CopyResult(src=Path("c"), dest=Path("d"), drifted=False)
        )
        assert report.has_drift
        assert len(report.drifted_files) == 1
        assert len(report.backed_up_files) == 1
