"""Variant dispatcher for the skills_eval package.

Provides the ABC ``VariantDispatcher`` and two concrete implementations:
- ``MockDispatcher``: zero-subprocess, caller-controlled output for CI tests (INV-2).
- ``ClaudeSubprocessDispatcher``: real ``claude -p`` invocation in a seeded
  throwaway temp cwd with the TEMP-FLIP applied.

Hard constraints (INV-2, INV-3, INV-5)
---------------------------------------
- Uses only stdlib; no Anthropic SDK imports (INV-3).
- Does not read cloud credentials from the environment (INV-3).
- Production ``.claude/`` and ``.map/`` trees are NEVER modified (INV-5).
  The TEMP-FLIP touches only the throwaway seeded copy.
- ``MockDispatcher.dispatch`` NEVER calls subprocess (INV-2).
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import shutil
import subprocess
import tempfile
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from mapify_cli.skills_eval.eval_schema import DispatchResult
from mapify_cli.token_budget import TokenUsage

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class VariantDispatcher(ABC):
    """Abstract dispatcher: given a prompt, produce a ``DispatchResult``."""

    @abstractmethod
    def dispatch(self, prompt: str) -> DispatchResult:
        """Run ``prompt`` and return a fully-populated ``DispatchResult``.

        Implementations MUST NOT raise — transient failures are captured in
        ``DispatchResult.error``.
        """


# ---------------------------------------------------------------------------
# MockDispatcher — CI / unit-test use only (INV-2: zero subprocess)
# ---------------------------------------------------------------------------


class MockDispatcher(VariantDispatcher):
    """Caller-controlled dispatcher that performs ZERO subprocess work.

    All tests in the CI suite use this instead of ``ClaudeSubprocessDispatcher``
    to avoid real ``claude`` invocations.  Construct with the exact field values
    that ``dispatch()`` should return.
    """

    def __init__(
        self,
        *,
        triggered_skill: str | None = None,
        raw_output: str = "",
        token_usage: TokenUsage | None = None,
        duration_s: float = 0.0,
        error: str | None = None,
    ) -> None:
        self._triggered_skill = triggered_skill
        self._raw_output = raw_output
        self._token_usage = token_usage
        self._duration_s = duration_s
        self._error = error

    def dispatch(self, prompt: str) -> DispatchResult:
        """Return the caller-configured ``DispatchResult``.

        No subprocess call, no file I/O — pure attribute access (INV-2).
        The ``prompt`` is intentionally ignored — a mock returns a fixed result.
        """
        del prompt  # intentionally unused; mock returns caller-set values
        return DispatchResult(
            raw_output=self._raw_output,
            triggered_skill=self._triggered_skill,
            token_usage=self._token_usage,
            duration_s=self._duration_s,
            error=self._error,
        )


# ---------------------------------------------------------------------------
# Seeding helpers (ClaudeSubprocessDispatcher internals)
# ---------------------------------------------------------------------------

# Subdir name (under the throwaway eval cwd) handed to the telegram-bridge
# plugin as its state dir — see _eval_subprocess_env.
_NO_TELEGRAM_STATE_DIRNAME = ".map-eval-no-telegram"

# Tools the eval ``claude -p`` subprocess is NOT allowed to use.
#
# Trigger-accuracy eval only needs to observe whether the right skill *fires*
# (the first ``Skill`` tool_use in the transcript) — it does NOT need the skill
# *body* to execute. Letting the body run is actively harmful for EXECUTING
# skills: ``map-check`` would run the full ``make check`` test suite, and
# ``map-task`` / ``map-efficient`` would dispatch sub-agents — each blowing past
# the per-call timeout (recorded as a false non-trigger) and, for sub-agents,
# leaving orphaned child processes and burning real quota after the parent is
# killed. Disallowing the heavy/mutating/network tools lets the skill still
# TRIGGER (description-driven, recorded in the transcript) while the body cannot
# perform slow or side-effecting work. Read-only tools (Read/Grep/Glob) stay
# allowed so triggering behaviour is unaffected. The ``Skill`` tool itself is
# never disallowed — it is exactly the signal we measure.
_EVAL_DISALLOWED_TOOLS: tuple[str, ...] = (
    "Bash",
    "Edit",
    "Write",
    "NotebookEdit",
    "Task",
    "Agent",
    "WebFetch",
    "WebSearch",
)


def _eval_subprocess_env(cwd: Path) -> dict[str, str]:
    """Build the environment for an eval ``claude -p`` subprocess.

    Two scoped overrides on top of the inherited environment:

    - ``MAP_INVOKED_BY`` — recursion guard so MAP's own hooks no-op inside the
      eval subprocess.
    - ``TG_STATE_DIR`` — points the ``telegram-bridge`` plugin's state dir at a
      config-less path **inside the throwaway cwd**. The plugin's SessionStart
      hook may still inject its "always-listen — run `tg listen`" instruction
      (plugin hooks run in a restricted env that does not receive this override),
      but the instruction is now **inert**: when the eval ``claude -p`` agent
      actually runs ``tg listen`` / ``tg send``, those commands inherit THIS
      subprocess env, find no ``config.json`` under ``TG_STATE_DIR``, and exit
      immediately (``die("no config.json")``) instead of blocking on the Telegram
      long-poll. Without this, ``tg listen`` blocks until the dispatch timeout and
      a triggered-skill cell mis-records as a non-trigger. The operator's real
      ``~/.claude/telegram`` config is never touched — this is a per-subprocess
      override on a path that is removed with the temp cwd.
    """
    return {
        **os.environ,
        "MAP_INVOKED_BY": "skills-eval",
        "TG_STATE_DIR": str(cwd / _NO_TELEGRAM_STATE_DIRNAME),
    }


def _seed_temp_cwd(source_claude_dir: Path) -> Path:
    """Create a throwaway temp directory seeded with a copy of ``.claude/``.

    Steps:
    1. ``tempfile.mkdtemp()`` — fresh isolated dir.
    2. ``shutil.copytree(source_claude_dir, <tmp>/.claude)`` — full copy.
    3. ``os.makedirs(<tmp>/.map)`` — fresh empty ``.map/`` (no production state).
    4. TEMP-FLIP: rewrite ``disable-model-invocation: true`` →
       ``disable-model-invocation: false`` in every seeded SKILL.md.

    Returns the tmp dir ``Path``.
    Caller is responsible for ``shutil.rmtree(tmp, ignore_errors=True)`` cleanup.
    """
    tmp = Path(tempfile.mkdtemp(prefix="mapeval-"))

    # 1. Copy .claude/ tree (only if source exists).
    seeded_claude = tmp / ".claude"
    if source_claude_dir.is_dir():
        shutil.copytree(source_claude_dir, seeded_claude)
    else:
        seeded_claude.mkdir(parents=True)
        logger.warning(
            "seed_temp_cwd: source_claude_dir %s does not exist — seeding empty .claude/",
            source_claude_dir,
        )

    # 2. Empty .map/ — prevents accidental reads of production workflow state.
    (tmp / ".map").mkdir(parents=True)

    # 3. TEMP-FLIP: make every skill model-selectable for the eval (spike VC3).
    #    Pattern: a frontmatter line ``disable-model-invocation: true`` (any
    #    leading/trailing whitespace) → ``disable-model-invocation: false``.
    #    Skills without the field are left untouched (already invocable).
    _apply_temp_flip(seeded_claude)

    return tmp


def _apply_temp_flip(seeded_claude_dir: Path) -> None:
    """Rewrite ``disable-model-invocation: true`` → ``false`` in seeded SKILL.md files.

    Intent: allow the eval model to select any skill via description, not just
    the three production-invocable ones.  Throwaway copy only — production
    templates are never touched.
    """
    skill_files = list(seeded_claude_dir.glob("skills/*/SKILL.md"))
    for skill_file in skill_files:
        try:
            original = skill_file.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("temp_flip: could not read %s: %s", skill_file, exc)
            continue

        flipped = _flip_disable_invocation_line(original)
        if flipped != original:
            try:
                skill_file.write_text(flipped, encoding="utf-8")
            except OSError as exc:
                logger.warning("temp_flip: could not write %s: %s", skill_file, exc)


def _flip_disable_invocation_line(content: str) -> str:
    """Replace the first ``disable-model-invocation: true`` line with ``false``.

    Operates line-by-line to avoid regex mis-matches on other content.
    Returns the original string unchanged if the field is absent or already false.
    """
    lines = content.splitlines(keepends=True)
    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped == "disable-model-invocation: true":
            # Preserve leading/trailing whitespace so the YAML structure stays valid.
            result.append(line.replace("true", "false", 1))
        else:
            result.append(line)
    return "".join(result)


# ---------------------------------------------------------------------------
# Transcript helpers
# ---------------------------------------------------------------------------


def _derive_triggered_skill(session_id: str, cwd: Path) -> str | None:
    """Scan the native JSONL transcript for the first fired skill.

    Search order (spike VC3 binding contract):
    1. Glob ``~/.claude/projects/*/<session_id>.jsonl`` (session_id is a unique
       UUID — no slug fragility).
    2. Fall back to slug-from-cwd path if glob returns nothing.
    3. If transcript not found → return ``None`` (do not crash).

    Detection rule: find the first assistant message.content[*] where
    ``type=="tool_use"`` and ``name=="Skill"``; return ``input.skill``.
    ``name=="Agent"`` / ``Task`` blocks are ignored.
    """
    if not session_id:
        return None

    transcript_path = _locate_transcript(session_id, cwd)
    if transcript_path is None or not transcript_path.exists():
        logger.debug(
            "transcript not found for session_id=%s cwd=%s", session_id, cwd
        )
        return None

    return _parse_transcript_for_skill(transcript_path)


def _cwd_to_project_slug(path: Path) -> str:
    """Replicate Claude Code's ``cwd -> ~/.claude/projects/<slug>`` transform.

    Every character that is NOT alphanumeric or ``-`` (so ``/``, ``.``, ``_``,
    spaces, …) is replaced by ``-``. Verified against real project dirs: a
    ``tempfile.mkdtemp()`` name such as ``mapeval-s_u5zv32`` — which contains an
    underscore — is recorded under ``…-mapeval-s-u5zv32``. A naive
    ``replace("/","-").replace(".","-")`` misses the ``_`` and silently fails to
    locate the transcript (a false non-trigger on the affected dispatches).
    """
    return re.sub(r"[^0-9A-Za-z-]", "-", str(path))


def _locate_transcript(session_id: str, cwd: Path) -> Path | None:
    """Return the path to the JSONL transcript or ``None`` if not found."""
    projects_dir = Path.home() / ".claude" / "projects"

    # Primary: UUID-based glob — immune to slug encoding differences.
    if session_id:
        matches = list(projects_dir.glob(f"*/{session_id}.jsonl"))
        if matches:
            return matches[0]

    # Fallback: reconstruct slug from cwd (Claude Code's transform).
    cwd_slug = _cwd_to_project_slug(cwd)
    fallback = projects_dir / cwd_slug / f"{session_id}.jsonl"
    if fallback.exists():
        return fallback

    return None


