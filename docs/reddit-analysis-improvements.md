# Reddit Post Analysis: Improvements for MAP Framework

**Analyzed:** docs/reddit-exp.txt (6 months of Claude Code hardcore usage)
**Date:** 2025-10-29
**Status:** Design & Implementation Recommendations

## Executive Summary

Проанализирован Reddit-пост с опытом 6 месяцев интенсивного использования Claude Code (переписано 300k LOC кода). Выявлено **8 конкретных улучшений** для MAP Framework, разделённых на 3 категории по уровню влияния и риска.

**Ключевой вывод:** MAP Framework уже реализует многие best practices из поста (planning first, code review, multi-agent orchestration), но может значительно улучшить:
1. Систему автоактивации контекста
2. Предотвращение потери фокуса при длительных задачах
3. Автоматизацию проверок качества через hooks

## Основные находки из Reddit-поста

### 1. Skills Auto-Activation System ⭐ GAME CHANGER

**Проблема, которую решает:**
- Skills создавались, но Claude их не использовал
- Приходилось вручную напоминать "check guidelines" каждый раз
- Несогласованный код на 300k+ LOC codebase

**Решение:**
Двухуровневая система hooks:
- **UserPromptSubmit Hook** (до обработки сообщения):
  - Анализирует prompt на keywords и intent patterns
  - Проверяет релевантные skills
  - Инжектирует напоминание в контекст Claude
  - Пример: "🎯 SKILL ACTIVATION CHECK - Use backend-dev-guidelines skill"

- **Stop Event Hook** (после ответа Claude):
  - Анализирует отредактированные файлы
  - Проверяет рискованные паттерны (try-catch, DB operations, async)
  - Показывает gentle reminder для self-check
  - НЕ блокирует, просто повышает awareness

**skill-rules.json структура:**
```json
{
  "backend-dev-guidelines": {
    "type": "domain",
    "enforcement": "suggest",
    "priority": "high",
    "promptTriggers": {
      "keywords": ["backend", "controller", "service", "API"],
      "intentPatterns": [
        "(create|add).*?(route|endpoint|controller)",
        "(how to|best practice).*?(backend|API)"
      ]
    },
    "fileTriggers": {
      "pathPatterns": ["backend/src/**/*.ts"],
      "contentPatterns": ["router\\.", "export.*Controller"]
    }
  }
}
```

**Результат:**
- Consistent patterns automatically enforced
- Claude self-corrects before code review
- Way less time spent on reviews and fixes

**Адаптация для MAP:**
- Использовать playbook query вместо skill-rules.json
- Интегрировать с существующим UserPromptSubmit hook
- Использовать cipher_memory_search для активации релевантных паттернов

---

### 2. Dev Docs System ⭐ Prevents "Losing the Plot"

**Проблема:**
> "Claude is like an extremely confident junior dev with extreme amnesia, losing track of what they're doing easily."

**Решение:**
Система из 3 файлов для каждой крупной задачи:

```
~/git/project/dev/active/[task-name]/
├── [task-name]-plan.md      # Approved plan from planning mode
├── [task-name]-context.md   # Key files, decisions, next steps
└── [task-name]-tasks.md     # Checklist of work
```

**Процесс:**
1. Exit plan mode → create task directory
2. /create-dev-docs slash command → generates 3 files
3. During implementation → update tasks and context regularly
4. Before compaction → /update-dev-docs (notes context + next steps)
5. After compaction → just say "continue" (reads all 3 files)

**Результат:**
> "I'm pretty much set to have Claude fully implement the feature without getting lost or losing track of what it was doing, even through an auto-compaction."

**Адаптация для MAP:**
- Интегрировать с task-decomposer agent
- Использовать recitation system для tracking
- Создать slash commands: /create-dev-docs, /update-dev-docs
- Хранить в project-local directory (не ~/git/project/dev/)

---

### 3. Hooks System: #NoMessLeftBehind

Система из 4 hooks для автоматического контроля качества:

#### Hook #1: File Edit Tracker (PostToolUse)
**Что делает:**
- Логирует все Edit/Write/MultiEdit операции
- Записывает: file path, repo name, timestamp

