# FTS5 Query Error Root Cause Analysis

## Executive Summary

Playbook queries with hyphenated terms (e.g., "session-start", "auto-activation", "multi-subtask") cause FTS5 SQL errors: `"no such column: <word>"`.

**Root Cause**: The `_build_fts_query` method removes hyphens and creates unquoted multi-word FTS5 queries. When FTS5 cannot find a term in the index, it interprets it as a column name, causing the error.

**Location**: `src/mapify_cli/playbook_manager.py`, lines 995-1062 (method `_build_fts_query`)

---

## Error Examples

### Example 1: "auto-activation"
```bash
$ mapify playbook query "hooks system error handling workflow skills auto-activation" --limit 10 --mode local
```
**Error**: `no such column: activation`

### Example 2: "session-start"
```bash
$ mapify playbook query "hooks session-start auto-injection file validation" --limit 5 --mode local
```
**Error**: `no such column: start`

### Example 3: "multi-subtask"
```bash
$ mapify playbook query "multi-subtask dependency verification upstream artifacts" --limit 5
```
**Error**: `no such column: subtask`

---

## Root Cause Deep Dive

### Current Code Flow (playbook_manager.py)

```python
# Line 1008: Start with original query
fts_query = params.query  # e.g., "session-start auto-injection"

# Line 1011-1013: Remove FTS5 special characters (INCLUDING HYPHENS)
fts_special_chars = '@#()"\':'
for char in fts_special_chars:
    fts_query = fts_query.replace(char, ' ')
# Result: "session start auto injection"

# Line 1016-1020: Add prefix matching (* suffix)
if params.fts_prefix:
    words = fts_query.split()  # ["session", "start", "auto", "injection"]
    fts_query = ' '.join([f"{word}*" for word in words if len(word) >= 2])
# Result: "session* start* auto* injection*"

# Line 1033: Execute FTS5 query
sql = "WHERE fts.bullets_fts MATCH ?"
sql_params = [fts_query]  # ["session* start* auto* injection*"]
```

### The Problem: FTS5 Interpretation

FTS5 interprets **unquoted multi-word queries** as implicit boolean AND:

```sql
-- Current query (unquoted multi-word)
MATCH 'session* start* auto* injection*'

-- FTS5 interprets as:
MATCH session* AND start* AND auto* AND injection*

-- If "start" not found in FTS5 index:
-- FTS5 assumes "start" is a COLUMN NAME → "no such column: start"
```

**Why this happens:**
- FTS5 searches for terms in indexed columns (content, code_example)
- If a term is not found, FTS5 falls back to interpreting it as a column specifier
- This is FTS5's design for column-scoped queries like `content:session*`
- Unquoted missing terms trigger this fallback behavior

---

## FTS5 Query Format Requirements

FTS5 supports multiple query formats. Current code generates **invalid format #4**.

### Valid Formats

#### 1. Phrase Query (Exact Match)
```sql
MATCH '"session start"'
```
- Finds **exact phrase** "session start" (words adjacent, in order)
- Does NOT support prefix matching with phrases
- Use case: Finding exact multi-word terms

#### 2. Quoted Terms with Prefix (RECOMMENDED FIX)
```sql
MATCH '"session"* "start"* "auto"* "injection"*'
```
- Finds documents containing ALL terms (boolean AND)
- Each term is prefix-matched independently
- Quoted terms prevent "no such column" errors
- **This is the recommended fix**

#### 3. Explicit AND Operator
```sql
MATCH 'session* AND start* AND auto* AND injection*'
```
- Explicit boolean AND between terms
- Works correctly with missing terms (returns 0 results instead of error)
- More verbose but explicit

#### 4. Unquoted Multi-Word (CURRENT BUG)
```sql
MATCH 'session* start* auto* injection*'
```
- Interpreted as implicit AND
- **Fails with "no such column" if term not in index**
- This is what current code generates

---

## Key Line Identification

### Critical Lines in `_build_fts_query` (playbook_manager.py)

| Line | Code | Issue |
|------|------|-------|
| **1008** | `fts_query = params.query` | Initial query assignment |
| **1011** | `fts_special_chars = '@#()"\':'` | Special chars list (note: hyphens NOT in list) |
| **1013** | `fts_query = fts_query.replace(char, ' ')` | **HYPHEN SANITIZATION** - Converts "session-start" → "session start" |
| **1019** | `words = fts_query.split()` | **WORD SPLITTING** - Splits into individual words |
| **1020** | `fts_query = ' '.join([f"{word}*" for word in words if len(word) >= 2])` | **PREFIX ADDITION** - Adds asterisk to each word |
| **1033** | `WHERE fts.bullets_fts MATCH ?` | **FTS5 QUERY EXECUTION** - Executes the malformed query |

