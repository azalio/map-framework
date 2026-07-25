"""Default ProposerFn implementation for skill-description optimization.

Calls ``claude -p <prompt> --output-format json`` as a subprocess and reads
ONLY the ``.result`` field from the JSON envelope.

Invariants enforced here:
- INV-1 / VC3: argv is a list; untrusted record text is a discrete element.
- INV-2 / HC-7: MAP_INVOKED_BY is set on every subprocess env.
- VC4: all failure modes (non-zero exit, malformed JSON, empty .result,
  OSError, TimeoutExpired) return None — never raise.
- No ``import anthropic``, no ANTHROPIC_API_KEY access (INV-1 / HC-2 / AC-10).
- No ``--model`` flag (D2).
"""
from __future__ import annotations

import json
import os
import subprocess

from mapify_cli.skills_eval.eval_schema import EvalResultRecord

# Default subprocess timeout in seconds.
_DEFAULT_TIMEOUT: int = 120

# Value set in MAP_INVOKED_BY for every proposer subprocess call.
_MAP_INVOKED_BY_VALUE: str = "skills-eval-proposer"

# Hard cap on a proposed description's length: the Agent Skills spec maximum for
# the `description` field (1024 chars), which the official skill-creator also
# validates against. A candidate over this is rejected so the eval never proves
# an unshippable description. (Note: Claude Code briefly truncated descriptions
# at 250 chars in v2.1.86, raised to 1536 in v2.1.105, then dropped the
# per-description cap entirely in v2.1.129+ for a usage-ranked listing budget —
# so 250 was a transient cap, not the spec; current Claude Code loads the full
# description for triggering.)
_DEFAULT_MAX_CHARS: int = 1024


def _build_prompt(
    current_description: str,
    failing_train_records: list[EvalResultRecord],
    max_chars: int = _DEFAULT_MAX_CHARS,
) -> str:
    """Build an improvement prompt from the current description and failing records.

    The prompt is a discrete argv element, never interpolated into a shell string.
    Record content (.prompt, .assertions_failed) is treated as UNTRUSTED text.
    """
    lines: list[str] = [
        "You are optimizing the trigger description of a Claude Code skill.",
        "",
        "Current description:",
        current_description.strip(),
        "",
        "The following eval prompts are currently failing (they should trigger",
        "the skill, but do not). For each, the assertions that failed are listed:",
        "",
    ]
    for i, rec in enumerate(failing_train_records, start=1):
        lines.append(f"--- Failing record {i} ---")
        lines.append(f"Prompt: {rec.prompt}")
        if rec.assertions_failed:
            lines.append("Assertions failed:")
            for assertion in rec.assertions_failed:
                lines.append(f"  - {assertion}")
        lines.append("")

    lines += [
        "Write an improved skill trigger description that would cause the",
        "skill to be triggered for the failing prompts above while remaining",
        "precise and not overly broad.",
        "",
        (f"HARD LIMIT: the new description MUST be at most {max_chars} characters "
        f"(aim for ~{max(0, max_chars - 20)} to be safe). It is shown in a UI that "
        "truncates anything longer, so a longer description is unusable no matter "
        "how well it triggers. Count characters and stay within the limit."),
        "",
        "Respond with ONLY the new description text, no preamble, no explanation.",
    ]
    return "\n".join(lines)


def propose_description(
    current_description: str,
    failing_train_records: list[EvalResultRecord],
    max_chars: int = _DEFAULT_MAX_CHARS,
) -> str | None:
    """Propose an improved skill description using ``claude -p``.

    Mirrors the subprocess/envelope pattern from ``dispatcher._run_once`` and
    ``dispatcher._parse_envelope``.

    The proposal is capped at ``max_chars`` characters (the skill-listing UI
    limit): the prompt asks for it, and a candidate that still exceeds the cap
    is rejected (``None``) so the optimizer never evaluates an unshippable
    description.

    Returns the proposed description text (stripped) on success, or ``None``
    on any failure:
    - non-zero subprocess exit code
    - subprocess timeout (``subprocess.TimeoutExpired``)
    - claude not on PATH (``OSError`` / ``FileNotFoundError``)
    - any other unexpected exception
    - malformed JSON stdout
    - missing or whitespace-only ``.result`` in the JSON envelope
    - a proposal longer than ``max_chars`` characters
    """
    prompt = _build_prompt(current_description, failing_train_records, max_chars)

    # Intent: argv is always a list; prompt is a discrete element (never shell-interpolated).
    argv: list[str] = ["claude", "-p", prompt, "--output-format", "json"]

    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=_DEFAULT_TIMEOUT,
            cwd=str(os.getcwd()),
            env={**os.environ, "MAP_INVOKED_BY": _MAP_INVOKED_BY_VALUE},
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None
    except OSError:
        # Covers FileNotFoundError (claude not on PATH) and other OS-level errors.
        return None
    except Exception:  # noqa: BLE001
        return None

    if proc.returncode != 0:
        return None

    # Intent: parse the JSON envelope defensively — mirror dispatcher._parse_envelope.
    try:
        parsed = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(parsed, dict):
        return None

    raw = str(parsed.get("result", ""))
    candidate = raw.strip()
    if not candidate:
        return None

    # Reject an over-limit proposal so the optimizer never evaluates (and a
    # later --apply never tries to ship) a description the skill-listing UI
    # would truncate. Treated like a proposal failure for that iteration.
    if len(candidate) > max_chars:
        return None

    return candidate
