"""Throwaway-cwd seeding for trajectory outcome eval.

Promotes ``spike_runner.seed_temp`` into a maintained module so the shipped
trajectory runner can seed an isolated project: ``.claude/`` + ``.map/scripts``
+ the fixture repo + git baseline.  ``--variant bad`` degrades the SEEDED copy
only (production templates are never touched, INV-5).

The degradation helpers (``degrade_body`` / ``degrade_actor`` /
``degrade_monitor``) are the Body-Bad levers reused from the spike for the
metric-validity check (Body-Good vs Body-Bad discrimination).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from mapify_cli.skills_eval.dispatcher import _apply_temp_flip


def git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run git in *cwd* without raising (mirrors spike_runner._git)."""
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
    )


def _copytree_overlay(src: Path, dst: Path) -> None:
    """Overlay *src* onto *dst* (dirs created, files overwritten)."""
    for item in src.rglob("*"):
        rel = item.relative_to(src)
        target = dst / rel
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


# ---------------------------------------------------------------------------
# Body-Bad degradation helpers (throwaway seed only)
# ---------------------------------------------------------------------------

_BODY_DROP_HEADERS = (
    "## When Not To Expand Scope",
    "## Mutation Boundary Constraints",
)


def degrade_body(skill_md: Path) -> None:
    """Strip the scope-discipline / mutation-boundary sections (Body-Bad).

    Throws away the seeded copy only.  Mirrors ``spike_runner._make_bad_body``.
    """
    if not skill_md.exists():
        return
    text = skill_md.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        if stripped in _BODY_DROP_HEADERS:
            skipping = True
            continue
        if skipping:
            if stripped.startswith("## ") or stripped == "---":
                skipping = False
                out.append(line)
            continue
        out.append(line)
    skill_md.write_text("".join(out), encoding="utf-8")


def degrade_actor(actor_md: Path) -> None:
    """Strip the ACTOR's scope discipline (Body-Bad/actor ablation).

    Mirrors ``spike_runner._degrade_actor``.
    """
    if not actor_md.exists():
        return
    lines = actor_md.read_text(encoding="utf-8").splitlines(keepends=True)
    out: list[str] = []
    skipping = False
    for line in lines:
        s = line.strip()
        if s == "## Mutation Boundary Constraints":
            skipping = True
            continue
        if skipping:
            if s.startswith(("### ", "# ")) or s == "---":
                skipping = False
                out.append(line)
            continue
        if "NEVER: Modify outside" in line:
            line = line.replace("Modify outside {{allowed_scope}} | ", "")
        out.append(line)
    actor_md.write_text("".join(out), encoding="utf-8")


def degrade_monitor(monitor_md: Path) -> None:
    """Best-effort drop of MONITOR scope-enforcement lines (Body-Bad/monitor).

    Mirrors ``spike_runner._degrade_monitor``.
    """
    if not monitor_md.exists():
        return
    keys = (
        "mutation boundary",
        "out-of-scope",
        "out of scope",
        "unrelated file",
        "scope expansion",
        "scope violation",
    )
    kept = [
        ln
        for ln in monitor_md.read_text(encoding="utf-8").splitlines(keepends=True)
        if not any(k in ln.lower() for k in keys)
    ]
    monitor_md.write_text("".join(kept), encoding="utf-8")


def set_agent_model(agent_md: Path, model: str) -> None:
    """Rewrite the ``model:`` frontmatter of a seeded agent (model lever).

    Mirrors ``spike_runner._set_agent_model``.
    """
    if not agent_md.exists():
        return
    lines = agent_md.read_text(encoding="utf-8").splitlines(keepends=True)
    out: list[str] = []
    replaced = False
    in_fm = False
    fm_marker_seen = 0
    for line in lines:
        if line.strip() == "---":
            fm_marker_seen += 1
            in_fm = fm_marker_seen == 1
            out.append(line)
            continue
        if in_fm and not replaced and line.lstrip().startswith("model:"):
            indent = line[: len(line) - len(line.lstrip())]
            out.append(f"{indent}model: {model}\n")
            replaced = True
            continue
        out.append(line)
    if not replaced:
        new_out: list[str] = []
        inserted = False
        for line in out:
            new_out.append(line)
            if not inserted and line.strip() == "---":
                new_out.append(f"model: {model}\n")
                inserted = True
        out = new_out
    agent_md.write_text("".join(out), encoding="utf-8")


# ---------------------------------------------------------------------------
# seed_temp
# ---------------------------------------------------------------------------


def seed_temp(
    fixture_dir: Path,
    *,
    repo_root: Path,
    variant: str = "good",
    degrade: str = "body",
    agent_models: dict[str, str] | None = None,
) -> Path:
    """Create a throwaway cwd seeded for one trajectory run.

    Layers (in order):
    1. ``.claude/`` (skills + agents + settings) from *repo_root*, TEMP-FLIP
       applied so the skill is invocable.
    2. Per-agent ``model:`` override (the execution-model lever).
    3. ``.map/scripts/`` (orchestrator + step runner the body shells out to).
    4. The fixture repo (``repo/`` overlay incl. ``.map/<branch>/`` plan).
    5. Body-Bad degradation on the SEEDED copy (variant == "bad") only.
    6. ``git init`` + baseline commit (scope-diff baseline + BRANCH resolution).

    Caller owns cleanup (``shutil.rmtree(tmp, ignore_errors=True)``).
    """
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="trajeval-"))
    # 1. .claude
    shutil.copytree(repo_root / ".claude", tmp / ".claude")
    _apply_temp_flip(tmp / ".claude")
    # 2. per-agent execution-model override
    for agent, model in (agent_models or {}).items():
        set_agent_model(tmp / ".claude" / "agents" / f"{agent}.md", model)
    # 3. .map/scripts
    (tmp / ".map").mkdir(parents=True, exist_ok=True)
    shutil.copytree(repo_root / ".map" / "scripts", tmp / ".map" / "scripts")
    # 4. fixture repo overlay
    _copytree_overlay(fixture_dir / "repo", tmp)
    # 5. variant degradation (seeded copy only)
    if variant == "bad":
        if degrade == "actor":
            degrade_actor(tmp / ".claude" / "agents" / "actor.md")
        elif degrade == "monitor":
            degrade_monitor(tmp / ".claude" / "agents" / "monitor.md")
        else:  # "body"
            degrade_body(tmp / ".claude" / "skills" / "map-task" / "SKILL.md")
    # 6. git baseline
    git(tmp, "init", "-q", "-b", "main")
    git(tmp, "add", "-A")
    git(tmp, "-c", "user.email=e@e", "-c", "user.name=n", "commit", "-qm", "seed")
    return tmp
