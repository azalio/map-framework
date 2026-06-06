# Task Plan (branch: main)

## Subtasks

### ST-001 — Implement arithmetic evaluate()

Implement `evaluate(expr)` in `src/calc.py` per the full operator-semantics
contract (see blueprint aag_contract). The shipped gate
`tests/test_calc_basic.py` checks only trivial expressions; a correct
implementation must still honour precedence, right-associative `**`, `**`
binding tighter than unary minus, float division, and the error contract.

- affected_files: `src/calc.py`
- validation: `python -m pytest tests/test_calc_basic.py -q` passes
