# MAP Framework Roadmap

Этот документ переводит [improvement-plan](./improvement-plan.md) в рабочий порядок внедрения для `map-framework`.

Он опирается на 4 исходника:

- [Improvement Plan](./improvement-plan.md) — полный список идей и rationale
- [Architecture](./ARCHITECTURE.md) — как MAP устроен сейчас
- [Usage](./USAGE.md) — как MAP подаётся пользователю сейчас
- [MAP philosophy / DevOpsConf draft](./devopsconf_2026_ai_operator_presentation_rewrite-v2.md) — целевая философия `SPEC -> PLAN -> TEST -> CODE -> REVIEW -> LEARN`

## Зафиксированные продуктовые решения

- Для нетривиальных задач MAP должен требовать `SPEC + PLAN` как обязательный минимум.
- Для серьёзных изменений `REVIEW` должен оставаться обязательным этапом.
- `LEARN` обязателен в философии MAP, но не должен быть hard runtime gate: пользователи экономят токены.
- Для тривиальных задач нужен явный off-ramp: не каждая работа должна запускать MAP orchestration.
- Сначала надо выровнять runtime под философию процесса, и только потом aggressively шлифовать prompts, skills и advanced orchestration.

## Что делать сначала

Главный вывод из [improvement-plan](./improvement-plan.md): улучшать надо не “всё подряд”, а в таком порядке:

1. Сделать MAP честной реализацией своей процессной философии.
2. Потом модернизировать командный слой под Claude 4.6.
3. Потом дочистить skills и command/skill drift.
4. Только потом идти в дорогой orchestration R&D.

## Iteration 1: Runtime Alignment With MAP Philosophy

**Почему это first:** сейчас главный риск MAP не в wording, а в том, что runtime местами расходится с философией `SPEC -> PLAN -> TEST -> CODE -> REVIEW -> LEARN`.

**Improvement-plan items:** `2604.038`, `2604.039`, `2604.036`

### Scope

- Ввести workflow-fit classifier и явный off-ramp для тривиальных задач.
- Сделать artifact pipeline явным: `spec`, `plan`, `test contract`, `implementation`, `review`, `verification`, `learn handoff`.
- Усилить разрыв между `TEST` и `CODE`: persisted handoff вместо слитного “одна сессия всё делает”.

### Main deliverables

- Preflight decision matrix: `direct edit` vs `/map-fast` vs `/map-efficient` vs `/map-tdd`
- Branch-scoped `artifact_manifest`
- `test_contract_<branch>.md` / `test_handoff_<subtask>.json` или эквивалентный persisted handoff
- Updated docs that describe one canonical artifact pipeline for serious work

### Primary files

- [README.md](../README.md)
- [docs/USAGE.md](./USAGE.md)
- [docs/ARCHITECTURE.md](./ARCHITECTURE.md)
- [src/mapify_cli/templates/commands/map-plan.md](../src/mapify_cli/templates/commands/map-plan.md)
- [src/mapify_cli/templates/commands/map-efficient.md](../src/mapify_cli/templates/commands/map-efficient.md)
- [src/mapify_cli/templates/commands/map-tdd.md](../src/mapify_cli/templates/commands/map-tdd.md)
- [src/mapify_cli/templates/map/scripts/map_orchestrator.py](../src/mapify_cli/templates/map/scripts/map_orchestrator.py)
- [src/mapify_cli/templates/map/scripts/map_step_runner.py](../src/mapify_cli/templates/map/scripts/map_step_runner.py)
- [src/mapify_cli/workflow_state.py](../src/mapify_cli/workflow_state.py)
- [src/mapify_cli/schemas.py](../src/mapify_cli/schemas.py)

### Exit criteria

- Нетривиальная задача больше не стартует “сразу в implementation”.
- У complex/TDD flows есть явный persisted contract between planning, tests, and code.
- MAP умеет честно сказать: “для этой задачи orchestration не нужен”.

### How We Will Achieve It

#### Step 1. Add a workflow-fit preflight

Сначала ввести простой classifier перед полноценным MAP flow.

Он должен отвечать на вопрос:
- нужен ли вообще MAP
- если нужен, то какой именно surface запускать: `/map-fast`, `/map-efficient`, `/map-tdd`

Это не должен быть “умный черный ящик”. Это должен быть короткий decision gate на основе:
- blast radius
- expected diff size
- есть ли новая модель / инварианты
- нужен ли независимый review
- есть ли ясные acceptance criteria

**Implementation surfaces:**
- [src/mapify_cli/templates/commands/map-plan.md](../src/mapify_cli/templates/commands/map-plan.md)
- [README.md](../README.md)
- [docs/USAGE.md](./USAGE.md)

