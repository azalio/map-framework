"""Static audit helpers for shipped MAP skill surfaces.

MAP installs hand-authored provider skill files into user projects.  This
module lowers each ``SKILL.md`` into a small intermediate representation so
tests and release checks can validate the semantics before ``mapify init``
copies those files into a target repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SUPPORTED_FRONTMATTER_FIELDS = frozenset(
    {
        "agent",
        "allowed-tools",
        "argument-hint",
        "arguments",
        "context",
        "description",
        "disable-model-invocation",
        "effort",
        "hooks",
        "metadata",
        "model",
        "name",
        "paths",
        "shell",
        "user-invocable",
        "version",
        "when_to_use",
    }
)

FORBIDDEN_INSTRUCTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bignore\s+(?:all\s+)?(?:previous|above|prior)\s+instructions\b", re.IGNORECASE),
    re.compile(r"\bdisregard\s+(?:all\s+)?(?:previous|above|prior)\s+instructions\b", re.IGNORECASE),
    re.compile(r"\boverride\s+(?:all\s+)?(?:safety|security)\s+(?:rules|policies)\b", re.IGNORECASE),
    re.compile(r"\breveal\s+(?:the\s+)?(?:system|developer)\s+(?:prompt|message)\b", re.IGNORECASE),
)

MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]\n]+\]\(([^)\n]+)\)")
CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
EXTERNAL_LINK_PREFIXES = ("http://", "https://", "mailto:", "#")


@dataclass(frozen=True)
class SkillIR:
    """Provider-neutral facts extracted from one ``SKILL.md`` file."""

    name: str
    provider: str
    source_path: str
    description: str
    invocation_mode: str
    allowed_tools: tuple[str, ...]
    supporting_files: tuple[str, ...]
    safety_constraints: tuple[str, ...]
    content_hash: str
    frontmatter: dict[str, Any]


@dataclass(frozen=True)
class SkillAuditFinding:
    """A static audit problem that should block template release."""

    path: str
    severity: str
    code: str
    message: str


class SkillIRParseError(ValueError):
    """Raised when a skill file cannot be lowered into ``SkillIR``."""


def _split_frontmatter(content: str) -> tuple[str, str]:
    if not content.startswith("---\n"):
        raise SkillIRParseError("missing opening frontmatter delimiter")
    end = content.find("\n---", 4)
    if end == -1:
        raise SkillIRParseError("missing closing frontmatter delimiter")
    return content[4:end], content[end + len("\n---") :].lstrip("\n")


def _parse_simple_yaml(frontmatter: str) -> dict[str, Any]:
    """Parse the small YAML subset used by MAP skill frontmatter.

    PyYAML is available in the test/dev environment, but it is not a runtime
    dependency of ``mapify-cli``.  This fallback is intentionally narrow: it
    supports top-level scalars, comma-separated tool lists, and preserves nested
    blocks as text for keys such as ``hooks`` or ``metadata``.
    """

    parsed: dict[str, Any] = {}
    lines = frontmatter.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        if line.startswith(" "):
            raise SkillIRParseError(f"unexpected indented frontmatter line: {line!r}")
        if ":" not in line:
            raise SkillIRParseError(f"invalid frontmatter line: {line!r}")
        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        if not key:
            raise SkillIRParseError(f"invalid empty frontmatter key: {line!r}")
        if value in {"|", ">", ">-"}:
            block: list[str] = []
            index += 1
            while index < len(lines) and (
                lines[index].startswith(" ") or not lines[index].strip()
            ):
                block.append(lines[index][2:] if lines[index].startswith("  ") else "")
                index += 1
            text = "\n".join(block).strip()
            parsed[key] = " ".join(text.splitlines()) if value.startswith(">") else text
            continue
        if value == "":
            block = []
            index += 1
            while index < len(lines) and (
                lines[index].startswith(" ") or not lines[index].strip()
            ):
                block.append(lines[index])
                index += 1
            parsed[key] = "\n".join(block).strip()
            continue
        if value.lower() == "true":
            parsed[key] = True
        elif value.lower() == "false":
            parsed[key] = False
        else:
            if value.startswith("[") and not value.endswith("]"):
                raise SkillIRParseError(f"invalid list-like scalar for {key!r}")
            if value.startswith("{") and not value.endswith("}"):
                raise SkillIRParseError(f"invalid map-like scalar for {key!r}")
            if value.startswith(("'", '"')) and not value.endswith(value[0]):
                raise SkillIRParseError(f"unterminated quoted scalar for {key!r}")
            parsed[key] = value.strip('"\'')
        index += 1
    return parsed


def parse_frontmatter(frontmatter: str) -> dict[str, Any]:
    """Parse skill frontmatter without requiring PyYAML at runtime."""

    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        return _parse_simple_yaml(frontmatter)

    try:
        loaded = yaml.safe_load(frontmatter) or {}
    except Exception as exc:
        raise SkillIRParseError(f"invalid YAML frontmatter: {exc}") from exc
    if not isinstance(loaded, dict):
        raise SkillIRParseError("frontmatter must parse to a mapping")
    return loaded


def _normalise_allowed_tools(value: Any) -> tuple[str, ...]:
    if not value:
        return ()
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    return (str(value),)


def _strip_code_fences(content: str) -> str:
    return CODE_FENCE_RE.sub("", content)


def _supporting_files(body: str) -> tuple[str, ...]:
    files: list[str] = []
    for href in MARKDOWN_LINK_RE.findall(_strip_code_fences(body)):
        target = href.split("#", 1)[0].strip()
        if target.startswith("<") and target.endswith(">"):
            target = target[1:-1].strip()
        if not target or target.startswith(EXTERNAL_LINK_PREFIXES):
            continue
        files.append(target)
    return tuple(dict.fromkeys(files))


def _safety_constraints(body: str) -> tuple[str, ...]:
    constraints: list[str] = []
    for line in _strip_code_fences(body).splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if lowered.startswith(("- do not", "- don't", "- never", "- must not")):
            constraints.append(stripped.lstrip("- ").strip())
    return tuple(constraints)


def _parse_skill_content(skill_file: Path, *, provider: str) -> tuple[SkillIR, str]:
    content_bytes = skill_file.read_bytes()
    content = content_bytes.decode("utf-8")
    frontmatter_text, body = _split_frontmatter(content)
    frontmatter = parse_frontmatter(frontmatter_text)
    name = str(frontmatter.get("name") or skill_file.parent.name)
    invocation_mode = (
        "manual" if frontmatter.get("disable-model-invocation") else "automatic"
    )
    ir = SkillIR(
        name=name,
        provider=provider,
        source_path=str(skill_file),
        description=str(frontmatter.get("description") or "").strip(),
        invocation_mode=invocation_mode,
        allowed_tools=_normalise_allowed_tools(frontmatter.get("allowed-tools")),
        supporting_files=_supporting_files(body),
        safety_constraints=_safety_constraints(body),
        content_hash=hashlib.sha256(content_bytes).hexdigest(),
        frontmatter=frontmatter,
    )
    return ir, body


def parse_skill_file(skill_file: Path, *, provider: str) -> SkillIR:
    """Lower one ``SKILL.md`` file into ``SkillIR``."""

    ir, _body = _parse_skill_content(skill_file, provider=provider)
    return ir


def _provider_from_root(root: Path) -> str:
    parts = set(root.parts)
    if "codex" in parts or root.name == "codex" or ".agents" in parts:
        return "codex"
    return "claude"


def iter_skill_files(root: Path) -> tuple[Path, ...]:
    """Return all ``SKILL.md`` files under a provider skill root."""

    return tuple(sorted(path for path in root.glob("*/SKILL.md") if path.is_file()))


def audit_skill_file(
    skill_file: Path,
    *,
    provider: str,
    bundle_root: Path | None = None,
) -> tuple[SkillIR | None, list[SkillAuditFinding]]:
    """Parse and validate one skill file."""

    findings: list[SkillAuditFinding] = []
    try:
        ir, body = _parse_skill_content(skill_file, provider=provider)
    except (OSError, UnicodeDecodeError, SkillIRParseError) as exc:
        return None, [
            SkillAuditFinding(str(skill_file), "error", "parse_error", str(exc))
        ]

    frontmatter_keys = set(ir.frontmatter)
    unsupported = sorted(frontmatter_keys - SUPPORTED_FRONTMATTER_FIELDS)
    if unsupported:
        findings.append(
            SkillAuditFinding(
                str(skill_file),
                "error",
                "unsupported_frontmatter",
                "Unsupported frontmatter fields: " + ", ".join(unsupported),
            )
        )

    if ir.name != skill_file.parent.name:
        findings.append(
            SkillAuditFinding(
                str(skill_file),
                "error",
                "name_mismatch",
                f"frontmatter name {ir.name!r} does not match folder {skill_file.parent.name!r}",
            )
        )
    if not ir.description:
        findings.append(
            SkillAuditFinding(str(skill_file), "error", "missing_description", "description is required")
        )

    allowed_root = (bundle_root or skill_file.parent).resolve()
    for rel_path in ir.supporting_files:
        resolved = (skill_file.parent / rel_path).resolve()
        if resolved != allowed_root and allowed_root not in resolved.parents:
            findings.append(
                SkillAuditFinding(
                    str(skill_file),
                    "error",
                    "supporting_file_escape",
                    f"supporting link escapes provider bundle: {rel_path}",
                )
            )
        elif not resolved.exists():
            findings.append(
                SkillAuditFinding(
                    str(skill_file),
                    "error",
                    "missing_supporting_file",
                    f"supporting link is missing: {rel_path}",
                )
            )

    body_without_code = _strip_code_fences(body)
    for pattern in FORBIDDEN_INSTRUCTION_PATTERNS:
        match = pattern.search(body_without_code)
        if match:
            findings.append(
                SkillAuditFinding(
                    str(skill_file),
                    "error",
                    "forbidden_instruction",
                    f"forbidden instruction-like phrase: {match.group(0)!r}",
                )
            )

    return ir, findings


def audit_skill_tree(root: Path, *, provider: str | None = None) -> tuple[list[SkillIR], list[SkillAuditFinding]]:
    """Audit every skill under a provider skill root."""

    provider = provider or _provider_from_root(root)
    irs: list[SkillIR] = []
    findings: list[SkillAuditFinding] = []
    bundle_root = root.parent
    for skill_file in iter_skill_files(root):
        ir, skill_findings = audit_skill_file(
            skill_file,
            provider=provider,
            bundle_root=bundle_root,
        )
        if ir is not None:
            irs.append(ir)
        findings.extend(skill_findings)
    return irs, findings


def ir_to_dict(ir: SkillIR) -> dict[str, Any]:
    """Return a stable JSON-serializable representation of ``SkillIR``."""

    return {
        "name": ir.name,
        "provider": ir.provider,
        "source_path": ir.source_path,
        "description": ir.description,
        "invocation_mode": ir.invocation_mode,
        "allowed_tools": list(ir.allowed_tools),
        "supporting_files": list(ir.supporting_files),
        "safety_constraints": list(ir.safety_constraints),
        "content_hash": ir.content_hash,
        "frontmatter_keys": sorted(ir.frontmatter),
    }


def _finding_to_dict(finding: SkillAuditFinding) -> dict[str, str]:
    return {
        "path": finding.path,
        "severity": finding.severity,
        "code": finding.code,
        "message": finding.message,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit MAP provider skill templates")
    parser.add_argument("roots", nargs="+", type=Path, help="skill roots to audit")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)

    all_irs: list[SkillIR] = []
    all_findings: list[SkillAuditFinding] = []
    for root in args.roots:
        irs, findings = audit_skill_tree(root)
        all_irs.extend(irs)
        all_findings.extend(findings)

    if args.format == "json":
        print(
            json.dumps(
                {
                    "skills": [ir_to_dict(ir) for ir in all_irs],
                    "findings": [_finding_to_dict(finding) for finding in all_findings],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        for ir in all_irs:
            print(f"OK {ir.provider}:{ir.name} {ir.content_hash[:12]}")
        for finding in all_findings:
            print(
                f"{finding.severity.upper()} {finding.code} {finding.path}: "
                f"{finding.message}",
                file=sys.stderr,
            )
    return 1 if any(f.severity == "error" for f in all_findings) else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
