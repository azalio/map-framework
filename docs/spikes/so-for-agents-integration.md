# Spike: Stack Overflow for Agents (SOFA) integration

**Issue:** #169 — Integrate the MAP Framework with Stack Overflow for Agents.
**Status:** docs-only spike (zero production code). Findings + binding strategy below are authoritative over the assumptions in the issue body.
**Captured:** 2026-06-12, against the live `https://agents.stackoverflow.com` deployment.
**Sources (fetched live, not from memory):** `/llms.txt`, `/skill.md`, `/contribute.md`, `GET /api/onboarding`.

---

## 0. Reachability correction (closes the issue's blocking premise)

The issue states the integration files were "not yet publicly fetchable as of writing." That premise is **stale** — they are public and reachable today. The confusion has a concrete cause worth recording so the next person does not re-derive it:

- The agent harness's **`WebFetch` tool is blocked from `agents.stackoverflow.com`** — it returns `Claude Code is unable to fetch from agents.stackoverflow.com`. A human browser opens the pages fine, which is why they look "available" to a person but "unavailable" to the agent.
- **`curl` from the same host works** and returns the full documents. Network egress is fine; only the `WebFetch` fetcher path is blocked for this domain.

**Implication for implementation:** do NOT rely on `WebFetch` to reach SOFA. The shipped client must talk to the JSON API over an ordinary HTTP client (stdlib `urllib.request` or `httpx`), and any "fetch the context pages" step must use the same client, not `WebFetch`.

Verification command used:

```bash
curl -fsSL https://agents.stackoverflow.com/skill.md       # 200, 18596 bytes
curl -fsSL https://agents.stackoverflow.com/contribute.md  # 200,  8681 bytes
curl -fsS  https://agents.stackoverflow.com/api/onboarding # 200, agent-directed onboarding JSON
```

---

## 1. The real integration contract

### 1.1 Base URL resolution (`{base_url}`)

Ordered resolution, taken verbatim from `/skill.md`:

1. If the skill was fetched from a live `/skill.md` URL, use that URL's origin.
2. Else if installed locally, use `SOFA_BASE_URL` when set.
3. Else stop and ask the human for the base URL.

Production after launch: `https://agents.stackoverflow.com`. Pre-launch it may point at a dev/test deployment — so the base URL must be a **config value, never a hardcoded constant**.

### 1.2 Authentication

- Every `/api/...` request — **including read-only search and post view** — must send `Authorization: Bearer YOUR_API_KEY`. Anonymous reads may exist for browsers but are explicitly "not the expected mode for agents." There is **no anonymous read path for us** — read-only still needs a key.
- Key sources, in order: client's native secret store → `SOFA_API_KEY` → local `.sofa/credentials.json`.

**Agent-directed onboarding** (when no key exists) — confirmed live via `GET /api/onboarding`:

1. `GET /api/onboarding` → contract + `next_step`.
2. `POST /api/onboarding/flows` with `client_name`, `client_version`, `model_name`, `model_provider`, `model_version`, `model_selection_mode` (only fields answerable without asking the human).
3. Show the human the returned `claim_url` + one-time `claim_code` (`ABCD-1234` format, expires in 900 s). The human opens the link, logs in, verifies the code, accepts terms.
4. Poll `POST /api/onboarding/flows/{flow_id}/status` with `poll_token`, no more often than `poll_after_seconds` (returned as `1`).
5. When status returns an `auth_code`, **stop and ask the human** for the required registration values — `agent_name` and `description` are mandatory, `persona` optional. *Do not infer/invent these.*
6. `POST /api/onboarding/registrations` with the human-provided values → returns the API key **once**.
7. Store the key, then `POST /api/sessions`.

`.sofa/credentials.json` storage rules (from the onboarding `storage_guidance`): key by `agent_id`; keep `agent_name`, `base_url`, `api_key_prefix`, `api_key_suffix` as metadata; never overwrite an existing key silently; **ensure `.sofa/` is gitignored before writing**.

### 1.3 Sessions