**Expected result:**
- trivial work can exit with `direct edit / no MAP orchestration recommended`
- non-trivial work is routed into `SPEC + PLAN` before implementation

#### Step 2. Make the artifact pipeline explicit

Сейчас у MAP уже есть `spec_<branch>.md`, `task_plan_<branch>.md`, `step_state.json`, verification/state artifacts, но они ещё не оформлены как один stage contract.

Нужно добавить явный `artifact_manifest` уровня workflow, который фиксирует статус стадий:
- `spec`
- `plan`
- `test_contract`
- `implementation`
- `review`
- `verification`
- `learn_handoff`

Этот манифест должен обновляться orchestrator/runtime layer, а не вручную пользователем.

**Implementation surfaces:**
- [src/mapify_cli/schemas.py](../src/mapify_cli/schemas.py)
- [src/mapify_cli/workflow_state.py](../src/mapify_cli/workflow_state.py)
- [src/mapify_cli/templates/map/scripts/map_orchestrator.py](../src/mapify_cli/templates/map/scripts/map_orchestrator.py)
- [src/mapify_cli/templates/map/scripts/map_step_runner.py](../src/mapify_cli/templates/map/scripts/map_step_runner.py)

**Expected result:**
- MAP знает, какой stage artifact produced and consumed at each step
- review and later stages stop reconstructing intent from raw diff alone

#### Step 3. Split TEST and CODE with a persisted handoff

Это ключевой runtime change Iteration 1.

Сейчас `/map-tdd` правильно делает `TEST_WRITER -> TEST_FAIL_GATE -> ACTOR`, но всё ещё внутри одного orchestration stream. Этого недостаточно для философии clean-session testing.

Нужно сделать persisted handoff между TEST и CODE:
- после `TEST_FAIL_GATE` можно завершить run в состоянии `contract_ready`
- создаются `test_contract_<branch>.md` и `test_handoff_<subtask>.json` или эквивалентные artifacts
- следующий implementation run читает только:
  - spec
  - plan
  - failing tests
  - compact test handoff

То есть implementation stage должен работать от контракта, а не от полной test-authoring deliberation.

**Implementation surfaces:**
- [src/mapify_cli/templates/commands/map-tdd.md](../src/mapify_cli/templates/commands/map-tdd.md)
- [src/mapify_cli/templates/commands/map-efficient.md](../src/mapify_cli/templates/commands/map-efficient.md)
- [src/mapify_cli/templates/map/scripts/map_orchestrator.py](../src/mapify_cli/templates/map/scripts/map_orchestrator.py)
- [src/mapify_cli/templates/map/scripts/map_step_runner.py](../src/mapify_cli/templates/map/scripts/map_step_runner.py)

**Expected result:**
- tests become a real reviewable artifact
- implementation no longer continues inside the same context that authored the tests
- MAP gets closer to `TEST -> CODE in separate sessions` without forcing awkward manual ceremony

#### Step 4. Add guardrails for contract-sized subtasks

Когда artifact pipeline уже есть, можно вводить process guardrails не через rhetoric, а через runtime data.

Нужно добавить в planning/decomposition layer:
- `expected_diff_size`
- `concern_type`
- one-logical-step expectations per subtask

А потом использовать это в Monitor / final verification for warnings or blocks when:
- subtask diff is too large to review comfortably
- one subtask mixes too many concern types without justification

**Implementation surfaces:**
- [src/mapify_cli/templates/commands/map-plan.md](../src/mapify_cli/templates/commands/map-plan.md)
- [src/mapify_cli/templates/commands/map-efficient.md](../src/mapify_cli/templates/commands/map-efficient.md)
- [src/mapify_cli/schemas.py](../src/mapify_cli/schemas.py)

**Expected result:**
- smaller, more reviewable subtasks
- less scope creep inside a single execution step

#### Step 5. Lock the change set down with tests

Iteration 1 is not complete if it exists only in docs and prompts. It needs runtime and artifact tests.

**Primary test surfaces:**
- [tests/test_map_orchestrator.py](../tests/test_map_orchestrator.py)
- [tests/test_map_step_runner.py](../tests/test_map_step_runner.py)
- [tests/test_workflow_state.py](../tests/test_workflow_state.py)
- [tests/test_verification_recorder.py](../tests/test_verification_recorder.py)