### Issue Details

**Line 1013 Problem:**
```python
# Current code (line 1013)
fts_query = fts_query.replace(char, ' ')

# Example transformation
"session-start" → "session start"  # Hyphen removed, space added
```

**Why hyphens are removed:**
- Hyphens are NOT in `fts_special_chars` list (line 1011)
- BUT: The code iterates over `fts_special_chars` which includes various characters
- **Wait, this needs verification** - let me check the actual special chars list

Actually, looking at line 1011:
```python
fts_special_chars = '@#()"\':'
```

**Hyphens are NOT in this list!** So why are they being removed?

Let me check if there's additional sanitization... Looking at line 1013:
```python
for char in fts_special_chars:
    fts_query = fts_query.replace(char, ' ')
```

This only removes `@`, `#`, `(`, `)`, `"`, `'`, `:`. **Hyphens should remain!**

**Updated Root Cause:** The issue is NOT hyphen removal (hyphens are preserved), but rather:
1. Hyphenated words like "session-start" are kept as-is
2. FTS5 tokenizer (`porter unicode61`) treats hyphens as word separators
3. So FTS5 indexes "session-start" as TWO tokens: "session" and "start"
4. When query contains "session-start*", FTS5 searches for token "session-start*"
5. Since the index has "session" and "start" separately, "session-start" is not found
6. FTS5 interprets "session-start" as a column name → error

**Corrected Root Cause:**
- Input: `"session-start auto-injection"`
- No sanitization (hyphens preserved): `"session-start auto-injection"`
- Prefix matching applied: `"session-start* auto-injection*"` (line 1020)
- FTS5 tokenizes during search: treats "session-start*" as single token
- Index has "session" and "start" as separate tokens (tokenizer split during indexing)
- FTS5 can't find "session-start" token → interprets as column name → error

**The real issue:** Mismatch between:
- **Indexing time**: FTS5 tokenizer splits "session-start" into "session" + "start"
- **Query time**: Query contains "session-start*" as single token
- **Result**: Token not found → FTS5 assumes it's a column name

---

## FTS5 Tokenization Behavior

### FTS5 Porter Unicode61 Tokenizer

The playbook uses this tokenizer (line 191 of playbook_manager.py):
```python
tokenize='porter unicode61'
```

**Tokenizer Behavior:**
- Splits on whitespace, punctuation, and special characters
- **Hyphens are treated as token separators** (like spaces)
- "session-start" → indexed as TWO tokens: ["session", "start"]
- "auto-activation" → indexed as TWO tokens: ["auto", "activation"]

### Example Tokenization

| Input Text | Tokens in FTS5 Index |
|------------|---------------------|
| "session-start hook" | `["session", "start", "hook"]` |
| "auto-activation workflow" | `["auto", "activation", "workflow"]` |
| "multi-subtask dependency" | `["multi", "subtask", "dependency"]` |

### Query vs. Index Mismatch

```
Index:     ["session", "start", "hook"]
Query:     "session-start* hook*"
           └─────┬──────┘
                 │
           Single token expected, but index has TWO tokens
           FTS5 can't find "session-start" → error
```

---

## Verification Test Cases

See `tests/test_fts5_error_investigation.py` for reproducible test cases:

1. **test_error_pattern_1_auto_activation**: Reproduces "no such column: activation"
2. **test_error_pattern_2_session_start**: Reproduces "no such column: start"
3. **test_error_pattern_3_multi_subtask**: Reproduces "no such column: subtask"
4. **test_fts5_query_format_requirements**: Documents correct FTS5 query formats
5. **test_build_fts_query_sanitization**: Tests current sanitization logic

---

## Recommended Fix Strategy

### Option A: Split Hyphenated Words at Query Time (RECOMMENDED)

**Approach**: Pre-process query to split hyphenated words before passing to FTS5

```python
# Line 1008-1015: Add hyphen splitting before sanitization
fts_query = params.query

# Split hyphenated words into separate words
fts_query = fts_query.replace('-', ' ')  # "session-start" → "session start"

# Then continue with existing sanitization...
fts_special_chars = '@#()"\':'
for char in fts_special_chars:
    fts_query = fts_query.replace(char, ' ')
```

**Result:**
- Input: `"session-start auto-activation"`
- After split: `"session start auto activation"`
- After prefix: `"session* start* auto* activation*"`
- FTS5 matches: Finds "session" AND "start" AND "auto" AND "activation" (all exist as separate tokens)

**Pros:**
- Simple one-line fix
- Aligns query tokenization with index tokenization
- No changes to FTS5 schema or query syntax
- Preserves existing prefix matching behavior

**Cons:**
- Loses exact phrase matching for hyphenated terms
- "session-start" becomes "session" AND "start" (may match unrelated documents)

