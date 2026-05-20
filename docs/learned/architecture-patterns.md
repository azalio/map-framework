# Architecture Patterns (Learned)

<!-- IMPROVEMENT-PLAN-LOOP: promoted from loop learnings. Edit freely and commit with the project. -->

- **Limit Budget Reports To Active Prompt Paths** (2026-05-20): When adding prompt-budget observability, write decisions only from prompt builders that already enforce budgets in production workflows because telemetry for dormant mechanisms does not improve the current user workflow. [workflow: improvement-plan-loop]
- **Externalize recovery appendices** (2026-05-20): Skills used after context loss should keep `SKILL.md` focused on the active recovery decision and link to supporting files for examples, state-shape references, token notes, and troubleshooting so compaction recovery does not re-load low-frequency appendices by default. [workflow: improvement-plan-loop]
- **Keep high-traffic task skills compact** (2026-05-20): When a task skill is part of the normal MAP golden path, keep active `SKILL.md` focused on next-action flow and move examples, troubleshooting, and low-frequency rationale to supporting files because invoked skill bodies remain in context and are reattached after compaction. [workflow: improvement-plan-loop]