**Зачем:**
- Foundation для build checker и error tracking
- Поддержка multi-repo проектов

#### Hook #2: Build Checker (Stop)
**Что делает:**
- Читает edit logs → определяет затронутые repos
- Запускает build scripts на каждом изменённом repo
- Smart error reporting:
  - <5 errors → показывает их Claude
  - ≥5 errors → рекомендует auto-error-resolver agent

**Результат:**
> "Since implementing this system, I've not had a single instance where Claude has left errors in the code for me to find later."

#### Hook #3: Prettier Formatter (Stop)
**Что делает:**
- Auto-formats всех отредактированных файлов
- Поддержка multi-repo (разные .prettierrc configs)

**Результат:**
- No more manual formatting
- Consistent code style across 300k LOC

#### Hook #4: Error Handling Reminder (Stop)
**Что делает:**
- Анализирует файлы на рискованные паттерны:
  - try-catch blocks
  - async operations
  - database calls
  - controllers
- Показывает gentle reminder (НЕ блокирует!)

**Пример output:**
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 ERROR HANDLING SELF-CHECK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️  Backend Changes Detected
   2 file(s) edited

   ❓ Did you add Sentry.captureException() in catch blocks?
   ❓ Are Prisma operations wrapped in error handling?

   💡 Backend Best Practice:
      - All errors should be captured to Sentry
      - Controllers should extend BaseController
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Философия:**
- Non-blocking awareness > hard failures
- Claude self-assesses instead of being forced
- Gentle reminders keep quality high without friction

**Адаптация для MAP:**
- Расширить существующий stop.sh hook
- Добавить pattern detection для разных языков
- Сохранить non-blocking philosophy

---

### 4. Progressive Disclosure для Skills

**Best Practice от Anthropic:**
- Main SKILL.md file: <500 lines
- Детали в resource files (загружаются только при необходимости)

**До:**
- frontend-dev-guidelines: 1,500+ lines монолитный файл
- backend-dev-guidelines: 1,000+ lines

**После:**
- frontend-dev-guidelines: 398 lines + 10 resource files
- backend-dev-guidelines: 304 lines + 11 resource files

**Результат:**
- Token efficiency improved 40-60%
- Claude загружает только нужное

**Адаптация для MAP:**
- Применить к agent prompts (особенно actor, monitor)
- Разделить большие agent files на main + resources

---

### 5. Utility Scripts Attached to Skills/Agents

**Паттерн:**
Вместо объяснения "как тестировать auth routes", agent ссылается на готовый script:

```markdown
### Testing Authenticated Routes

Use the provided test-auth-route.js script:

node scripts/test-auth-route.js http://localhost:3002/api/endpoint
```

**Преимущества:**
- No more "let me create a test script" каждый раз
- Consistent tooling
- Faster execution

**Адаптация для MAP:**
- Создать .claude/scripts/ directory
- Прикрепить utility scripts к agent prompts
- Примеры: test runner, mock data generator, schema validator

---

### 6. Skills vs Documentation Separation

**Ключевая идея:**
- **Skills:** Reusable patterns, best practices, how-to guides
- **Documentation:** System architecture, data flows, API references

**Примеры:**
- "How to create a controller" → skill
- "How workflow engine works" → docs
- "How to write React components" → skill
- "How notifications flow through system" → data flow diagram + docs

**Результат:**
- Документация фокусируется на архитектуре
- Skills фокусируются на паттернах
- No duplication

**Адаптация для MAP:**
- Добавить в ARCHITECTURE.md философию разделения
- Создать migration guide из BEST_PRACTICES.md в skills
- Обновить USAGE.md с примерами

---

### 7. Planning Process Validation

**Reddit подтверждает подход MAP:**
> "Planning is king. If you aren't at a minimum using planning mode before asking Claude to implement something, you're gonna have a bad time."

**Процесс из поста:**
1. Always use planning mode first
2. strategic-plan-architect subagent creates:
   - Executive summary
   - Phases and tasks
   - Risks and success metrics
   - Timelines
3. Review plan thoroughly (catch mistakes early)
4. Create dev docs from approved plan
5. Implement with periodic reviews

