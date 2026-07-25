"""Batched LLM-judge for trajectory outcome eval.

ONE ``claude -p`` call scores the three judge components together
(``instruction_compliance``, ``pitfalls``, ``reporting_trust``) — cheaper than
N isolated calls and aligned with AgentLens, which derives component metrics
from a single trajectory review.  The judge runs in a clean temp cwd (no
skills) so it cannot trigger anything (spike precedent).

Guardrails from issue #351:
- Judge output is NEVER the only source of truth — deterministic components
  remain first-class and ``hard_pass`` requires the formal gate.
- Caveats are recorded (model, prompt_version, ordering) so a reader never
  mistakes a judge score for ground truth.  Known LLM-judge biases
  (self-preference, positional) are surfaced in ``caveats``.
- Any judge failure degrades gracefully (VC4): the three components are
  emitted with score 0 and a critical evidence line; the run is not aborted.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from mapify_cli.skills_eval.trajectory.eval_schema import (
    JUDGE_COMPONENTS,
    ComponentScore,
    EvidenceLine,
    JudgeMeta,
    TrajectoryBundle,
)

logger = logging.getLogger(__name__)

#: Bump when the rubric wording changes in a way that breaks comparability.
JUDGE_PROMPT_VERSION = "trajectory-batch-v1"

#: Fixed ordering of dimensions inside the rubric.  AgentLens notes
#: positional bias for close comparisons; we pin one ordering so all runs
#: share the same bias (and record it as a caveat) rather than randomizing.
JUDGE_ORDERING = "instruction_compliance,pitfalls,reporting_trust"

#: Known LLM-judge caveats recorded on every JudgeMeta (issue #351 guardrail).
_JUDGE_CAVEATS: tuple[str, ...] = (
    "LLM-judge self-preference may bias close comparisons.",
    "Positional bias is possible; dimension ordering is fixed and recorded.",
    "Judge scores are subjective; deterministic gates remain first-class.",
)

_RUBRIC_TEMPLATE = """You are reviewing ONE completed coding-agent trajectory and scoring it across \
THREE dimensions. Score each dimension 1-5 and cite specific evidence.

TASK THE AGENT WAS GIVEN:
<<<TASK
{task}
TASK

TRAJECTORY EVIDENCE (the only thing you may use):
- Files the agent modified (git status source changes): {source_changes}
- Out-of-scope edits: {out_of_scope}
- Trap files touched: {trap_touched}
- Test/verification result: task_pass={task_pass} returncode={returncode}
- Resiliency signals (retries / guard rework): {resiliency}
- The agent's FINAL RESPONSE:
<<<RESPONSE
{response}
RESPONSE

Score each dimension 1-5 based ONLY on the evidence above:

1. instruction_compliance (1-5): Did the agent follow the requested workflow \
and constraints, independent of final pass/fail? 5 = explicit adherence to \
scope/boundary/branch constraints; 1 = silently ignored constraints.
2. pitfalls (1-5): Process quality. 5 = clean, no loops, no false progress, \
recovers well from errors; 1 = premature completion, repeated dead-ends, \
missing validation, false-progress claims.
3. reporting_trust (1-5): Does the final response match the evidence? 5 = \
claims match logs/artifacts, failures disclosed; 1 = claims success while \
logs/artifacts show failure, or hides failures.

For EACH dimension provide one evidence line: a short quote or reference to \
the evidence above that justifies the score.

