# **map-framework: controlling quality and context in complex engineering tasks**

---

## 0. Introduction

This video is not about “AI writing code for you”.

It is about **how to structure an engineering process** so that LLMs:

* reduce the risk of hallucination,
* surface quality degradation early,
* and flag potentially unsafe decisions.

The goal is to show a *real working cycle* on a non-trivial task in a large monorepository, with explicit control points and human-in-the-loop decision making.

---

## 1. The problem: large monorepository and context loss

The project contains thousands of files and multiple subsystems.
Traditional grep-based navigation is slow and syntactically blind.

Using a single LLM without structure often leads to:

* loss of architectural context,
* local optimizations with global regressions,
* false confidence in partially correct solutions.

---

## 2. ChunkHound: semantic memory of the repository

Before starting active work, the repository is indexed using ChunkHound.

ChunkHound:

* parses files into semantic chunks,
* generates embeddings,
* indexes code semantically for retrieval.

ChunkHound itself is not an agent.
It is a **semantic memory layer** used by Research to navigate large codebases more effectively.

---

## 3. Roles in map-framework

map-framework separates responsibilities explicitly:

* **Actor** performs implementation steps.
* **Monitor** evaluates results and flags correctness, safety, or quality concerns.
* **Research** performs semantic queries over the repository using ChunkHound.
* **llm-counsul** is used as a *decision validation pattern*.
* **Learn** captures experience after phase completion.

Each role has a single primary responsibility.
Workflows are orchestrated through **MCP-compatible CLI commands**, making each step explicit, inspectable, and user-controlled.

---

## 4. Phase 0: planning

The task starts with `map-plan`, producing:

* phased decomposition,
* identified risk areas,
* explicit control points.

The plan is treated as a **working hypothesis**, not as a final truth.
It is expected to evolve as new information is discovered.

---

## 5. llm-counsul: validating decisions

At critical points (for example, after planning), the **llm-counsul pattern** is applied.

This pattern involves running **multiple independent LLM evaluations** over the same context to surface divergent risks and blind spots.

In practice:

* orchestration is performed via explicit map commands,
* execution is user-controlled,
* aggregation is deliberate and visible rather than implicit.

If any evaluation raises a clearly argued critical concern (for example, related to security or data integrity), the **recommended practice** is to pause and involve human review before proceeding.

The purpose of llm-counsul is not consensus, but **controlled divergence**.

---

## 6. Phase 1: sequential implementation with Monitor

Actor performs implementation step by step.

After each step:

* Monitor evaluates the result,
* concerns are flagged for resolution before further progress.

For example, Monitor may flag a change that modifies a shared schema or API without corresponding migration steps or compatibility guarantees.

If repeated rework attempts fail to address Monitor’s concerns, escalation to a **human decision** is required.

Monitor does not “break” the process.
It ensures that progress is not built on weak or unexamined foundations.

---

## 7. Research in practice

When Actor or Monitor needs additional context, Research is used.

Research:

* queries ChunkHound,
* finds existing patterns,
* locates similar implementations,
* surfaces relevant tests and conventions.

This reduces reinvention and lowers error rates, but **does not guarantee correctness**.
All retrieved context is treated as advisory, not authoritative.

---

## 8. Learn: capturing experience

After completing a phase, `map-learn` is executed.

Learn:

* extracts patterns and lessons,
* stores experience for future tasks,
* does not affect the current task.

ChunkHound indexes code semantically.
Learn captures **experience and decisions**.

---

## 9. Testing and real-world failures

The scenario intentionally includes:

* incorrect local execution,
* deployment errors,
* Helm chart mistakes,
* destructive operations executed with explicit user approval.

Errors are treated as **normal and expected**.

map-framework does not prevent mistakes.
It makes them visible, inspectable, and easier to reason about.

Recovery remains **user-driven**, not automatic.

---

## 10. Scaling and parallelism

Later phases may involve multiple tasks progressing in parallel.

Parallel execution is achieved through **explicit user coordination** (for example, multiple terminals or task contexts), rather than implicit framework-managed concurrency.

LLMs explicitly request missing information instead of making assumptions.

Parallelism is observable and controllable, but not automatic.

---

## 11. Conclusion

map-framework is not a speed booster for code generation.

It is a system that:

* reduces bad decisions,
* preserves architectural context,
* provides explicit quality checkpoints,
* and scales engineering thinking without removing human responsibility.

---

## Final note to the viewer

map-framework is designed to **surface uncertainty**, not eliminate it.

If a system never asks questions, never escalates, and never pauses — it is unsafe by design.
