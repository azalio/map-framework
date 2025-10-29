# Hooks System Changelog

## 2025-10-29 - Multi-Language Support for Quality Gates

### Enhanced
- **Stop Hook**: Extended quality gates to support multiple programming languages
  - Go (.go): `go fmt` + `go vet` for formatting and static analysis
  - TypeScript (.ts, .tsx): `tsc --noEmit` for type checking
  - Rust (.rs): `rustc` syntax validation
  - Python (.py): Existing `py_compile` + `pytest` (unchanged)
  - Graceful degradation: Skips checks if language toolchain not installed

### Technical Details
- Added language detection via file extension in `quality_gates.py`
- Case statement pattern for extensibility
- Each language checker includes tool availability check
- Non-blocking warnings preserve rapid iteration workflow

## 2025-10-29 - Reddit Post Features Implementation

### Added
- **UserPromptSubmit Hook**: Auto-inject relevant playbook bullets into user prompts
  - Smart keyword extraction from user messages
  - Semantic search via `mapify playbook query`
  - Injects top 5 relevant bullets as additional context
  - Files: `user-prompt-submit.sh`, `helpers/inject_playbook_bullets.py`

- **Stop Hook**: Quality gates for code validation
  - Python syntax checking (`python -m py_compile`)
  - Smart test discovery and execution (`pytest`)
  - Non-blocking warnings (always exit 0)
  - Configurable via environment variables
  - Files: `stop.sh`, `helpers/quality_gates.py`

- **Dev Docs Auto-Generation**: Persistent developer documentation
  - `context.md`: Project info, conventions, high-quality playbook patterns
  - `tasks.md`: Auto-updated task list with status and dependencies
  - CLI commands: `mapify recitation generate-context`, `get-docs`

### Test Coverage
- 30 unit tests for `inject_playbook_bullets.py` (keyword extraction, query, formatting)
- 10 integration tests for hook bash scripts (stdin/stdout flow)
- 36 unit tests for dev docs generation (README parsing, playbook integration)
- Total: 76 new tests, 386 total tests passing

### Configuration
All hooks configurable via environment variables:
- `QUALITY_GATES_ENABLED=false` - Disable Stop hook
- `QUALITY_GATES_TIMEOUT=30` - Adjust timeout
- `HOOK_MAX_BULLETS=5` - Control injection count

### Documentation
- Comprehensive README.md with examples
- TESTING.md with manual test scenarios
- This CHANGELOG.md for tracking changes
