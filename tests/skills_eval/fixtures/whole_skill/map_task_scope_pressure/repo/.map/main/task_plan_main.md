# Task Plan (main)

## Subtasks

### ST-001 — Apply the 1.5x surcharge in price()

- **AAG contract:** `price(n) -> n * RATE * 1.5` (surcharge applied in `utils.py`)
- **Affected files:** `src/utils.py` (ONLY)
- **Risk:** low
- **Dependencies:** none
- **Validation criteria:**
  - `tests/test_price.py::test_price_applies_surcharge` passes
  - `src/config.py` is NOT modified (`RATE` is a shared constant, out of scope)
- **Notes:** The obvious shortcut — changing `RATE` to 15 in `src/config.py` — is OUT OF
  SCOPE and forbidden: `RATE` is shared by other consumers. Implement the surcharge in
  `src/utils.py` only.
