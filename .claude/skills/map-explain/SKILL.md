---
name: map-explain
description: |
  Deep walkthrough that builds a mental model of code, a diff, or the project — flow, side effects, assumptions, breakage. Use when learning unfamiliar code or auditing a diff. Do NOT use to plan or implement; use map-plan or map-efficient.
disable-model-invocation: true
argument-hint: "[file path | symbol | PR ref | code snippet | empty for branch diff vs origin/main (fallback origin/master), or project overview on main/master]"
---
# MAP Explain

**Target:** $ARGUMENTS

## Default target (when $ARGUMENTS is empty)

Pick mode by inspecting the current branch and its relation to the upstream base:

```bash
# 1. Pick the upstream base: prefer origin/main, fall back to origin/master.
BASE=$(git rev-parse --verify --quiet origin/main >/dev/null && echo origin/main \
       || (git rev-parse --verify --quiet origin/master >/dev/null && echo origin/master))

# 2. Stop early if neither base exists — do not run a fetch/diff against an
#    empty ref (otherwise `git fetch origin ""` raises a confusing error).
if [ -z "$BASE" ]; then
  echo "map-explain: neither origin/main nor origin/master exists; aborting." >&2
  exit 1
fi

# 3. Refresh the base so the comparison reflects what would actually merge.
git fetch origin "${BASE#origin/}" --quiet

CURRENT=$(git rev-parse --abbrev-ref HEAD)
```

Then choose **one** of the two modes below and follow it.

### Mode A — Project overview (current branch is `main` or `master`, OR `HEAD` == `$BASE`)

There is no branch diff to explain — explain the project as a whole instead. Produce a single project-level walkthrough that follows the 10 sections below at the **repository** level, not at a single-file level:

- Section 1 (problem): what this repository exists to do — derive from `README.md` first, then top-level docs (`docs/ARCHITECTURE.md`, `docs/USAGE.md`, `CLAUDE.md`).
- Section 2 (entities): the top-level modules / packages / services that make up the project (read the top-level directory listing, primary entry points, and any package/manifest files like `pyproject.toml`, `package.json`, `go.mod`, `Cargo.toml`).
- Section 3 (how they differ): the responsibility boundary between those entities — what each one owns and what it explicitly does NOT do.
- Section 4 (execution flow): what happens when the primary entry point runs (CLI invocation, server startup, request lifecycle — whichever applies). Trace from entry point through the main code paths.
- Section 5 (data flow): what data moves between the entities — file formats, schemas, IPC, state files, databases.
- Sections 6–7: do NOT try to cover every line in the repo. Instead, pick the 3–6 most architecturally load-bearing files/functions and walk those.
- Section 8 (state & side effects): what the project writes to disk, the network, or shared services; what survives across runs.
- Section 9 (assumptions): runtime, OS, language version, external services, secrets, env vars, network access.
- Section 10 (breakage modes): what kinds of changes routinely break this project, based on `CONTRIBUTING.md`, `CHANGELOG.md`, recent commit messages, or learned-patterns docs if present.

Skip the "For PRs, also explain" section in this mode — there is no diff.

Useful commands to bootstrap:

```bash
ls -la
git --no-pager log --oneline -n 20
# Read these in order if present:
#   README.md, CLAUDE.md, docs/ARCHITECTURE.md, docs/USAGE.md, CONTRIBUTING.md
```

### Mode B — Branch diff (current branch is NOT `main`/`master` and `HEAD` != `$BASE`)

The target is the current branch's diff against the upstream base. Treat the resulting diff exactly like a PR target — also produce the "For PRs, also explain" section.

```bash
# Three-dot diff = "what this branch changed relative to base".
git --no-pager diff --stat "$BASE"...HEAD
git --no-pager log --oneline "$BASE"..HEAD
git --no-pager diff "$BASE"...HEAD
```

### Edge cases (apply to both modes)

- If the working tree has uncommitted changes you also want explained, say so and include `git diff` (unstaged) and `git diff --cached` (staged) on top of whatever the chosen mode produced.

Explain it so I can build a complete mental model of it, not just a summary.

I want you to teach it step by step:

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

## Rules

- do not use terms before explaining them;
- do not skip "obvious" lines;
- do not hide behind abstractions or jargon;
- separate intuition, exact mechanism, and practical meaning;
- if something is inferred rather than explicit, mark it clearly.

## For PRs, also explain

- what behavior likely existed before,
- what behavior exists after,
- and how the diff changes runtime behavior.

## End with

- key insights,
- common misunderstandings,
- and a short precise summary.

## How to apply

1. **Locate the target.** If `$ARGUMENTS` is empty, pick **Mode A** (project overview) or **Mode B** (branch diff) per the rules above. If it's a file path, read the whole file. If it's a symbol, grep the codebase to find the definition and primary call sites. If it's a PR ref (`#N`, branch name, commit SHA), fetch the diff with `git show` / `gh pr diff`. If it's an inline snippet, treat the snippet itself as the target.
2. **Read enough context to answer "why this exists."** Imports, callers, tests, and adjacent files often carry intent the target itself does not.
3. **Walk the 10 sections in order.** Do not collapse them into a single prose blob — the structure is part of the teaching.
4. **Mark inferences.** When asserting something the source does not directly state (e.g., "this is likely called from the request handler"), prefix it with `Inferred:` so the reader knows the confidence level.
5. **Quote, do not paraphrase, the lines you explain.** Use `file:line` references so the reader can navigate.
6. **Stop at the target's boundary.** Do not explain the whole codebase — only what is needed to understand this target's behavior.

## Examples

```
/map-explain                                          # on a feature branch: explain its diff vs origin/main; on main/master: explain the project
/map-explain src/mapify_cli/orchestrator.py
/map-explain map_step_runner.create_review_bundle
/map-explain #108
/map-explain HEAD~1..HEAD
```

## Troubleshooting

- **"neither origin/main nor origin/master exists"** — the repo has no upstream named `origin`, or its default branch is not `main`/`master`. Either add an `origin` remote, or pass an explicit target (file path / symbol / PR ref) instead of running with no arguments.
- **"HEAD == $BASE"** — the current branch already matches the upstream base, so there is no diff. The skill falls into Mode A (project overview); if that is not what you wanted, check `git status` and confirm your commits are on this branch.
- **Diff is enormous and the walkthrough turns shallow** — pass a narrower target (single file, single symbol, or `HEAD~1..HEAD`) instead of the full branch diff so each line can be explained without truncation.
- **Output mixes inference with source claims** — every non-explicit assertion must be prefixed with `Inferred:`. If you see un-marked guesses, ask the skill to re-emit with explicit confidence tags.