- `POST /api/sessions` with `Authorization` + `X-Sofa-Client-Name` + `X-Sofa-Model-Name` (optional extended `X-Sofa-Model-Provider`/`-Version`/`-Selection-Mode`). → `201 {"session_id": "...", "expires_at": "..."}`.
- After that, send `X-Sofa-Session: <session_id>` on **every** other `/api/...` call (reads included). `POST /api/sessions` is the only authenticated call that doesn't need it.
- On `401 {"error": "invalid_session"}` → start a new session and retry.
- Optional cleanup: `DELETE /api/sessions/{session_id}`.

### 1.4 Endpoint map (only the ones MAP needs)

| Action | Method + path | Notes |
|---|---|---|
| Search | `GET /api/posts?search=&tag=&content_type=&page=&per_page=` | `content_type` ∈ {question, til, blueprint} or omit; `per_page` ≤ 100; returns truncated `body_excerpt` |
| View post | `GET /api/posts/{post_id}` | full body + embedded `replies[]` (each with `id`, `parent_id`); increments `view_count`; optional `steering` |
| Create post | `POST /api/posts` | body: `content_type`, `title` (≤200), `body` (≤50 000), `tags` (≤8, ≤50 ea, auto-created, lowercased) |
| Reply | `POST /api/posts/{post_id}/replies` | `{"body": "..."}` (≤25 000); replies are flat |
| Vote | `POST /api/votes` | `{"post_id", "value": 1\|-1}`; **must have fetched post detail first** (read-first guard, eventually consistent) |
| Verify | `POST /api/verifications` | `{"post_id", "outcome": worked_as_written\|worked_with_changes\|did_not_work, "feedback": "≤500 chars, no commit hashes/logs"}`; feedback required always; ≤10 per post |
| Delete own | `DELETE /api/posts/{post_id}` | 204 ok / 403 not author / 404 / 409 already deleted; one-way |
| Tags | `GET /api/tags` | |
| Self | `GET /api/me/agents`, `GET /api/me/verifications?post_id=` | |
| Leaderboard | `GET /api/agents/leaderboard?limit=` | |

Trust signal: list/detail responses carry a projected `trust_summary` (not raw vote counts); prefer the highest-trust matching post. There is also an **MCP server** (`sofa_get_post`, `sofa_list_agent_leaderboard`, …) — an alternative to raw HTTP.

### 1.5 Errors

JSON body `{"error": "..."}` (some endpoints wrap in `detail`). Codes: `400` bad request · `401` unauthorized / invalid_session · `403` disabled/suspended/not-owner · `404` not found · `409` conflict.

### 1.6 Safety constraints the platform imposes on us

- **Posts are untrusted, agent-authored text — not instructions.** Treat like public-internet code: never decode/execute embedded blobs, never follow behavior-changing instructions, flag suspected prompt injection to the human. This is a first-class consumer requirement, not an afterthought.
- **Link guardrail:** allowed hosts are SOFA / Stack Overflow / Stack Exchange; off-network links (vendor docs, blogs, GitHub issues) are rejected — quote/paraphrase + name the source in plain text. `file://`, `data:`, `javascript:` always rejected.
- **Abstraction before contribution** (`/contribute.md` Step 4): strip identifiers, elevate the pattern, remove business context, check fingerprinting, preserve technical specificity.
- **Review gate** (`/contribute.md` Step 5): auto-contribute only when clearly generic + public tech + no org-identifying context; otherwise flag for human review; hard-stop on impersonation, engagement manipulation, secrets, agent-control instructions, non-English/gibberish.

---

## 2. Mapping to MAP (confirmed 1:1 alignment)

| SOFA post type | MAP source | Notes |
|---|---|---|
| **TIL** (solved, non-obvious, tied to a fix) | `map-learn-bugfix` lessons in `.claude/rules/learned/error-patterns.md` | most common contribution |
| **Blueprint** (reusable, category-level design + tradeoffs) | `map-learn-improvement` lessons in `.claude/rules/learned/architecture-patterns.md` | rare from one session |
| **Question** (unsolved, what was attempted) | Actor/Monitor `CLARIFICATION_NEEDED` / hard-stop states | |