def _locate_transcript_by_cwd(cwd: Path) -> Path | None:
    """Locate the transcript for a dispatch by cwd slug — no ``session_id`` needed.

    Used for timeout recovery: when ``claude -p`` is killed by the per-call
    timeout we never receive the result envelope, so the ``session_id`` is
    unknown. But Claude Code writes transcripts under
    ``~/.claude/projects/<cwd-slug>/<session_id>.jsonl`` where ``<cwd-slug>`` is
    the cwd path with ``/`` and ``.`` replaced by ``-``. Each dispatch runs in a
    unique throwaway temp cwd, so that slug dir holds exactly one session's
    transcript(s); return the most-recently-modified ``*.jsonl`` (or ``None``).

    Claude Code derives the slug from the *resolved* cwd, so on macOS a
    ``tempfile.mkdtemp()`` path under ``/var/folders/...`` (where ``/var`` is a
    symlink to ``/private/var``) is recorded under the ``/private/var/...`` slug.
    We therefore try the slug for BOTH the raw and the resolved cwd, and finally
    fall back to globbing by the unique temp-dir name (the project dir name ends
    with it) so a slug-derivation change cannot silently break recovery.
    """
    projects_dir = Path.home() / ".claude" / "projects"
    if not projects_dir.is_dir():
        return None

    candidates: list[Path] = []
    bases = {cwd}
    try:
        bases.add(cwd.resolve())
    except OSError:  # pragma: no cover - resolve only fails on exotic FS errors
        pass
    for base in bases:
        slug_dir = projects_dir / _cwd_to_project_slug(base)
        if slug_dir.is_dir():
            candidates.extend(slug_dir.glob("*.jsonl"))

    if not candidates:
        # Fallback: the project dir name ends with the (slugified) unique temp
        # dir name — slugify so an underscore in the mkdtemp suffix still matches.
        name_slug = _cwd_to_project_slug(Path(cwd.name))
        candidates.extend(projects_dir.glob(f"*{name_slug}/*.jsonl"))

    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _parse_transcript_for_skill(path: Path) -> str | None:
    """Return the first ``Skill`` tool_use ``input.skill`` value, or ``None``."""
    try:
        with path.open(encoding="utf-8") as fh:
            for raw_line in fh:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    entry = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue

                skill = _extract_skill_from_entry(entry)
                if skill is not None:
                    return skill
    except OSError as exc:
        logger.warning("parse_transcript: could not read %s: %s", path, exc)

    return None