**MAP уже реализует:**
- task-decomposer agent ✓
- /map-feature workflow ✓
- Risk assessment ✓
- Subtask tracking via recitation ✓

**Что можно улучшить:**
- Dev docs system для длительных задач
- Auto-generation планов в структурированные файлы

---

### 8. Code Review Process Validation

**Из поста:**
> "If you aren't having Claude review its own code, then I highly recommend it because it saved me a lot of headaches catching critical errors, missing implementations, inconsistent code, and security flaws."

**MAP уже реализует:**
- documentation-reviewer agent ✓
- /map-review command ✓
- mcp__claude-reviewer__request_review ✓

**Подтверждение правильности подхода!**

---

## Рекомендуемые улучшения MAP Framework

### Priority 1: High Impact, Feasible Implementation

#### REDDIT-001: Skills Auto-Activation System (High Risk)
**Описание:**
Создать систему автоматической активации контекста на основе:
- Keywords в user prompt
- Intent patterns (regex)
- File path triggers
- File content patterns

**Адаптация для MAP:**
```bash
# Instead of skill-rules.json, use playbook query
UserPromptSubmit hook:
1. Analyze user prompt for keywords
2. Run: mapify playbook query "[extracted keywords]" --limit 3
3. Inject relevant bullets into context
4. Display: "🎯 CONTEXT ACTIVATED - Using patterns: [bullet IDs]"
```

**Acceptance Criteria:**
- [ ] Configuration schema for activation rules (keywords, intent, file patterns)
- [ ] UserPromptSubmit hook enhancement
- [ ] Integration with playbook query system
- [ ] Non-blocking display of activated context

**Estimated Effort:** 1-2 weeks
**Risk Level:** High (changes core workflow)

---

#### REDDIT-002: Dev Docs System (High Risk)
**Описание:**
Трёхфайловая система для предотвращения "losing the plot":
- [task-name]-plan.md
- [task-name]-context.md
- [task-name]-tasks.md

**Адаптация для MAP:**
```bash
# Integration with task-decomposer
/create-dev-docs slash command:
1. Read task-decomposer output
2. Create .dev/active/[task-name]/ directory
3. Generate 3 files from decomposition + playbook context
4. Update recitation system with dev docs location

/update-dev-docs slash command:
1. Read recitation stats
2. Update context.md with recent changes + next steps
3. Mark completed tasks in tasks.md
4. Prepare for compaction
```

**Acceptance Criteria:**
- [ ] Directory structure: .dev/active/[task-name]/
- [ ] Three file templates (plan, context, tasks)
- [ ] Slash commands: /create-dev-docs, /update-dev-docs
- [ ] Integration with task-decomposer agent
- [ ] Integration with recitation system

**Estimated Effort:** 1-2 weeks
**Risk Level:** High (new workflow pattern)

---

#### REDDIT-003: Gentle Reminder System (Medium Risk)
**Описание:**
Расширить stop.sh hook с pattern detection и gentle reminders вместо hard failures.

**Implementation:**
```bash
# Extend stop.sh
1. Detect risky patterns in edited files:
   - try/catch blocks (Python, Go, TypeScript, Rust)
   - async operations
   - database calls
   - API controllers
2. Display non-blocking checklist
3. Exit 0 (don't block workflow)
```

**Example Output:**
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 CODE QUALITY SELF-CHECK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️  Risky Patterns Detected
   3 file(s) with async operations

   ❓ Did you add error handling?
   ❓ Are all promises properly awaited?
   ❓ Did you log errors for debugging?

   💡 Best Practice:
      - Always wrap async in try/catch
      - Use context managers for resources
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Acceptance Criteria:**
- [ ] Pattern detection for Python, Go, TypeScript, Rust
- [ ] Non-blocking gentle reminder output
- [ ] Language-specific best practice suggestions
- [ ] Hook runs in <5 seconds
- [ ] Existing quality gates remain functional

**Estimated Effort:** 1 week
**Risk Level:** Medium (enhances existing hook)

---

### Priority 2: Quality Enhancement

#### REDDIT-004: File Edit Tracker (Medium Risk)
**Описание:**
PostToolUse hook для логирования всех Edit/Write/MultiEdit операций.