### Option B: Quote Each Term (Explicit Tokens)

**Approach**: Quote each word individually to prevent column interpretation

```python
# Line 1016-1020: Modify prefix matching to quote each term
if params.fts_prefix:
    words = fts_query.split()
    # Split hyphenated words
    expanded_words = []
    for word in words:
        expanded_words.extend(word.split('-'))
    # Quote each word and add prefix
    fts_query = ' '.join([f'"{word}"*' for word in expanded_words if len(word) >= 2])
```

**Result:**
- Input: `"session-start auto-activation"`
- After split + quote: `'"session"* "start"* "auto"* "activation"*'`
- FTS5 interprets: Explicit AND between quoted terms
- No "no such column" errors (quoted terms never interpreted as columns)

**Pros:**
- Robust against missing terms (returns 0 results instead of error)
- Explicit token boundaries (FTS5 knows these are search terms, not columns)
- Maintains prefix matching

**Cons:**
- More complex query syntax
- May affect FTS5 ranking (quoted vs unquoted terms ranked differently)

### Option C: Explicit AND Operators

**Approach**: Add explicit AND operators between terms

```python
# Line 1016-1020: Add explicit AND operators
if params.fts_prefix:
    words = fts_query.split()
    # Split hyphenated words and add AND
    expanded_words = []
    for word in words:
        expanded_words.extend(word.split('-'))
    fts_query = ' AND '.join([f'"{word}"*' for word in expanded_words if len(word) >= 2])
```

**Result:**
- Input: `"session-start auto-activation"`
- After split + AND: `'"session"* AND "start"* AND "auto"* AND "activation"*'`
- FTS5 interprets: Explicit boolean AND (very clear semantics)

**Pros:**
- Most explicit and readable query format
- Guaranteed no column interpretation errors
- Clear boolean semantics

**Cons:**
- Longest query strings (more verbose)
- Minor performance impact (explicit operator evaluation)

---

## Recommendation

**Use Option A** (Split hyphens at query time) for immediate fix:

```python
# Minimal change to line 1008-1010
def _build_fts_query(self, params: PlaybookQuery, limit: int) -> Tuple[str, List]:
    import string
    fts_query = params.query

    # FIX: Split hyphenated words to match FTS5 tokenization
    fts_query = fts_query.replace('-', ' ')  # NEW LINE

    # Remove FTS5 special characters: @ # ( ) " ' :
    fts_special_chars = '@#()"\':'
    for char in fts_special_chars:
        fts_query = fts_query.replace(char, ' ')
    # ... rest of method unchanged
```

**Why Option A:**
1. **Minimal code change** (one line)
2. **Aligns with FTS5 tokenization** (fixes mismatch at root)
3. **No breaking changes** to existing query behavior
4. **Simple to test** and verify
5. **Low risk** (no schema or syntax changes)

**Future enhancement**: Consider Option B or C if users need exact phrase matching for hyphenated terms (e.g., treating "session-start" as atomic phrase).

---

## Testing Plan

### Test Cases to Add

1. **Hyphenated query terms**: Verify no "no such column" errors
   ```python
   query("session-start auto-injection")  # Should succeed
   query("multi-subtask dependency")      # Should succeed
   ```

2. **Edge cases**: Multiple consecutive hyphens, leading/trailing hyphens
   ```python
   query("session--start")    # Double hyphen
   query("-session-start")    # Leading hyphen
   query("session-start-")    # Trailing hyphen
   ```

3. **Mixed queries**: Hyphens + other special characters
   ```python
   query("session-start @hooks (validation)")  # Hyphen + special chars
   ```

4. **Regression tests**: Ensure existing queries still work
   ```python
   query("JWT authentication")           # No hyphens
   query("error handling patterns")      # Multi-word, no hyphens
   ```

### Test Files

- `tests/test_fts5_error_investigation.py`: Current error reproduction
- `tests/test_fts5_hyphen_fix.py`: Tests for fix verification (to be created)

---

## Summary

### Root Cause
FTS5 tokenizer splits hyphenated words at indexing time, but queries preserve hyphens, causing token mismatch. FTS5 interprets missing tokens as column names, producing "no such column" errors.

### Fix
Replace hyphens with spaces in query before FTS5 execution (one-line change at line 1010).

### Impact
- **Risk Level**: Low (simple sanitization change)
- **Breaking Changes**: None (improves error handling)
- **Performance**: No impact (same query complexity)
- **Testing**: Add hyphenated query test cases

### Next Steps
1. Implement Option A fix (hyphen replacement)
2. Add test cases for hyphenated queries
3. Verify no "no such column" errors
4. Test regression (ensure existing queries work)
5. Document fix in CHANGELOG