def _extract_skill_from_entry(entry: Any) -> str | None:
    """Extract ``input.skill`` from a transcript entry if it is a Skill tool_use.

    Walks ``message.content[*]`` looking for ``type=="tool_use"`` +
    ``name=="Skill"``.  Returns the skill name string or ``None``.
    """
    if not isinstance(entry, dict):
        return None

    message = entry.get("message")
    if not isinstance(message, dict):
        return None

    content = message.get("content")
    if not isinstance(content, list):
        return None

    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "tool_use":
            continue
        if block.get("name") != "Skill":
            continue
        tool_input = block.get("input")
        if isinstance(tool_input, dict):
            skill_name = tool_input.get("skill")
            if isinstance(skill_name, str) and skill_name:
                return skill_name

    return None


# ---------------------------------------------------------------------------
# Envelope parsing
# ---------------------------------------------------------------------------


def _parse_envelope(stdout: str) -> tuple[str, TokenUsage | None, str]:
    """Parse the ``claude -p --output-format json`` result envelope defensively.

    Returns ``(raw_output, token_usage, session_id)``.
    On JSON decode failure returns ``(stdout, None, "")``.

    Mirrors ``_parse_claude_output`` / ``_append_cost_log`` from
    ``memory/finalize.py:232-281``.
    """
    try:
        parsed = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return stdout, None, ""

    if not isinstance(parsed, dict):
        return stdout, None, ""

    raw_output = str(parsed.get("result", ""))
    session_id = str(parsed.get("session_id") or "")

    usage_raw = parsed.get("usage")
    token_usage: TokenUsage | None = None
    if isinstance(usage_raw, dict):
        token_usage = TokenUsage(
            input_tokens=int(usage_raw.get("input_tokens", 0) or 0),
            cache_read_input_tokens=int(
                usage_raw.get("cache_read_input_tokens", 0) or 0
            ),
            cache_creation_input_tokens=int(
                usage_raw.get("cache_creation_input_tokens", 0) or 0
            ),
        )

    return raw_output, token_usage, session_id