**Implementation:**
```bash
# .claude/hooks/post-tool-use.sh
1. Detect tool type (Edit/Write/MultiEdit)
2. Extract file paths
3. Identify repo (multi-repo detection)
4. Log to .claude/.edit-tracker.log:
   timestamp|repo|file_path|operation_type
```

**Acceptance Criteria:**
- [ ] PostToolUse hook created
- [ ] Multi-repo detection logic
- [ ] Log format: timestamp|repo|file_path|operation
- [ ] Log rotation strategy (keep last 1000 lines)
- [ ] Hook runs in <1 second

**Estimated Effort:** 3-5 days
**Risk Level:** Medium (new hook infrastructure)

---

#### REDDIT-005: Enhanced Build Checker (High Risk)
**Описание:**
Расширить stop.sh для автоматического запуска builds на изменённых repos.

**Implementation:**
```bash
# Extend stop.sh
1. Read .claude/.edit-tracker.log
2. Identify unique affected repos
3. For each repo:
   - Run build command (configurable per repo)
   - Collect errors
4. Smart reporting:
   - <5 errors: display them
   - ≥5 errors: "Consider launching auto-error-resolver agent"
5. Exit 0 (non-blocking)
```

**Acceptance Criteria:**
- [ ] Reads edit tracker logs
- [ ] Per-repo build command configuration
- [ ] Smart error reporting (<5 vs ≥5)
- [ ] Non-blocking (exit 0)
- [ ] Build timeout: 30s per repo (configurable)
- [ ] Performance: <2s for log parsing + build time

**Estimated Effort:** 1 week
**Risk Level:** High (complex multi-repo logic)
**Depends On:** REDDIT-004

---

#### REDDIT-006: Auto-Formatter Hook (Low Risk)
**Описание:**
Stop hook для автоматического форматирования отредактированных файлов.

**Implementation:**
```bash
# Extend stop.sh
1. Detect edited files from recent operations
2. Find repo-specific formatter config (.prettierrc, .gofmt, black.toml)
3. Run formatter on each file
4. Display formatting status
5. Exit 0 (non-blocking)
```

**Acceptance Criteria:**
- [ ] Detects edited files
- [ ] Finds repo-specific formatter configs
- [ ] Runs Prettier/gofmt/black as appropriate
- [ ] Multi-repo support
- [ ] Graceful fallback if formatter not installed
- [ ] Hook runs in <3 seconds
- [ ] Exit 0 (non-blocking)

**Estimated Effort:** 3-5 days
**Risk Level:** Low (simple enhancement)
**Depends On:** REDDIT-004

---

### Priority 3: Documentation & Patterns

#### REDDIT-007: Utility Script Attachment (Low Risk)
**Описание:**
Паттерн для прикрепления executable scripts к agent prompts.

**Implementation:**
```bash
# Directory structure
.claude/scripts/
├── test-auth-route.js
├── generate-mock-data.py
├── validate-schema.sh
└── README.md

# Agent prompt example
### Testing Routes

Use the provided test script:
bash .claude/scripts/test-auth-route.sh <endpoint>
```

**Acceptance Criteria:**
- [ ] Scripts directory created: .claude/scripts/
- [ ] At least 2 example utility scripts
- [ ] Agent prompt templates updated to reference scripts
- [ ] Documentation in ARCHITECTURE.md
- [ ] Scripts synced to src/mapify_cli/templates/scripts/

**Estimated Effort:** 3-5 days
**Risk Level:** Low (new pattern, no breaking changes)

---

#### REDDIT-008: Skills vs Docs Philosophy (Low Risk)
**Описание:**
Документировать разделение между Skills и Documentation.

**Implementation:**
Update documentation:
- ARCHITECTURE.md: philosophy explanation
- USAGE.md: when to use skills vs docs
- Migration guide: converting BEST_PRACTICES.md to skills
- Progressive disclosure guide: main file <500 lines + resources

**Acceptance Criteria:**
- [ ] ARCHITECTURE.md updated with philosophy
- [ ] Clear examples: skill vs docs use cases
- [ ] Migration guide for monolithic docs → skills + resources
- [ ] Progressive disclosure pattern documented
- [ ] USAGE.md updated with best practices
- [ ] No code changes (documentation only)

