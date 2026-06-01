---
name: map-explain
description: "Deep walkthrough of code, a diff, or the whole project — problem, entities, flow, line-by-line rationale, side effects, assumptions, breakage. Use when learning unfamiliar code or auditing a diff."
---

# $map-explain — Deep Walkthrough

**Purpose:** Build a complete mental model of a target (code, diff, or the whole repository). This skill ONLY teaches — it does NOT plan or execute.

**When to use:**
- Learning unfamiliar code or onboarding to a module
- Auditing a diff before merge
- Bootstrapping a new contributor on an existing project

**Related skills:** `$map-plan` (decomposition before execution), `$map-fast` (small implementations), `$map-check` (post-execution verification).

---

## Target resolution

The skill takes a single argument. Resolve it as follows:

- **File path** (`src/foo/bar.py`) → read the entire file with `shell_command` and treat it as the target.
- **Symbol** (`module.function`, `ClassName.method`) → grep the repo with `shell_command` to find the definition and primary call sites.
- **PR ref** (`#123`, branch name, commit SHA) → fetch the diff via `gh pr diff` or `git show`.
- **Inline snippet** → treat the snippet itself as the target.
- **Empty / no argument** → fall back to one of the two default modes below.

## Default modes (when no argument is passed)

Resolve the upstream base, then pick mode A or B.

```
shell_command:
  cmd: |
    # 1. Pick the upstream base: prefer origin/main, fall back to origin/master.
    BASE=$(git rev-parse --verify --quiet origin/main >/dev/null && echo origin/main \
           || (git rev-parse --verify --quiet origin/master >/dev/null && echo origin/master))

    # 2. Stop early if neither base exists — avoid `git fetch origin ""`.
    if [ -z "$BASE" ]; then
      echo "map-explain: neither origin/main nor origin/master exists; aborting." >&2
      exit 1
    fi

    # 3. Refresh the base so the comparison reflects what would actually merge.
    git fetch origin "${BASE#origin/}" --quiet
    echo "BASE=$BASE"
    echo "CURRENT=$(git rev-parse --abbrev-ref HEAD)"
```

### Mode A — Project overview (current branch is `main`/`master`, OR `HEAD` == `$BASE`)

No branch diff to explain — walk the **whole repository**. Map the 10 sections below onto the project, not a single file:

- Section 1 (problem): what this repository exists to do — derive from `README.md`, then `docs/ARCHITECTURE.md`, `docs/USAGE.md`, `CLAUDE.md` / `AGENTS.md`.
- Section 2 (entities): top-level modules / packages / services. Read the directory listing, entry points, and manifests (`pyproject.toml`, `package.json`, `go.mod`, `Cargo.toml`).
- Section 3 (how they differ): responsibility boundaries — what each entity owns and explicitly does NOT do.
- Section 4 (execution flow): what happens when the primary entry point runs (CLI invocation, server startup, request lifecycle).
- Section 5 (data flow): how data moves between entities — file formats, schemas, IPC, state files, databases.
- Sections 6–7: pick the 3–6 most load-bearing files/functions and walk those line by line. Do NOT try to cover every line in the repo.
- Section 8 (state & side effects): what the project writes to disk, network, or shared services; what survives across runs.
- Section 9 (assumptions): runtime, OS, language version, external services, secrets, env vars, network access.
- Section 10 (breakage modes): kinds of changes that routinely break this project — derive from `CONTRIBUTING.md`, `CHANGELOG.md`, recent commits, or learned-patterns docs.

Skip the "For PRs, also explain" section in this mode — no diff exists.

Bootstrap commands:

```
shell_command:
  cmd: |
    ls -la
    git --no-pager log --oneline -n 20
    # Read these in order if present:
    #   README.md, AGENTS.md, CLAUDE.md, docs/ARCHITECTURE.md, docs/USAGE.md, CONTRIBUTING.md
```

### Mode B — Branch diff (current branch is NOT `main`/`master` and `HEAD` != `$BASE`)

The target is the current branch's diff against the upstream base. Treat it like a PR and **also** produce the "For PRs, also explain" section.

```
shell_command:
  cmd: |
    BASE=$(git rev-parse --verify --quiet origin/main >/dev/null && echo origin/main \
           || (git rev-parse --verify --quiet origin/master >/dev/null && echo origin/master))
    if [ -z "$BASE" ]; then
      echo "map-explain: neither origin/main nor origin/master exists; aborting." >&2
      exit 1
    fi
    git fetch origin "${BASE#origin/}" --quiet
    # Three-dot diff = "what this branch changed relative to base".
    git --no-pager diff --stat "$BASE"...HEAD
    git --no-pager log --oneline "$BASE"..HEAD
    git --no-pager diff "$BASE"...HEAD
```

---

## What the explanation must contain

Teach the target step by step:

1. what problem it solves,
2. what entities exist,
3. how they differ,
4. how execution flows,
5. how data flows,
6. what every important line does,
7. why each non-trivial line is needed,
8. what state changes and side effects happen,
9. what assumptions the code relies on,
10. what could break if I modify it.

### Rules

- do not use terms before explaining them;
- do not skip "obvious" lines;
- do not hide behind abstractions or jargon;
- separate intuition, exact mechanism, and practical meaning;
- if something is inferred rather than explicit, prefix it with `Inferred:`.

### For PRs / diffs, also explain

- what behavior likely existed before,
- what behavior exists after,
- and how the diff changes runtime behavior.

### End with

- key insights,
- common misunderstandings,
- a short precise summary.

---

## How to apply

1. **Locate the target** per the rules above (file / symbol / PR ref / snippet / empty).
2. **Read enough context to answer "why this exists."** Imports, callers, tests, and adjacent files often carry intent the target itself does not.
3. **Walk the 10 sections in order.** Do not collapse them into a single prose blob — the structure is part of the teaching.
4. **Mark inferences** with `Inferred:` so the reader knows the confidence level.
5. **Quote, do not paraphrase,** the lines you explain. Use `file:line` references.
6. **Stop at the target's boundary.** Do not explain the whole codebase — only what is needed to understand this target.

---

## Examples

```
$map-explain                                          # feature branch → diff vs origin/main; on main/master → project overview
$map-explain src/mapify_cli/orchestrator.py
$map-explain map_step_runner.create_review_bundle
$map-explain #108
$map-explain HEAD~1..HEAD
```

---

## Troubleshooting

- **"neither origin/main nor origin/master exists"** — the repo has no upstream named `origin`, or its default branch is not `main`/`master`. Either add an `origin` remote, or pass an explicit target (file path / symbol / PR ref) instead of running with no arguments.
- **`HEAD == $BASE`** — the current branch already matches the upstream base; there is no diff. The skill falls into Mode A (project overview); if that's not what you wanted, check `git status` and confirm your commits are on this branch.
- **Diff is enormous and the walkthrough turns shallow** — pass a narrower target (single file, single symbol, or `HEAD~1..HEAD`) so each line can be explained without truncation.
- **Output mixes inference with source claims** — every non-explicit assertion must be prefixed with `Inferred:`. If you see unmarked guesses, ask the skill to re-emit with explicit confidence tags.