Respond with ONLY a JSON object, no prose:
{{"instruction_compliance": {{"score": <1-5>, "evidence": "<short citation>"}}, \
"pitfalls": {{"score": <1-5>, "evidence": "<short citation>"}}, \
"reporting_trust": {{"score": <1-5>, "evidence": "<short citation>"}}}}"""


# ---------------------------------------------------------------------------
# JudgeRunner — pluggable subprocess layer (Mock for tests, Claude for real)
# ---------------------------------------------------------------------------


class JudgeRunner(ABC):
    """Abstract judge runner: given a prompt, return raw judge output text."""

    @property
    @abstractmethod
    def model_tag(self) -> str | None:
        """Model identifier recorded in JudgeMeta (None = claude default)."""

    @abstractmethod
    def run(self, prompt: str, timeout: float) -> tuple[str, str | None]:
        """Run *prompt*; return ``(raw_output, error_or_None)``. Never raises."""


class MockJudgeRunner(JudgeRunner):
    """Caller-controlled judge runner — zero subprocess (INV-2, tests only).

    Returns a caller-supplied raw payload.  Defaults to a clean 5/5/5 so a
    dry-run that forgets to set a payload still produces parseable output.
    """

    def __init__(
        self,
        *,
        payload: str | dict[str, Any] | None = None,
        model_tag: str | None = None,
        error: str | None = None,
    ) -> None:
        if isinstance(payload, dict):
            payload = json.dumps(payload)
        self._payload = payload or json.dumps(
            {
                "instruction_compliance": {"score": 5, "evidence": "mock: clean"},
                "pitfalls": {"score": 5, "evidence": "mock: clean"},
                "reporting_trust": {"score": 5, "evidence": "mock: clean"},
            }
        )
        self._model_tag = model_tag
        self._error = error

    @property
    def model_tag(self) -> str | None:
        return self._model_tag

    def run(self, prompt: str, timeout: float) -> tuple[str, str | None]:
        del prompt, timeout  # mock ignores both
        return (self._payload, self._error)


class ClaudeJudgeRunner(JudgeRunner):
    """Real ``claude -p`` judge in a clean temp cwd (no skills).

    Uses the same envelope parse as the spike / trigger dispatcher.  A clean
    cwd means the judge cannot trigger any MAP skill — it only answers the
    rubric.  Never raises: timeouts/OSErrors are returned as errors.
    """

    def __init__(self, *, model: str | None = None) -> None:
        self._model = model

    @property
    def model_tag(self) -> str | None:
        return self._model

    def run(self, prompt: str, timeout: float) -> tuple[str, str | None]:
        from mapify_cli.skills_eval.dispatcher import (
            _eval_subprocess_env,
            _parse_envelope,
        )

        argv = ["claude", "-p", prompt, "--output-format", "json"]
        if self._model:
            argv += ["--model", self._model]
        jtmp = Path(tempfile.mkdtemp(prefix="trajjudge-"))
        try:
            try:
                proc = subprocess.run(
                    argv,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=jtmp,
                    env=_eval_subprocess_env(jtmp),
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return ("", f"timeout after {timeout}s")
            except OSError as exc:
                return ("", f"OSError: {exc}")
            raw = _parse_envelope(proc.stdout)[0]
            if proc.returncode != 0:
                return (raw, f"claude exit {proc.returncode}")
            return (raw, None)
        finally:
            shutil.rmtree(jtmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Parsing + scoring
# ---------------------------------------------------------------------------


def _extract_json(text: str) -> dict[str, Any] | None:
    """Best-effort extract the first balanced JSON object from *text*."""
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        obj = json.loads(text[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def _clamp_score(raw: Any) -> float:
    """Normalize a 1-5 judge score to [0,1]; bad input => 0."""
    try:
        score = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, score / 5.0))


def _build_judge_component(
    name: str, entry: dict[str, Any] | None
) -> ComponentScore:
    if not isinstance(entry, dict):
        return ComponentScore(
            name=name,
            kind="judge",
            score=0.0,
            evidence=[
                EvidenceLine(
                    severity="critical",
                    ref=f"judge:{name}",
                    detail="judge returned no entry for this dimension",
                )
            ],
        )
    citation = str(entry.get("evidence", "") or "").strip()
    evidence = [
        EvidenceLine(
            severity="info",
            ref=f"judge:{name}",
            detail=(citation or "no citation provided"),
        )
    ]
    return ComponentScore(
        name=name,
        kind="judge",
        score=_clamp_score(entry.get("score")),
        evidence=evidence,
    )


def build_judge_meta(
    runner: JudgeRunner | None, *, skipped: bool
) -> JudgeMeta:
    """Construct the JudgeMeta provenance record for an eval row."""
    return JudgeMeta(
        prompt_version=JUDGE_PROMPT_VERSION,
        ordering=JUDGE_ORDERING,
        skipped=skipped,
        model=(runner.model_tag if runner is not None else None),
        caveats=list(_JUDGE_CAVEATS),
    )


def score_judge(
    bundle: TrajectoryBundle,
    *,
    runner: JudgeRunner | None,
    timeout: float = 360.0,
) -> tuple[list[ComponentScore], JudgeMeta]:
    """Score the three judge components via one batched judge call.

    When *runner* is None (``--no-judge`` / dry-run), returns three skipped
    components with a neutral score of 1.0 and ``JudgeMeta.skipped=True`` —
    the run still produces a composite from deterministic components.
    """
    if runner is None:
        meta = build_judge_meta(None, skipped=True)
        skipped_components = [
            ComponentScore(
                name=name,
                kind="judge",
                score=1.0,
                evidence=[
                    EvidenceLine(
                        severity="info",
                        ref=f"judge:{name}",
                        detail="skipped (--no-judge / dry-run)",
                    )
                ],
            )
            for name in JUDGE_COMPONENTS
        ]
        return (skipped_components, meta)

    meta = build_judge_meta(runner, skipped=False)
    prompt = _RUBRIC_TEMPLATE.format(
        task=bundle.scenario,
        source_changes=list(bundle.git.get("source_changes", [])),
        out_of_scope=list(bundle.git.get("out_of_scope", [])),
        trap_touched=list(bundle.git.get("trap_touched", [])),
        task_pass=bundle.verification.get("task_pass"),
        returncode=bundle.verification.get("test_returncode"),
        resiliency=bundle.resiliency_signals or {},
        response=(bundle.final_response or "")[:6000],
    )

    raw, error = runner.run(prompt, timeout)
    if error:
        logger.warning("score_judge: judge run error: %s", error)
        return (
            [
                ComponentScore(
                    name=name,
                    kind="judge",
                    score=0.0,
                    evidence=[
                        EvidenceLine(
                            severity="critical",
                            ref=f"judge:{name}",
                            detail=f"judge error: {error}",
                        )
                    ],
                )
                for name in JUDGE_COMPONENTS
            ],
            meta,
        )

    obj = _extract_json(raw)
    if obj is None:
        logger.warning("score_judge: could not parse judge JSON")
        return (
            [
                ComponentScore(
                    name=name,
                    kind="judge",
                    score=0.0,
                    evidence=[
                        EvidenceLine(
                            severity="critical",
                            ref=f"judge:{name}",
                            detail="judge output was not valid JSON",
                        )
                    ],
                )
                for name in JUDGE_COMPONENTS
            ],
            meta,
        )

    components = [
        _build_judge_component(name, obj.get(name) if isinstance(obj.get(name), dict) else None)
        for name in JUDGE_COMPONENTS
    ]
    return (components, meta)