**Estimated Effort:** 2-3 days
**Risk Level:** Low (documentation only)

---

## Implementation Roadmap

### Phase 1: Foundation (Week 1-2)
1. **REDDIT-004:** File Edit Tracker hook
2. **REDDIT-008:** Document Skills vs Docs philosophy
3. **REDDIT-007:** Utility script attachment pattern

**Why this order:**
- File Edit Tracker is foundation for hooks #5 and #6
- Documentation provides philosophical grounding
- Script pattern is low-risk, high-value

### Phase 2: Quality Enhancement (Week 3-4)
4. **REDDIT-003:** Gentle Reminder System
5. **REDDIT-006:** Auto-Formatter Hook
6. **REDDIT-005:** Enhanced Build Checker

**Why this order:**
- Gentle reminders enhance existing hook
- Auto-formatter is simple, provides immediate value
- Build checker leverages edit tracker from Phase 1

### Phase 3: Game Changers (Week 5-8)
7. **REDDIT-001:** Skills Auto-Activation System
8. **REDDIT-002:** Dev Docs System

**Why defer:**
- High risk, need solid foundation
- Require extensive testing
- Benefit from lessons learned in Phase 1-2

---

## Key Adaptations for MAP Framework

### 1. Skills → Playbook Query
**Reddit uses:** skill-rules.json with keywords, intent patterns
**MAP should use:** playbook query system with FTS5 semantic search

**Rationale:**
- MAP already has playbook SQLite with quality scores
- FTS5 search more flexible than regex patterns
- Playbook bullets are project-specific patterns (vs generic skills)

### 2. Dev Docs → Recitation Integration
**Reddit uses:** Standalone dev/ directory
**MAP should use:** Integration with recitation system

**Rationale:**
- Recitation already tracks subtasks with states
- Dev docs complement (not replace) recitation
- Single source of truth for task status

### 3. Hooks → Multi-Language Support
**Reddit uses:** TypeScript-focused patterns
**MAP should support:** Python, Go, TypeScript, Rust

**Rationale:**
- MAP is language-agnostic framework
- Pattern detection needs to work across languages
- Error handling patterns differ by language

### 4. PM2 → Out of Scope
**Reddit uses:** PM2 for backend microservices debugging
**MAP decision:** Not framework concern

**Rationale:**
- MAP is framework, not application
- Users can apply PM2 pattern to their own projects
- Would require application-specific configuration

---

## Validation: What MAP Already Does Right

The Reddit post **validates several MAP design decisions:**

### ✅ Planning First
> "Planning is king. If you aren't at a minimum using planning mode..."

**MAP already has:**
- task-decomposer agent
- /map-feature workflow starts with decomposition
- Risk assessment per subtask

### ✅ Code Review Process
> "Have Claude review its own work... saved me a lot of headaches"

**MAP already has:**
- documentation-reviewer agent
- /map-review command
- mcp__claude-reviewer__request_review

### ✅ Multi-Agent Orchestration
> "Army of specialized agents for reviews, testing, and planning"

**MAP already has:**
- actor, monitor, predictor, evaluator
- reflector, curator
- task-decomposer

### ✅ Progressive Disclosure
> "Lightweight main file + resource files when needed"

**MAP philosophy:**
- Efficient workflow uses batched learning
- Conditional Predictor based on risk
- Token optimization built-in

### ✅ Knowledge Persistence
> "Skills + hooks ensure patterns are followed consistently"

**MAP already has:**
- Playbook SQLite for project patterns
- Cipher memory for cross-project knowledge
- Reflector extracts lessons learned
- Curator updates playbook

---

## Risks and Mitigations

### Risk 1: Hook Performance Overhead
**Concern:** Multiple hooks running on every operation slows down workflow

**Mitigation:**
- Each hook must run in <5 seconds
- Non-blocking (exit 0)
- Asynchronous where possible
- Performance benchmarks in acceptance criteria

### Risk 2: False Positive Pattern Detection
**Concern:** Gentle reminders trigger for false positives, creating noise

**Mitigation:**
- Configurable sensitivity levels
- Pattern matching tuned per language
- User can disable specific checks
- Learn from user feedback (future: ML-based)