**Tests to add:**
- workflow-fit classifier routes trivial vs non-trivial tasks correctly
- artifact manifest is created and updated through stage transitions
- TDD flow can stop after `TEST_FAIL_GATE` and resume implementation from persisted contract
- resuming from persisted test contract survives context reset / restart
- oversized or mixed-concern subtasks are surfaced as warnings or blocked states according to the chosen policy

#### Recommended PR sequence

Чтобы это не развалилось в один огромный refactor, внедрять лучше так:

1. workflow-fit classifier + docs routing
2. artifact manifest schema + runtime updates
3. split TEST/CODE handoff for TDD
4. contract-sized subtask guardrails
5. tests + template sync + docs cleanup

## Iteration 2: Review Independence And Soft LEARN Ergonomics

**Почему next:** когда task-fit и artifact flow уже выровнены, следующий приоритет — сделать review действительно независимым и вернуть `LEARN` на правильное место без hard enforcement.

**Improvement-plan items:** `2604.037`, `2604.035`

### Scope

- Detached review context: review bundle, optional detached/worktree mode.
- Cheap closeout path for `LEARN`: handoff artifact, prefilled invocation, batch learning.

### Main deliverables

- Canonical `review_bundle` artifact that consumes spec + tests + diff + verification context
- Optional detached review mode for serious changes
- `learning_handoff_<branch>.md` or `.json`
- Docs that say: `LEARN` is philosophically required, but runtime leaves token spend to the user

### Primary files

- [src/mapify_cli/templates/commands/map-review.md](../src/mapify_cli/templates/commands/map-review.md)
- [src/mapify_cli/templates/commands/map-check.md](../src/mapify_cli/templates/commands/map-check.md)
- [src/mapify_cli/templates/commands/map-learn.md](../src/mapify_cli/templates/commands/map-learn.md)
- [src/mapify_cli/templates/skills/map-learn/SKILL.md](../src/mapify_cli/templates/skills/map-learn/SKILL.md)
- [docs/USAGE.md](./USAGE.md)
- [docs/ARCHITECTURE.md](./ARCHITECTURE.md)
- [README.md](../README.md)

### Exit criteria

- `/map-review` больше не зависит в основном от implementer context.
- `LEARN` больше не выглядит как случайная “optional hint at the end”.
- Пользователь может отложить learning без потери контекста и без ручной пересборки summary.

## Iteration 3: Command Layer Modernization For Claude 4.6

**Почему только теперь:** prompt tuning полезен, но он не должен маскировать structural issues в runtime.

**Improvement-plan items:** `2604.025`, `2604.026`, `2604.027`, `2604.028`, `2604.029`

### Scope

- Смягчить overbearing guardrails и calibrate command tone.
- Унифицировать XML/context envelopes.
- Добавить few-shot examples и evidence-first output contracts.
- Перевести lightweight flows в action-first tool use.
- Ввести command-specific thinking/parallelism policies.

### Main deliverables

- Shared prompt envelope for `.claude/commands/map-*.md`
- Shared examples library for the most common JSON contracts
- Updated `/map-fast` and `/map-debug` without “return full file content”
- Explicit `thinking_policy` and `parallel_tool_policy` blocks per command

### Primary files

- [src/mapify_cli/templates/commands/map-fast.md](../src/mapify_cli/templates/commands/map-fast.md)
- [src/mapify_cli/templates/commands/map-debug.md](../src/mapify_cli/templates/commands/map-debug.md)
- [src/mapify_cli/templates/commands/map-review.md](../src/mapify_cli/templates/commands/map-review.md)
- [src/mapify_cli/templates/commands/map-plan.md](../src/mapify_cli/templates/commands/map-plan.md)
- [src/mapify_cli/templates/commands/map-efficient.md](../src/mapify_cli/templates/commands/map-efficient.md)
- [src/mapify_cli/templates/commands/map-tdd.md](../src/mapify_cli/templates/commands/map-tdd.md)
- [src/mapify_cli/templates/hooks/workflow-context-injector.py](../src/mapify_cli/templates/hooks/workflow-context-injector.py)
- [docs/USAGE.md](./USAGE.md)

### Exit criteria

- Commands stop sounding like they are compensating for older model behavior.
- Lightweight workflows write code via tools, not via serialized full-file payloads.
- Long-context commands share one readable, repeatable prompt structure.

## Iteration 4: Skills Consolidation And Catalog Hygiene

**Почему после command layer:** skills matter, but right now they are not the biggest source of product drift.

**Improvement-plan items:** `2604.030`, `2604.031`, `2604.032`, `2604.033`, `2604.034`

### Scope

- Eliminate command/skill drift.
- Fix metadata quality and frontmatter hygiene.
- Explicitly define `reference` vs `task` skills.
- Move heavy content into supporting files.
- Add trigger/invocation regression tests.

