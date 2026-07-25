"""Tests for src/mapify_cli/tool_output_offload.py (GitHub issue #232)."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from mapify_cli.tool_output_offload import (
    DENYLIST_TOOLS,
    DISCOVERY_MIN_CHARS,
    INDEX_SCHEMA_VERSION,
    LARGE_ANY_CHARS,
    build_manifest,
    extract_tool_outputs,
    offload_transcript_tool_outputs,
    recovery_pointer_text,
    should_offload,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _tool_use(tid: str, name: str, tool_input: dict) -> dict:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": tid, "name": name, "input": tool_input}
            ],
        },
    }


def _tool_result(tid: str, body: str) -> dict:
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tid,
                    "content": [{"type": "text", "text": body}],
                }
            ],
        },
    }


def _write_transcript(path: Path, entries: list[dict]) -> Path:
    path.write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8"
    )
    return path


def _pair(tid: str, name: str, tool_input: dict, body: str) -> list[dict]:
    return [_tool_use(tid, name, tool_input), _tool_result(tid, body)]


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


class TestShouldOffload:
    def test_large_body_any_tool_offloaded(self):
        assert should_offload("WebFetch", LARGE_ANY_CHARS) is True

    def test_small_body_skipped_even_for_discovery_tool(self):
        assert should_offload("Bash", 499) is False
        assert should_offload("Bash", DISCOVERY_MIN_CHARS - 1) is False

    def test_medium_discovery_tool_offloaded(self):
        assert should_offload("Bash", DISCOVERY_MIN_CHARS) is True
        assert should_offload("Grep", DISCOVERY_MIN_CHARS + 1) is True

    def test_medium_non_discovery_tool_skipped(self):
        # Between DISCOVERY_MIN and LARGE_ANY, non-discovery tools are skipped.
        assert should_offload("WebFetch", DISCOVERY_MIN_CHARS + 1) is False

    @pytest.mark.parametrize("tool", sorted(DENYLIST_TOOLS))
    def test_denylist_never_offloaded(self, tool):
        assert should_offload(tool, LARGE_ANY_CHARS * 10) is False


# ---------------------------------------------------------------------------
# Transcript parsing
# ---------------------------------------------------------------------------


class TestExtractToolOutputs:
    def test_pairs_tool_use_with_result(self, tmp_path):
        t = _write_transcript(
            tmp_path / "t.jsonl",
            _pair("toolu_1", "Bash", {"command": "grep -r TODO src/"}, "hit\n" * 5),
        )
        outputs = extract_tool_outputs(t)
        assert len(outputs) == 1
        assert outputs[0].tool_use_id == "toolu_1"
        assert outputs[0].tool_name == "Bash"
        assert outputs[0].input_summary == "grep -r TODO src/"
        assert outputs[0].body == "hit\n" * 5

    def test_string_content_result(self, tmp_path):
        entries = [
            _tool_use("toolu_x", "Read", {"file_path": "/a/b.py"}),
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "toolu_x", "content": "raw body"}
                    ],
                },
            },
        ]
        outputs = extract_tool_outputs(_write_transcript(tmp_path / "t.jsonl", entries))
        assert outputs[0].body == "raw body"
        assert outputs[0].input_summary == "/a/b.py"

    def test_missing_metadata_defaults_to_unknown(self, tmp_path):
        # tool_result with no preceding tool_use → name unknown, still extracted.
        t = _write_transcript(tmp_path / "t.jsonl", [_tool_result("orphan", "body")])
        outputs = extract_tool_outputs(t)
        assert len(outputs) == 1
        assert outputs[0].tool_name == "unknown"

    def test_malformed_lines_skipped(self, tmp_path):
        path = tmp_path / "t.jsonl"
        good = _pair("toolu_1", "Bash", {"command": "ls"}, "x")
        path.write_text(
            "not json\n" + json.dumps(good[0]) + "\n{ broken\n" + json.dumps(good[1]) + "\n",
            encoding="utf-8",
        )
        outputs = extract_tool_outputs(path)
        assert len(outputs) == 1

    def test_missing_file_returns_empty(self, tmp_path):
        assert extract_tool_outputs(tmp_path / "nope.jsonl") == []

    def test_duplicate_tool_use_id_first_body_wins(self, tmp_path):
        entries = [
            _tool_use("toolu_1", "Bash", {"command": "ls"}),
            _tool_result("toolu_1", "first"),
            _tool_result("toolu_1", "second"),
        ]
        outputs = extract_tool_outputs(_write_transcript(tmp_path / "t.jsonl", entries))
        assert len(outputs) == 1
        assert outputs[0].body == "first"


# ---------------------------------------------------------------------------
# Offload end-to-end
# ---------------------------------------------------------------------------


class TestOffload:
    def _big(self, marker: str) -> str:
        return marker + ("x" * (LARGE_ANY_CHARS + 10))

    def test_offloads_large_skips_small(self, tmp_path):
        branch_dir = tmp_path / ".map" / "br"
        branch_dir.mkdir(parents=True)
        entries = (
            _pair("toolu_big", "Bash", {"command": "grep -r X"}, self._big("BIG"))
            + _pair("toolu_small", "Bash", {"command": "echo hi"}, "tiny")
        )
        t = _write_transcript(tmp_path / "t.jsonl", entries)

        summary = offload_transcript_tool_outputs(t, branch_dir)

        assert summary.written == 1
        assert summary.written_ids == ["toolu_big"]
        compacted = branch_dir / "compacted"
        sidecars = list(compacted.glob("Bash-*.txt"))
        assert len(sidecars) == 1
        text = sidecars[0].read_text(encoding="utf-8")
        assert "BIG" in text
        assert "# map:offloaded tool_use_id=toolu_big" in text
        assert "Authority:" in text

    def test_full_body_preserved_not_truncated(self, tmp_path):
        branch_dir = tmp_path / ".map" / "br"
        branch_dir.mkdir(parents=True)
        body = "LINE\n" * (LARGE_ANY_CHARS // 4)  # well over 1000 chars
        t = _write_transcript(
            tmp_path / "t.jsonl", _pair("toolu_1", "Read", {"file_path": "/big.py"}, body)
        )
        offload_transcript_tool_outputs(t, branch_dir)
        sidecar = next((branch_dir / "compacted").glob("Read-*.txt"))
        assert body in sidecar.read_text(encoding="utf-8")

    def test_index_record_shape(self, tmp_path):
        branch_dir = tmp_path / ".map" / "br"
        branch_dir.mkdir(parents=True)
        t = _write_transcript(
            tmp_path / "t.jsonl",
            _pair("toolu_1", "Grep", {"pattern": "needle"}, self._big("G")),
        )
        offload_transcript_tool_outputs(t, branch_dir)
        index = (branch_dir / "compacted" / "index.ndjson").read_text().splitlines()
        assert len(index) == 1
        rec = json.loads(index[0])
        assert rec["schema_version"] == INDEX_SCHEMA_VERSION
        assert rec["tool_use_id"] == "toolu_1"
        assert rec["tool"] == "Grep"
        assert rec["input_summary"] == "needle"
        assert rec["bytes"] >= LARGE_ANY_CHARS
        assert rec["sidecar"].startswith("Grep-")
        assert rec["saved_at"]

    def test_dedup_idempotent_across_runs(self, tmp_path):
        branch_dir = tmp_path / ".map" / "br"
        branch_dir.mkdir(parents=True)
        t = _write_transcript(
            tmp_path / "t.jsonl",
            _pair("toolu_1", "Bash", {"command": "grep X"}, self._big("A")),
        )
        first = offload_transcript_tool_outputs(t, branch_dir)
        second = offload_transcript_tool_outputs(t, branch_dir)
        assert first.written == 1
        assert second.written == 0
        assert second.skipped_existing == 1
        # index has exactly one line; one sidecar on disk.
        index = (branch_dir / "compacted" / "index.ndjson").read_text().splitlines()
        assert len(index) == 1
        assert len(list((branch_dir / "compacted").glob("Bash-*.txt"))) == 1

    def test_no_candidates_creates_no_directory(self, tmp_path):
        branch_dir = tmp_path / ".map" / "br"
        branch_dir.mkdir(parents=True)
        t = _write_transcript(
            tmp_path / "t.jsonl", _pair("toolu_1", "Bash", {"command": "echo"}, "tiny")
        )
        summary = offload_transcript_tool_outputs(t, branch_dir)
        assert summary.written == 0
        assert not (branch_dir / "compacted").exists()

    def test_gitignore_written_on_creation(self, tmp_path):
        branch_dir = tmp_path / ".map" / "br"
        branch_dir.mkdir(parents=True)
        t = _write_transcript(
            tmp_path / "t.jsonl",
            _pair("toolu_1", "Bash", {"command": "grep X"}, self._big("A")),
        )
        offload_transcript_tool_outputs(t, branch_dir)
        gitignore = branch_dir / "compacted" / ".gitignore"
        assert gitignore.exists()
        assert gitignore.read_text().strip().endswith("*")

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
    def test_sidecar_is_chmod_0600(self, tmp_path):
        branch_dir = tmp_path / ".map" / "br"
        branch_dir.mkdir(parents=True)
        t = _write_transcript(
            tmp_path / "t.jsonl",
            _pair("toolu_1", "Bash", {"command": "grep X"}, self._big("A")),
        )
        offload_transcript_tool_outputs(t, branch_dir)
        sidecar = next((branch_dir / "compacted").glob("Bash-*.txt"))
        mode = stat.S_IMODE(sidecar.stat().st_mode)
        assert mode == 0o600

    def test_cap_evicts_oldest_fifo(self, tmp_path):
        branch_dir = tmp_path / ".map" / "br"
        branch_dir.mkdir(parents=True)
        entries: list[dict] = []
        for i in range(4):
            entries += _pair(
                f"toolu_{i}", "Bash", {"command": f"grep {i}"}, self._big(f"M{i}")
            )
        t = _write_transcript(tmp_path / "t.jsonl", entries)

        summary = offload_transcript_tool_outputs(t, branch_dir, max_files=2)

        assert summary.written == 4
        assert summary.evicted == 2
        index = (branch_dir / "compacted" / "index.ndjson").read_text().splitlines()
        ids = [json.loads(line)["tool_use_id"] for line in index]
        assert ids == ["toolu_2", "toolu_3"]  # oldest two evicted
        remaining = {p.name for p in (branch_dir / "compacted").glob("Bash-*.txt")}
        assert len(remaining) == 2
        evictions = (branch_dir / "compacted" / ".evictions.log").read_text()
        assert "evicted" in evictions

    def test_manifest_built_and_lists_entries(self, tmp_path):
        branch_dir = tmp_path / ".map" / "br"
        branch_dir.mkdir(parents=True)
        t = _write_transcript(
            tmp_path / "t.jsonl",
            _pair("toolu_1", "Grep", {"pattern": "needle"}, self._big("G")),
        )
        offload_transcript_tool_outputs(t, branch_dir)
        manifest = (branch_dir / "compacted" / "MANIFEST.md").read_text()
        assert "Offloaded tool outputs" in manifest
        assert "needle" in manifest
        assert "Grep-" in manifest
        assert "live source" in manifest.lower()

    def test_build_manifest_none_when_empty(self, tmp_path):
        compacted = tmp_path / "compacted"
        compacted.mkdir()
        assert build_manifest(compacted) is None


# ---------------------------------------------------------------------------
# Recovery pointer
# ---------------------------------------------------------------------------


class TestRecoveryPointer:
    def test_none_when_nothing_offloaded(self, tmp_path):
        branch_dir = tmp_path / ".map" / "br"
        branch_dir.mkdir(parents=True)
        assert recovery_pointer_text("br", branch_dir) is None

    def test_pointer_after_offload(self, tmp_path):
        branch_dir = tmp_path / ".map" / "br"
        branch_dir.mkdir(parents=True)
        t = _write_transcript(
            tmp_path / "t.jsonl",
            _pair("toolu_1", "Bash", {"command": "grep X"}, "x" * (LARGE_ANY_CHARS + 1)),
        )
        offload_transcript_tool_outputs(t, branch_dir)
        pointer = recovery_pointer_text("br", branch_dir)
        assert pointer is not None
        assert ".map/br/compacted/MANIFEST.md" in pointer
        assert "do not" not in pointer.lower() or "instead of re-running" in pointer
        assert "live source" in pointer.lower()
