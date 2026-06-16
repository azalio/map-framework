---
name: map-understand
description: "Interactive deep-understanding and quiz mode for MAP sessions. Use when the user wants to understand code, a diff, workflow result, debugging cause, or architecture and be checked with restatements or quizzes."
---

# $map-understand - Interactive Learning Check

**Purpose:** Make the user's understanding a first-class deliverable. This skill teaches and checks comprehension; it does not plan, implement, review, or persist project lessons.

**When to use:**
- After a complex MAP workflow, debugging session, or architectural review
- When onboarding to unfamiliar code or a branch diff
- When the user asks to be quizzed or to verify their own understanding

**Related skills:** `$map-explain` for one-shot walkthroughs, `$map-learn` for saved project memory, `$map-check` for verification gates.

---

## Behavior Contract

- This skill is opt-in only. Do not make ordinary `$map-*` workflows more verbose because this skill exists.
- Keep the checklist transient in the conversation. Do not create or update files from this skill.
- Use gender-neutral wording.
- Maintain a running Markdown checklist named `Understanding checklist` and update it as the user demonstrates understanding.
- Cover the problem/context, why it existed, alternatives or branches considered, the solution, design decisions, edge cases, and broader impact.
- Work incrementally. Teach one milestone, ask for a restatement or quiz answer, then fill gaps before moving on.
- Multiple-choice checks are allowed, but do not reveal the answer key before the user responds.
- End only when the user demonstrates enough understanding for the selected depth or explicitly opts out.

## Depth Modes

Infer the depth from the arguments when present:

| Mode | Use When | Teaching Style |
|---|---|---|
| `eli5` | Simple conceptual explanation | Metaphors first, no jargon until defined |
| `eli14` | Practical beginner explanation | Simple mechanics, light terminology, concrete examples |
| `intern` | Default engineering onboarding | Explain why, how, tradeoffs, and common mistakes |
| `expert` | Domain-aware user | Focus on invariants, edge cases, consequences, and alternatives |

If no depth is provided, default to `intern`.

## Target Resolution

Resolve the target before teaching:

- File path, directory, symbol, PR ref, commit range, or code snippet -> use that target.
- Workflow artifact such as `.map/<branch>/learning-handoff.md`, `verification-summary.md`, `review-bundle.md`, `run_health_report.json`, or `task_plan_<branch>.md` -> read it and any directly referenced files needed to explain it.
- Empty on a feature branch -> explain the branch diff against `origin/main` or `origin/master`.
- Empty on `main`/`master` -> explain the project or latest relevant `.map/<branch>/` handoff when one clearly exists.

Bootstrap commands for empty-target branch diff mode:

```
shell_command:
  cmd: |
    BASE=$(git rev-parse --verify --quiet origin/main >/dev/null && echo origin/main \
           || (git rev-parse --verify --quiet origin/master >/dev/null && echo origin/master))
    if [ -n "$BASE" ]; then
      git fetch origin "${BASE#origin/}" --quiet
      git --no-pager diff --stat "$BASE"...HEAD
      git --no-pager diff "$BASE"...HEAD
    fi
```

---

## Teaching Loop

1. State the selected depth, target, and evidence read.
2. Create an `Understanding checklist` with 5-9 unchecked, concrete items.
3. Teach the first milestone only: usually problem/context and why it existed.
4. Ask one open-ended restatement question or one multiple-choice question. Withhold the answer key for multiple-choice.
5. After the user responds, mark checklist items complete only when the response shows understanding. Correct gaps briefly.
6. Repeat for design decisions, implementation mechanics, edge cases, alternatives, and impact.
7. Close with a final summary/application check. End with the final checklist state only after the user passes or opts out.

## Check Question Guidance

Prefer open-ended checks:

- "Restate why this bug happened in your own words."
- "What would break if we removed this guard?"
- "Which alternative did we reject, and why?"

Use multiple-choice only when it helps focus the learner:

```text
Which invariant matters most here?
A. The cache is always warm before validation.
B. The validator must reject stale generated surfaces before install.
C. The CLI should skip template rendering when tests pass.

Pick one and explain why. I will not reveal the answer until you answer.
```

## Examples

```
$map-understand --depth intern
$map-understand --depth eli14 src/mapify_cli/delivery/template_renderer.py
$map-understand --depth expert HEAD~1..HEAD
$map-understand .map/my-branch/verification-summary.md
```

## Troubleshooting

- **The user wants only a walkthrough, no quiz** - use `$map-explain` instead, or ask one confirmation question and stop if they opt out.
- **The user wants lessons saved for future sessions** - use `$map-learn`; this skill intentionally does not write learned-rule or `.map/` artifacts.
- **The target is huge** - teach the highest-leverage slice first and ask whether to continue with another slice.
- **The user answers incorrectly** - do not advance the checklist. Correct the exact misconception and ask a simpler follow-up.
- **A multiple-choice answer was accidentally revealed early** - discard that check and ask a new question without an answer key.