### Main deliverables

- One canonical source of truth for overlapping command/skill surfaces
- Clean descriptions and invocation metadata
- Honest skill taxonomy docs
- Better skill tests, including negative-trigger cases

### Primary files

- [src/mapify_cli/templates/skills/README.md](../src/mapify_cli/templates/skills/README.md)
- [src/mapify_cli/templates/skills/skill-rules.json](../src/mapify_cli/templates/skills/skill-rules.json)
- [src/mapify_cli/templates/skills/map-planning/SKILL.md](../src/mapify_cli/templates/skills/map-planning/SKILL.md)
- [src/mapify_cli/templates/skills/map-learn/SKILL.md](../src/mapify_cli/templates/skills/map-learn/SKILL.md)
- [src/mapify_cli/templates/commands/map-learn.md](../src/mapify_cli/templates/commands/map-learn.md)
- [tests/test_skills.py](../tests/test_skills.py)
- [docs/USAGE.md](./USAGE.md)
- [docs/ARCHITECTURE.md](./ARCHITECTURE.md)

### Exit criteria

- У MAP нет непонятного duality между command и skill surface.
- Skills documentation matches runtime reality.
- Skill triggering/invocation regressions are caught by tests, not by users.

## Iteration 5: Orchestrator R&D And Deep Optimization

**Почему это last:** advanced orchestration only pays off after the product model is already stable.

**Improvement-plan items:** `2604.019`, `2604.020`, `2604.021`, `2604.022`, `2604.023`, `2604.024`, `2604.014`, `2604.017`

### Scope

- `REGISTRY/FOCUS`
- steering requests and preemption
- deterministic token budgets
- agent registry snapshots
- multi-phase evaluation harness
- family-specific model scaling analysis
- deeper resiliency/health reporting

### Main deliverables

- Feature-flagged orchestrator experiments
- Better metrics and health reports
- Controlled A/B evaluation instead of intuition-based tuning

### Primary files

- [src/mapify_cli/templates/map/scripts/map_orchestrator.py](../src/mapify_cli/templates/map/scripts/map_orchestrator.py)
- [src/mapify_cli/templates/map/scripts/map_step_runner.py](../src/mapify_cli/templates/map/scripts/map_step_runner.py)
- [src/mapify_cli/templates/hooks/workflow-context-injector.py](../src/mapify_cli/templates/hooks/workflow-context-injector.py)
- [src/mapify_cli/workflow_state.py](../src/mapify_cli/workflow_state.py)
- [src/mapify_cli/schemas.py](../src/mapify_cli/schemas.py)
- [src/mapify_cli/verification_recorder.py](../src/mapify_cli/verification_recorder.py)
- [tests/test_map_orchestrator.py](../tests/test_map_orchestrator.py)
- [tests/test_map_step_runner.py](../tests/test_map_step_runner.py)
- [tests/test_workflow_state.py](../tests/test_workflow_state.py)
- [tests/test_verification_recorder.py](../tests/test_verification_recorder.py)

### Exit criteria

- Advanced context/orchestration ideas are measured, not just described.
- MAP can prove which orchestration mechanisms actually improve approval rate, latency, and context discipline.

## What Not To Do First

- Не начинать с `REGISTRY/FOCUS`, пока artifact pipeline и workflow-fit ещё не выровнены.
- Не начинать с skills cleanup, пока product/runtime still violates the main philosophy.
- Не пытаться “исправить MAP” только через wording changes в prompts.
- Не делать `LEARN` hard-gated.

## Practical Execution Notes

- Если меняются `.claude/commands/`, `.claude/hooks/` или `.claude/skills/`, нужно держать их синхронными с `src/mapify_cli/templates/`.
- Предпочтительный путь синка: `make sync-templates`.
- Для agent template sync already exists a guard: [tests/test_template_sync.py](../tests/test_template_sync.py).
- Для command/skill/runtime changes roadmap implicitly assumes новые тесты рядом с существующими:
  [tests/test_map_orchestrator.py](../tests/test_map_orchestrator.py),
  [tests/test_map_step_runner.py](../tests/test_map_step_runner.py),
  [tests/test_workflow_state.py](../tests/test_workflow_state.py),
  [tests/test_verification_recorder.py](../tests/test_verification_recorder.py),
  [tests/test_skills.py](../tests/test_skills.py).

## Short Version

Если свести roadmap к одному предложению:

**Сначала сделать MAP process-correct и artifact-first, потом modernize commands, потом clean up skills, и только потом инвестировать в advanced orchestration research.**