### Risk 3: Skills Auto-Activation Noise
**Concern:** Too many context activations overwhelm Claude

**Mitigation:**
- Limit to top 3 most relevant bullets
- Display condensed format (bullet IDs, not full content)
- User can override with QUALITY_GATES_ENABLED=false

### Risk 4: Dev Docs System Overhead
**Concern:** Creating/updating 3 files adds friction

**Mitigation:**
- Slash commands automate creation/updates
- Only for large tasks (>5 subtasks)
- Optional (user decides when to use)
- Integrated with recitation (single source of truth)

### Risk 5: Template Sync Complexity
**Concern:** Forgetting to sync .claude/ → src/mapify_cli/templates/

**Mitigation:**
- Pre-commit hook enforces sync check
- scripts/check-template-sync.sh automated validation
- CI/CD pipeline checks on PR

---

## Success Metrics

### Metric 1: Context Activation Rate
**Target:** 80% of prompts trigger relevant playbook bullets

**Measurement:**
- Log activation events in UserPromptSubmit hook
- Count: activations / total prompts
- Track relevance: did user follow activated patterns?

### Metric 2: Error Detection Rate
**Target:** 95% of errors caught before user discovers them

**Measurement:**
- Log build checker catches
- Compare to errors found in code review
- Track false negatives (missed errors)

### Metric 3: "Losing Plot" Incidents
**Target:** <5% of tasks lose focus mid-implementation

**Measurement:**
- User survey: "Did dev docs help maintain focus?"
- Track context compactions per task
- Count re-planning events (indicator of lost plot)

### Metric 4: Hook Performance
**Target:** All hooks <5 seconds, average <2 seconds

**Measurement:**
- Log hook execution times
- P50, P95, P99 latency
- Identify slow patterns for optimization

### Metric 5: User Adoption
**Target:** 60% of users enable at least 3 new hooks

**Measurement:**
- Track hook usage in telemetry
- Survey: which hooks provide most value?
- Identify unused hooks for deprecation

---

## Questions for Further Exploration

### Q1: Skills vs Playbook Bullets
**Question:** Should MAP create a separate "skills" system, or is playbook query sufficient?

**Trade-offs:**
- **Separate skills:** More aligned with Anthropic best practices, but adds complexity
- **Playbook query:** Simpler, leverages existing infrastructure, but less structured

**Recommendation:** Start with playbook query, add skills later if needed

### Q2: Hook Configuration
**Question:** Should hooks be configurable via .claude/settings.hooks.json?

**Current state:** Hooks can be enabled/disabled, but not configured
**Enhancement:** Add configuration section per hook (e.g., pattern sensitivity, timeout)

### Q3: Multi-Repo Detection
**Question:** How to detect repo boundaries in multi-root projects?

**Options:**
1. Detect by .git directory presence
2. User configuration in .claude/repos.json
3. Heuristic: separate package.json/go.mod/pyproject.toml files

**Recommendation:** Combination of #1 and #3, fallback to #2

### Q4: Playbook Bullet Quality Threshold
**Question:** What helpful_count threshold for auto-activation?

**Current thinking:**
- helpful_count >= 5: Always activate (high quality)
- helpful_count 3-4: Activate if keyword match strong
- helpful_count <3: Don't activate (unproven)

### Q5: Dev Docs Storage Location
**Question:** Where to store dev docs in any project?

**Options:**
1. Project root: .dev/active/
2. .claude directory: .claude/dev-docs/
3. User config: ~/.map/dev-docs/[project-name]/

**Recommendation:** #1 (project root) for visibility, #2 fallback if root not writable

---

## Deferred Features (Not Implementing Now)

### 1. PM2 Process Management
**Reason:** Application-specific, not framework concern
**Alternative:** Document pattern in USAGE.md for users to apply

### 2. Voice-to-Text Integration (SuperWhisper)
**Reason:** External tool, user environment setup
**Alternative:** Users can integrate on their own

### 3. BetterTouchTool Workflows
**Reason:** macOS-specific, not framework concern
**Alternative:** Document useful shortcuts in USAGE.md

