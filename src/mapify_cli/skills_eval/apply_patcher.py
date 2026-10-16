"""Apply a provider-specific winner without modifying the opposite skill."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import TypedDict


class _JournalEntry(TypedDict):
    path: str
    exists: bool
    mode: int
    backup: str


def _plain_description(text: str, winner: str) -> str:
    """Replace one complete, supported YAML description scalar."""
    if not text.startswith("---\n") or "\n---" not in text:
        raise ValueError("No YAML frontmatter found or no closing '---'")
    end = text.index("\n---", 4)
    lines = text[4:end].splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.startswith("description:")]
    if len(starts) != 1:
        raise ValueError("Expected exactly one description key")
    i = starts[0]
    scalar = lines[i].split(":", 1)[1].strip()
    if not scalar or scalar.startswith(("[", "{", "&", "*")):
        raise ValueError("Unsupported description scalar")
    j = i + 1
    while j < len(lines) and (not lines[j].strip() or lines[j].startswith((" ", "\t"))):
        j += 1
    if j > i + 1 and scalar not in ("|", "|-", "|+", ">", ">-", ">+"):
        raise ValueError("Unsupported multiline description scalar")
    while j > i + 1 and not lines[j - 1].strip():
        j -= 1
    replacement = "description: |-\n" + "".join("  " + line + "\n" for line in winner.split("\n"))
    header = "".join(lines[:i]) + replacement + "".join(lines[j:])
    return "---\n" + header.rstrip("\n") + text[end:]


def patch_skill_description(skill_md_path: Path, new_description: str) -> None:
    """Preserved plain YAML API; validate fully before the single write."""
    text = skill_md_path.read_text(encoding="utf-8")
    patched = _plain_description(text, new_description)
    _atomic_bytes(skill_md_path, patched.encode(), stat.S_IMODE(skill_md_path.stat().st_mode))


def _provider_description(text: str, winner: str, provider: str) -> str:
    """Bounded provider-header contract, not a general Jinja source parser."""
    from mapify_cli.delivery.template_renderer import get_environment
    from mapify_cli.skill_ir import parse_frontmatter

    if not text.startswith("---\n") or "\n---\n" not in text:
        raise ValueError("Unsupported description structure: missing frontmatter")
    header, body = text[4:].split("\n---\n", 1)
    for directive in re.findall(r"\[%.*?%\]", header, flags=re.DOTALL):
        token = directive[2:-2].strip().strip("-").strip()
        if token not in ("else", "endif") and not re.fullmatch(
            r"if PROVIDER == ([\"'])(?:claude|codex)\1|set cmd = \"/\" if PROVIDER == \"claude\" else \"\$\"", token
        ):
            raise ValueError(f"Unsupported description directive: {directive}")
    if re.search(r"<%(?!\s*cmd\s*%>)|\[#", header):
        raise ValueError("Unsupported description expression")
    if any(t in winner for t in ("[%", "<%", "[#")) or not winner.strip():
        raise ValueError("Unsupported winner description")
    env = get_environment()
    rendered = env.from_string("---\n" + header + "\n---\n").render(PROVIDER=provider)
    parse_frontmatter(rendered.split("---", 2)[1])
    patched = _plain_description(rendered, winner)
    parsed = parse_frontmatter(patched.split("---", 2)[1])
    if parsed.get("description") != winner:
        raise ValueError("Unsupported description structure: winner did not round-trip")
    opposite = "codex" if provider == "claude" else "claude"
    original_other = env.from_string("---\n" + header + "\n---\n").render(PROVIDER=opposite)
    # Independent provider descriptions have unambiguous scalar spans. Edit
    # only the selected block, retaining every other source byte.
    branches = list(re.finditer(r'\[% if PROVIDER == ([\"\'])(claude|codex)\1 %\]description:', header))
    for branch in branches:
        stop = header.find("[% endif", branch.end())
        alternate = header.find("[% else %]description:", branch.end(), stop)
        if alternate < 0:
            continue
        first = branch.end() - len("description:")
        second = alternate + len("[% else %]")
        start, limit = (first, alternate) if provider == branch.group(2) else (second, stop)
        segment = header[start:limit]
        patched_segment = _plain_description("---\n" + segment + "\n---\n", winner)[4:-5]
        if segment.endswith("\n"):
            patched_segment += "\n"
        candidate_header = header[:start] + patched_segment + header[limit:]
        result = "---\n" + candidate_header + "\n---\n" + body
        if env.from_string("---\n" + candidate_header + "\n---\n").render(PROVIDER=opposite) != original_other:
            raise ValueError("Unsupported conditional description whitespace")
        return result
    binding = '[% set cmd = "/" if PROVIDER == "claude" else "$" -%]'
    combined = ("---\n" + binding + f'[% if PROVIDER == "{provider}" %]'
                + patched[4:-4] + "[% else %]" + original_other[4:-4] + "[% endif -%]\n---\n")
    if env.from_string(combined).render(PROVIDER=opposite) != original_other:
        raise ValueError("Unsupported description whitespace structure")
    return combined + body


def _atomic_bytes(path: Path, data: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".mapify-apply-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        Path(name).unlink(missing_ok=True)


def _recover_transaction(root: Path) -> None:
    journal = root / ".map/skill-eval-apply-transaction"
    manifest = journal / "manifest.json"
    if any(p.is_symlink() for p in (journal, journal.parent, manifest)):
        raise ValueError(f"Unsafe apply recovery journal: {journal}")
    if not manifest.exists():
        return
    entries = json.loads(manifest.read_text(encoding="utf-8"))
    if not (journal / "complete").exists():
        for entry in entries:
            target = root / entry["path"]
            backup = journal / entry["backup"]
            if (not target.resolve().is_relative_to(root.resolve())
                    or not backup.resolve().is_relative_to(journal.resolve())
                    or any(p.is_symlink() for p in (target, *target.parents, backup))):
                raise ValueError(f"Unsafe recovery path in {manifest}")
            if entry["exists"]:
                _atomic_bytes(target, (journal / entry["backup"]).read_bytes(), entry["mode"])
            else:
                target.unlink(missing_ok=True)
    shutil.rmtree(journal)


def _commit_transaction(root: Path, updates: dict[Path, bytes]) -> list[Path]:
    journal = root / ".map/skill-eval-apply-transaction"
    for path in updates:
        if any(p.is_symlink() for p in (path, *path.parents) if p != root.parent):
            raise ValueError(f"Refusing symlink output: {path}")
    if journal.exists():
        raise ValueError(f"Incomplete apply journal requires inspection: {journal}")
    journal.mkdir(parents=True, exist_ok=False)
    entries: list[_JournalEntry] = []
    for i, (path, data) in enumerate(updates.items()):
        exists = path.exists()
        if exists and path.read_bytes() == data:
            continue
        mode = stat.S_IMODE(path.stat().st_mode) if exists else 0o644
        entry: _JournalEntry = {"path": str(path.relative_to(root)), "exists": exists, "mode": mode, "backup": str(i)}
        if exists:
            _atomic_bytes(journal / str(i), path.read_bytes(), 0o600)
        entries.append(entry)
    _atomic_bytes(journal / "manifest.json", json.dumps(entries).encode(), 0o600)
    fd = os.open(journal, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        for entry in entries:
            path = root / str(entry["path"])
            _atomic_bytes(path, updates[path], int(entry["mode"]))
        _atomic_bytes(journal / "complete", b"complete", 0o600)
    except BaseException:
        _recover_transaction(root)
        raise
    shutil.rmtree(journal)
    return [root / str(entry["path"]) for entry in entries]


def apply_optimized_description(
    *, skill: str, winner: str, current_description: str, no_improvement: bool,
    repo_root: Path, stage: bool = True, provider: str = "claude",
) -> str:
    """Serialize recovery/promotion across processes using the installer barrier."""
    if no_improvement:
        print("No improvement found: current description already optimal on held-out test")
        return "no_improvement"
    if winner == current_description:
        print("Winner identical to current description; no file changes")
        return "identical"
    from mapify_cli.update_state import installer_process_lock

    repo_root = repo_root.resolve()
    with installer_process_lock(repo_root, timeout_s=30):
        return _apply_optimized_description(
            skill=skill, winner=winner, current_description=current_description,
            no_improvement=no_improvement, repo_root=repo_root, stage=stage, provider=provider,
        )


def _apply_optimized_description(
    *, skill: str, winner: str, current_description: str, no_improvement: bool,
    repo_root: Path, stage: bool = True, provider: str = "claude",
) -> str:
    """Render in isolation, then transactionally promote only selected skill files."""
    if no_improvement:
        print("No improvement found: current description already optimal on held-out test")
        return "no_improvement"
    if winner == current_description:
        print("Winner identical to current description; no file changes")
        return "identical"
    if provider not in ("claude", "codex"):
        raise ValueError(f"Unsupported provider: {provider}")
    source_root = (repo_root / "src/mapify_cli/templates_src").resolve()
    jinja = source_root / "skills" / skill / "SKILL.md.jinja"
    if not jinja.resolve().is_relative_to(source_root) or ".git" in jinja.resolve().parts:
        raise ValueError(f"Path safety violation outside templates_src or under .git: {jinja}")
    _recover_transaction(repo_root)
    original = jinja.read_text(encoding="utf-8")
    candidate = _provider_description(original, winner, provider)
    from mapify_cli.delivery.template_renderer import get_environment, render_repo_trees

    with tempfile.TemporaryDirectory(prefix="mapify-apply-") as tmp:
        sandbox = Path(tmp)
        source = sandbox / "src/mapify_cli/templates_src"
        shutil.copytree(source_root, source)
        target = source / jinja.relative_to(source_root)
        target.write_text(candidate, encoding="utf-8")
        env = get_environment(source)
        name = jinja.relative_to(source_root).as_posix()
        opposite = "codex" if provider == "claude" else "claude"
        before_env = get_environment(source_root)
        if env.get_template(name).render(PROVIDER=opposite) != before_env.get_template(name).render(PROVIDER=opposite):
            raise ValueError("Unsupported description structure: opposite provider changed")
        from mapify_cli.skill_ir import parse_frontmatter

        selected = env.get_template(name).render(PROVIDER=provider)
        if parse_frontmatter(selected.split("---", 2)[1]).get("description") != winner:
            raise ValueError("Unsupported description structure: selected winner mismatch")
        for runtime in ("claude", "codex"):
            render_repo_trees(runtime, repo_root=sandbox, templates_src_root=source)
        roots = (".claude/skills", "src/mapify_cli/templates/skills") if provider == "claude" else (
            ".agents/skills", "src/mapify_cli/templates/codex/skills"
        )
        updates = {jinja: target.read_bytes()}
        for root in roots:
            rel = Path(root) / skill / "SKILL.md"
            rendered_bytes = (sandbox / rel).read_bytes()
            if rendered_bytes.decode() != selected:
                raise ValueError("Unsupported provider source: generated skill differs from common source")
            updates[repo_root / rel] = rendered_bytes
        changed = _commit_transaction(repo_root, updates)
    if stage and changed:
        result = subprocess.run(
            ["git", "add", "--", *(str(p.relative_to(repo_root)) for p in changed)],
            cwd=repo_root, capture_output=True, text=True, check=False,
        )
        if result.returncode:
            print(f"Warning: 'git add' failed (exit {result.returncode}): {result.stderr.strip()}")
    print(f"Applied new description for '{skill}'. Note: skill-rules.json description is NOT auto-patched")
    return "applied"
