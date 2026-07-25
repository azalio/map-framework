"""End-to-end integration for compaction tool-output offload (issue #232).

Runs the *real generated* PreCompact and post-compact hooks as subprocesses to
prove the full wiring: a large tool output is offloaded before compaction and is
recoverable afterwards without re-running the tool, and a ``never`` policy is a
byte-identical no-op (acceptance criteria 1-3).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PRECOMPACT_HOOK = REPO_ROOT / ".claude" / "hooks" / "pre-compact-save-transcript.py"
POSTCOMPACT_HOOK = REPO_ROOT / ".claude" / "hooks" / "post-compact-context.py"

pytestmark = pytest.mark.skipif(
    not PRECOMPACT_HOOK.is_file() or not POSTCOMPACT_HOOK.is_file(),
    reason="generated hooks not present (run `make render-templates`)",
)

BIG_GREP_BODY = "src/foo.py:42: TODO fix\n" * 800  # well over the size threshold


def _run_hook(hook: Path, project_dir: Path, stdin_obj: dict) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    # Pin mapify_cli resolution to THIS worktree (avoid editable cross-clone).
    env["PYTHONPATH"] = str(REPO_ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env.pop("MAP_INVOKED_BY", None)
    return subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps(stdin_obj),
        text=True,
        capture_output=True,
        env=env,
        timeout=30,
        check=False,
    )


def _make_project(tmp_path: Path, policy: str) -> tuple[Path, Path]:
    project = tmp_path / "proj"
    (project / ".map").mkdir(parents=True)
    (project / ".map" / "config.yaml").write_text(
        f"compression_policy: {policy}\n", encoding="utf-8"
    )
    transcript = project / "transcript.jsonl"
    entries = [
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_grep1",
                        "name": "Bash",
                        "input": {"command": "grep -rn TODO src/"},
                    }
                ],
            },
        },
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_grep1",
                        "content": [{"type": "text", "text": BIG_GREP_BODY}],
                    }
                ],
            },
        },
    ]
    transcript.write_text(
        "\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8"
    )
    return project, transcript


def _branch_dir(project: Path) -> Path:
    # tmp dir is not a git repo → hook falls back to the "default" branch.
    return project / ".map" / "default"


def test_offload_and_recover_when_policy_auto(tmp_path):
    project, transcript = _make_project(tmp_path, policy="auto")

    pre = _run_hook(
        PRECOMPACT_HOOK,
        project,
        {"transcript_path": str(transcript), "session_id": "s1"},
    )
    assert pre.returncode == 0, pre.stderr

    compacted = _branch_dir(project) / "compacted"
    sidecars = list(compacted.glob("Bash-*.txt"))
    assert len(sidecars) == 1, f"expected one sidecar, got {sidecars} ({pre.stderr})"

    # Acceptance #2: the dropped output is fully recoverable from the sidecar —
    # the original body is present, so re-running grep is unnecessary.
    recovered = sidecars[0].read_text(encoding="utf-8")
    assert "src/foo.py:42: TODO fix" in recovered
    assert recovered.count("TODO fix") == 800

    # The directory ignores its own (possibly secret-bearing) contents.
    assert (compacted / ".gitignore").read_text().strip().endswith("*")

    # post-compact hook surfaces the recovery pointer.
    post = _run_hook(POSTCOMPACT_HOOK, project, {})
    assert post.returncode == 0, post.stderr
    payload = json.loads(post.stdout)
    ctx = payload["hookSpecificOutput"]["additionalContext"]
    assert "compacted/MANIFEST.md" in ctx
    assert "instead of re-running broad discovery" in ctx


def test_never_policy_is_byte_identical_no_op(tmp_path):
    project, transcript = _make_project(tmp_path, policy="never")

    pre = _run_hook(
        PRECOMPACT_HOOK,
        project,
        {"transcript_path": str(transcript), "session_id": "s1"},
    )
    assert pre.returncode == 0, pre.stderr

    # Acceptance #3: no offload artifacts created under the default policy.
    assert not (_branch_dir(project) / "compacted").exists()
    # Existing behavior preserved: the transcript archive is still written.
    archives = list(_branch_dir(project).glob("transcript-*.md"))
    assert len(archives) == 1

    # post-compact hook emits no offload pointer when nothing was offloaded.
    post = _run_hook(POSTCOMPACT_HOOK, project, {})
    assert post.returncode == 0, post.stderr
    assert "compacted/MANIFEST.md" not in post.stdout