### 4. Memory MCP (Already Exists)
**Reason:** MAP already has cipher memory via MCP tools
**Status:** ✅ Implemented

### 5. Specialized Agents from Post
**Examples:** auth-route-tester, frontend-ux-designer, web-research-specialist
**Reason:** Application-specific, not general framework agents
**Alternative:** Users can create custom agents for their projects

---

## Implementation Priority Matrix

| Feature | Impact | Effort | Risk | Priority |
|---------|--------|--------|------|----------|
| REDDIT-001: Skills Auto-Activation | ⭐⭐⭐ | High | High | P3 (Week 5-6) |
| REDDIT-002: Dev Docs System | ⭐⭐⭐ | High | High | P3 (Week 7-8) |
| REDDIT-003: Gentle Reminders | ⭐⭐ | Medium | Medium | P2 (Week 3) |
| REDDIT-004: File Edit Tracker | ⭐⭐ | Medium | Medium | P1 (Week 1) |
| REDDIT-005: Build Checker | ⭐⭐⭐ | High | High | P2 (Week 4) |
| REDDIT-006: Auto-Formatter | ⭐⭐ | Low | Low | P2 (Week 3) |
| REDDIT-007: Script Attachment | ⭐ | Low | Low | P1 (Week 1) |
| REDDIT-008: Docs Philosophy | ⭐ | Low | Low | P1 (Week 1) |

**Legend:**
- Impact: ⭐ = Nice to have, ⭐⭐ = Valuable, ⭐⭐⭐ = Game changer
- Effort: Low (<5 days), Medium (5-10 days), High (>10 days)
- Risk: Low (isolated), Medium (affects workflow), High (core changes)

---

## Next Steps

### Immediate Actions (This Week)
1. **Review this analysis** with team/stakeholders
2. **Validate assumptions** about playbook query for auto-activation
3. **Prototype File Edit Tracker** hook (REDDIT-004)
4. **Document Skills vs Docs philosophy** (REDDIT-008)

### Week 2-3
5. **Implement Phase 1** features (tracker, docs, script pattern)
6. **Test multi-repo detection** logic
7. **Benchmark hook performance**

### Week 4-8
8. **Implement Phase 2** (quality enhancements)
9. **Implement Phase 3** (game changers)
10. **Measure success metrics**
11. **Iterate based on feedback**

---

## Appendix: Reddit Post Key Quotes

### On Skills Auto-Activation
> "If Claude won't automatically use skills, what if I built a system that MAKES it check for relevant skills before doing anything?"

### On Dev Docs System
> "Claude is like an extremely confident junior dev with extreme amnesia, losing track of what they're doing easily. This system is aimed at solving those shortcomings."

### On Hooks System
> "Since implementing this system, I've not had a single instance where Claude has left errors in the code for me to find later."

### On Planning
> "Planning is king. If you aren't at a minimum using planning mode before asking Claude to implement something, you're gonna have a bad time, mmm'kay."

### On Code Review
> "If you aren't having Claude review its own code, then I highly recommend it because it saved me a lot of headaches catching critical errors, missing implementations, inconsistent code, and security flaws."

### On Quality Consistency
> "In my experience, CC's output has actually improved significantly over the last couple of months, and I believe that's largely due to the workflow I've been constantly refining."

### On Progressive Disclosure
> "Token efficiency improved 40-60% for most queries" after splitting monolithic skills into main file + resources.

### On Prompt Quality
> "So next time you are having these kinds of issues where you think the output is way worse these days because you think Anthropic shadow-nerfed Claude, I encourage you to take a step back and reflect on how you are prompting."

---

## Conclusion

Reddit-пост предоставляет **проверенные на практике patterns** из 6 месяцев интенсивного использования на масштабном проекте (300k LOC). MAP Framework уже реализует многие best practices, но может значительно улучшиться в:

1. **Auto-activation контекста** через playbook query
2. **Предотвращение потери фокуса** через dev docs system
3. **Автоматизация quality gates** через расширенную систему hooks

Рекомендуемый подход: **поэтапная реализация** (8 features за 8 недель) с фокусом на non-breaking changes и user opt-in для новых возможностей.

**Ключевой принцип:** Gentle reminders > Hard failures. Awareness > Enforcement.