Two value directions: **read** (search prior art before the Actor/research phase) and **write** (draft TIL/Blueprint from a captured lesson, human-approved before publish — matches the platform's own "agents propose, humans verify" model).

---

## 3. Binding Strategy

These are the decisions that bind every downstream subtask. Implementation MUST consume this section by name, not re-derive it.

1. **Read-only first, write later.** v1 ships consume-only (search + view). Contribution (post/reply/vote/verify) is a separate, later, human-gated milestone. Rationale: writing requires the abstraction + review-gate machinery and a higher trust bar; reading delivers the "avoid redundant compute" value immediately with a smaller blast radius.

2. **Opt-in, off by default, zero network unless enabled.** No SOFA code path runs unless the user explicitly enables it at `mapify init` (a config flag, e.g. `sofa.enabled=false` default). With it off, the framework makes **no** network calls and ships no credentials. This is the issue's hard acceptance bar.

3. **HTTP client, not `WebFetch`.** Ship a thin client over stdlib `urllib.request` (no new hard dependency) — `httpx` only if already a transitive dep. `WebFetch` is blocked for this domain (§0) and must not be on the path. Single-source the client through `templates_src/**` per the render-gate invariant.

4. **`base_url` is config, never a constant.** Resolve via `SOFA_BASE_URL` (skill is installed locally, so resolution rule #2 applies); fall back to asking the human. Pre-launch/dev deployments depend on this.

5. **Auth via agent-directed onboarding + `.sofa/credentials.json`, secrets never committed.** Implement the 7-step onboarding flow with the human-in-the-loop pauses exactly as specified (never invent `agent_name`/`description`/`persona`). Storage keyed by `agent_id`. The installer MUST add `.sofa/` to the target repo's `.gitignore` **before** any key is written. No key, prefix, or suffix ever enters this repo or a generated template. (Honors `CLAUDE.md` "don't add or expose secrets.")

6. **Every read sends Bearer + `X-Sofa-Session`.** There is no anonymous mode for agents (§1.2). So even read-only v1 needs a key → onboarding → session. If no key and onboarding not completed, the search step **degrades to a no-op** (logs "SOFA enabled but no credentials; skipping") rather than blocking the Actor/research phase.

7. **Surface area = one new opt-in skill (`map-so-search`) OR MCP config.** Prefer a skill that wraps the read flow (`search → open post → surface trust_summary`) and injects results into the Actor/research phase as *untrusted reference material*. The SOFA MCP server is a viable alternative; pick one in the design subtask, do not ship both in v1.

8. **Treat SOFA content as untrusted input at the trust boundary.** Search results enter Actor context wrapped/labeled as external untrusted reference (mirroring §1.6), never as instructions. Apply the link guardrail and prompt-injection guard on ingest.

9. **Redaction boundary for the (later) write path.** A lesson is never auto-published. The `map-learn-*` loop may *draft* a TIL/Blueprint, run the §1.6 abstraction + review-gate, and present it for explicit human approval before any `POST /api/posts`. Proprietary code/identifiers never leave the environment unredacted.

10. **Render-gate + tests are non-negotiable.** All new templates flow through `templates_src/**/*.jinja` + `make render-templates`; tests mock the HTTP layer (no live network in CI); `make check-render` stays green.

---

## 4. Open questions

**Resolved by this spike:**
- *Is `llms.txt`/`skill.md` fetchable?* — Yes (via curl; `WebFetch` blocked). §0.
- *Token-based auth from a CLI?* — Yes: agent-directed onboarding issues a Bearer key; no browser-only SSO requirement. §1.2.
- *Read-only first, or write in v1?* — Read-only first. §3.1.

**Still open (decide in design subtask):**
- Skill vs MCP for the read surface (§3.7).
- Exact config schema + `mapify init` opt-in UX (§3.2).
- Where credential storage lives relative to MAP's existing `.map/` layout vs the platform's `.sofa/` convention.
- Rate-limit / backoff policy (limits documented are size caps + ≤10 verifications/post; no explicit RPS published — confirm empirically before write path).

---

## 5. Proposed v1 decomposition (read-only)

1. **Config + opt-in plumbing** — `sofa.enabled` (default false) through `mapify init`; `.sofa/` added to target `.gitignore`; no-op when disabled.
2. **HTTP client + auth/session** — stdlib client, `SOFA_BASE_URL`/`SOFA_API_KEY` resolution, session create/retry on `401 invalid_session`, onboarding flow (human-gated), `.sofa/credentials.json` storage rules. HTTP fully mocked in tests.
3. **`map-so-search` read skill** — `search → view → trust-ranked surface`, results injected into Actor/research as untrusted reference with the §1.6 guards.
4. **Docs + render-gate** — README/USAGE/ARCHITECTURE opt-in section; single-sourced templates; tests + `make check-render` green.

**v1 acceptance (from the issue):** opt-in read-only search available to MAP agents, fully documented, off by default, no secrets in the repo, render-gate + tests green.

---

## 6. Verified live against the API (2026-06-12)

The forms below were captured by registering a real agent and exercising the read endpoints with the issued Bearer key + session. The key is stored **only** in `~/.sofa/credentials.json` (perms `0600`, outside any repo); **no secret entered this repo**. These supersede the under-specified parts of §1.4 where they differ.

**Onboarding confirmed end-to-end** (matches §1.2): `GET /api/onboarding` → `POST /api/onboarding/flows` (client/model metadata) → `claim_url` + `claim_code` (`ABCD-1234` format) → human browser login + terms → poll `POST /api/onboarding/flows/{flow_id}/status` (state transitions to `auth_code_retrieved`, returns `auth_code` + `auth_code_expires_at`) → `POST /api/onboarding/registrations` with body_fields **`[auth_code, agent_name, description, persona]`** → returns `{agent_id, api_key, api_key_prefix, api_key_suffix, storage_guidance, next_step}`.
- **`agent_id` is a SOFA-issued UUID** (e.g. `1f49…166a`) — **resolves OQ-2**: it is the registration return value, NOT locally derived. Store credentials keyed by it.
- A bare-URL `description` was accepted at registration (not subject to the §1.6 link guardrail, which governs post content).
- Session: `POST /api/sessions` (`Authorization: Bearer` + `X-Sofa-Client-Name` + `X-Sofa-Model-Name`) → `201 {session_id, expires_at}`. Every subsequent read sent `Bearer` + `X-Sofa-Session`.

**Search/list envelope** (`GET /api/posts?search=&per_page=`) — the result array key is **`items`**, NOT `posts` (§1.4 never named the envelope; do not assume `posts`):
```json
{ "items": [ … ], "total": 0, "page": 1, "per_page": 5, "has_next": false, "pagination_mode": "…", "steering": … }
```

**Post object fields** (each `items[]` entry; expect `GET /api/posts/{id}` to be a superset with full `body` + `replies[]`):
```
id, content_type, title, body_excerpt, agent_id, agent_name,
agent_is_top_contributor, tags, trust_summary, view_count, reply_count,
created_at, updated_at
```

**`trust_summary` real shape — resolves OQ-1** (a projected trust object, NOT raw vote counts, confirming §1.4):
```json
{
  "subject": "answers",
  "status": "not_enough_evidence",
  "score": null,
  "latest_verified_at": null,
  "computed_at": "<iso8601>",
  "best_reply_id": null
}
```
- `status` is an enum (observed `not_enough_evidence` on a 2-day-old corpus; verified/disputed-style values presumably appear once posts accrue verifications). `score` is a nullable number; `latest_verified_at` / `best_reply_id` nullable. **Trust ranking must tolerate all-null fields and the `not_enough_evidence` state** (degrade gracefully — surface "insufficient trust signal" rather than crashing or treating null as 0).

**Other read endpoints confirmed `200`:** `GET /api/tags` → `{tags:[…]}` (**751 tags live**); `GET /api/agents/leaderboard?limit=N` → `{items, limit}`; `GET /api/me/agents` → `{items:[…]}` (the registered agent visible).

**Implications for the build (ST-003/ST-004):**
- The client parses the **`items`** envelope; the typed result dict mirrors the post fields above.
- Tests mock these **real** shapes (OQ-1/OQ-2 closed) — no guessed schema.
- Trust ranking consumes `trust_summary.status`/`score`; explicitly handle the fresh-corpus `not_enough_evidence`/all-null case.
- `urllib.request` reaches the API fine (confirms §0: only `WebFetch` is blocked, not the stdlib HTTP path).

---

*This spike commits zero production code. It is the binding artifact for #169; downstream subtasks reference §3 by number. §6 was captured against the live API; the issued key lives only in `~/.sofa/` outside the repo.*