# ---------------------------------------------------------------------------
# ClaudeSubprocessDispatcher
# ---------------------------------------------------------------------------

# Default jitter upper-bound (seconds) added to backoff sleep.
_JITTER_MAX: float = 2.0


class _TimeoutRecovery:
    """Internal signal: the subprocess timed out but the trigger was recovered.

    Returned by ``_run_once`` when ``claude -p`` exceeds the per-call timeout yet
    its transcript was already written (the ``Skill`` tool_use fires early, in the
    first assistant turn, well before a slow skill BODY finishes). This is a VALID
    trigger verdict — not a transient failure — so it is NOT retried.
    ``triggered_skill`` is the fired skill name, or ``None`` if the transcript
    exists but no skill fired by the time the process was killed.
    """

    __slots__ = ("triggered_skill",)

    def __init__(self, triggered_skill: str | None) -> None:
        self.triggered_skill = triggered_skill


class ClaudeSubprocessDispatcher(VariantDispatcher):
    """Real ``claude -p`` dispatcher for production/manual eval runs.

    Seeding and cleanup
    -------------------
    Each ``dispatch()`` call:
    1. Creates a fresh temp cwd seeded with a copy of ``source_claude_dir``
       and an empty ``.map/``.
    2. Applies TEMP-FLIP so all skills are model-selectable.
    3. Runs ``claude -p <prompt> --output-format json`` in that temp cwd.
    4. Removes the temp dir in a ``try/finally`` block.

    Retry policy (VC4)
    ------------------
    ``subprocess.TimeoutExpired``, non-zero ``returncode``, and ``OSError``
    are treated as transient.  Up to ``max_retries`` additional attempts are
    made with bounded jittered exponential backoff.  After exhaustion the error
    is recorded in ``DispatchResult.error``; no exception escapes ``dispatch()``.

    INV-3 compliance
    ----------------
    No Anthropic SDK import.  No cloud credential environment reads.

    INV-5 compliance
    ----------------
    ``cwd`` of the subprocess is always the throwaway temp dir.  Production
    ``.map/`` is never referenced.
    """

    def __init__(
        self,
        *,
        source_claude_dir: Path | None = None,
        timeout: float = 90.0,
        max_retries: int = 2,
        backoff_base: float = 2.0,
        model: str | None = None,
    ) -> None:
        """Initialise the dispatcher.

        Parameters
        ----------
        source_claude_dir:
            Path to the ``.claude/`` directory to seed from.  Defaults to
            ``Path.cwd() / ".claude"`` at construction time.
        model:
            Optional model alias passed to ``claude -p --model`` (e.g. ``haiku``,
            ``sonnet``, ``opus``). ``None`` (default) omits the flag, so the
            ``claude`` CLI resolves the session default — preserving prior
            behaviour. Pin this to measure how trigger accuracy varies by model
            tier (model choice is known to dominate prompt phrasing).
        timeout:
            Per-attempt timeout in seconds passed to ``subprocess.run``. The
            default (90 s) sits well above the observed trigger latency (the
            first ``Skill`` tool_use lands in the transcript in ~30 s) so most
            calls finish naturally; a slow EXECUTING skill that overruns is not
            mis-recorded — ``_run_once`` recovers the trigger from the transcript
            on timeout (see ``_TimeoutRecovery``).
        max_retries:
            Number of *additional* retry attempts after the first failure.
            Total attempts = 1 + max_retries.
        backoff_base:
            Base for exponential backoff (seconds).  Attempt 0 sleeps
            ``backoff_base * 2**0 + jitter``, attempt 1 sleeps
            ``backoff_base * 2**1 + jitter``, etc.
        """
        self._source_claude_dir: Path = (
            source_claude_dir if source_claude_dir is not None else Path.cwd() / ".claude"
        )
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._model = model
        # Holds the error message from the latest _run_once call. Instance-scoped
        # (not class-level) so the safe-sequential-only assumption is explicit.
        self._last_error: str = ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def dispatch(self, prompt: str) -> DispatchResult:
        """Dispatch ``prompt`` via ``claude -p``, with backoff retry on failure.

        Always returns a ``DispatchResult`` — never raises.
        """
        t_total_start = time.monotonic()
        tmp: Path | None = None

        try:
            tmp = _seed_temp_cwd(self._source_claude_dir)
            return self._dispatch_with_retry(prompt, tmp, t_total_start)
        except Exception as exc:  # noqa: BLE001
            # Catch any unexpected seeding failure; should not occur in practice.
            duration_s = time.monotonic() - t_total_start
            logger.warning("dispatch: unexpected error during seeding: %s", exc)
            return DispatchResult(
                raw_output="",
                triggered_skill=None,
                token_usage=None,
                duration_s=duration_s,
                error=f"seeding error: {exc}",
            )
        finally:
            if tmp is not None:
                shutil.rmtree(tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _dispatch_with_retry(
        self,
        prompt: str,
        tmp: Path,
        t_total_start: float,
    ) -> DispatchResult:
        """Run the subprocess with bounded jittered exponential backoff.

        ``max_retries=2`` means up to 3 total attempts (attempt 0, 1, 2).
        After all attempts are exhausted, returns an error ``DispatchResult``.
        """
        argv = [
            "claude",
            "-p",
            prompt,
            "--output-format",
            "json",
            "--disallowed-tools",
            *_EVAL_DISALLOWED_TOOLS,
        ]
        if self._model:
            argv += ["--model", self._model]
        last_error: str = ""

        for attempt in range(self._max_retries + 1):
            if attempt > 0:
                sleep_s = self._backoff_base * (2 ** (attempt - 1)) + random.uniform(
                    0, _JITTER_MAX
                )
                logger.debug(
                    "dispatch: retry attempt %d/%d — sleeping %.2fs",
                    attempt,
                    self._max_retries,
                    sleep_s,
                )
                time.sleep(sleep_s)

            result = self._run_once(argv, tmp)
            if isinstance(result, subprocess.CompletedProcess):
                # Successful subprocess run — parse and return.
                return self._build_result(result, tmp, t_total_start)
            if isinstance(result, _TimeoutRecovery):
                # Timed out, but the trigger was recovered from the transcript —
                # a valid verdict, not a transient failure. Do NOT retry.
                duration_s = time.monotonic() - t_total_start
                return DispatchResult(
                    raw_output="",
                    triggered_skill=result.triggered_skill,
                    token_usage=None,
                    duration_s=duration_s,
                    error=None,
                )

            # _run_once returned None => transient failure; last_error was set.
            last_error = self._last_error

        duration_s = time.monotonic() - t_total_start
        return DispatchResult(
            raw_output="",
            triggered_skill=None,
            token_usage=None,
            duration_s=duration_s,
            error=last_error or "dispatch failed after retries",
        )

    def _run_once(
        self,
        argv: list[str],
        cwd: Path,
    ) -> subprocess.CompletedProcess[str] | _TimeoutRecovery | None:
        """Run ``argv`` once.

        Returns:
        - ``CompletedProcess`` on a normal (returncode 0) run,
        - ``_TimeoutRecovery`` when the call timed out but its transcript was
          already written (trigger recovered — a valid verdict, not a failure),
        - ``None`` on a transient failure (retryable; ``self._last_error`` set).
        """
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                cwd=cwd,
                env=_eval_subprocess_env(cwd),
                check=False,
            )
        except subprocess.TimeoutExpired:
            # The trigger (first ``Skill`` tool_use) is written to the transcript
            # early — before a slow EXECUTING skill body finishes. Recover it from
            # the transcript (located by cwd slug, since the timeout gave us no
            # result envelope / session_id) rather than mis-recording a false
            # non-trigger.
            #
            # A timeout is TERMINAL — never retried. Retrying re-runs the same
            # expensive call (another full ``self._timeout`` wait) with no reason
            # to behave differently; the original design retried it 3x, turning a
            # single overrun into ~3x the wall-clock for every executing-skill
            # positive. The settle-poll below defeats the flush/visibility race
            # where the just-killed process's transcript is not yet visible at the
            # exact instant of the kill.
            recovered = self._recover_trigger_after_timeout(cwd)
            return _TimeoutRecovery(triggered_skill=recovered)
        except OSError as exc:
            self._last_error = f"OSError: {exc}"
            logger.warning("dispatch: OSError running claude: %s", exc)
            return None
        except Exception as exc:  # noqa: BLE001
            self._last_error = f"unexpected subprocess error: {exc}"
            logger.warning("dispatch: unexpected subprocess error: %s", exc)
            return None

        if proc.returncode != 0:
            self._last_error = (
                f"non-zero returncode {proc.returncode}: "
                f"{(proc.stderr or '')[:200].strip()}"
            )
            logger.warning(
                "dispatch: claude returned returncode=%d stderr=%s",
                proc.returncode,
                (proc.stderr or "")[:200].strip(),
            )
            return None

        return proc

    # Settle-poll for transcript recovery after a timeout kill: total ~1.5 s.
    _RECOVERY_POLL_ATTEMPTS: int = 5
    _RECOVERY_POLL_INTERVAL_S: float = 0.3

    def _recover_trigger_after_timeout(self, cwd: Path) -> str | None:
        """Recover the fired-skill from the transcript after a timeout kill.

        Polls briefly because the killed process's transcript may not be visible
        at the exact instant of the kill. Returns the fired skill name, or
        ``None`` if no transcript appears (genuine non-trigger / startup hang) or
        it contains no ``Skill`` tool_use.
        """
        for attempt in range(self._RECOVERY_POLL_ATTEMPTS):
            transcript = _locate_transcript_by_cwd(cwd)
            if transcript is not None:
                recovered = _parse_transcript_for_skill(transcript)
                logger.warning(
                    "dispatch: timed out after %ss; recovered trigger=%r (transcript found)",
                    self._timeout,
                    recovered,
                )
                return recovered
            if attempt < self._RECOVERY_POLL_ATTEMPTS - 1:
                time.sleep(self._RECOVERY_POLL_INTERVAL_S)
        logger.warning(
            "dispatch: timed out after %ss; no transcript located — recording non-trigger",
            self._timeout,
        )
        return None

    def _build_result(
        self,
        proc: subprocess.CompletedProcess[str],
        tmp: Path,
        t_start: float,
    ) -> DispatchResult:
        """Parse the envelope from a successful subprocess run."""
        stdout = proc.stdout or ""
        raw_output, token_usage, session_id = _parse_envelope(stdout)
        duration_s = time.monotonic() - t_start
        triggered_skill = _derive_triggered_skill(session_id, tmp)

        return DispatchResult(
            raw_output=raw_output,
            triggered_skill=triggered_skill,
            token_usage=token_usage,
            duration_s=duration_s,
            error=None,
        )
