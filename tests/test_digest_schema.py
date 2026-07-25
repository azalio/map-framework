"""Tests for mapify_cli.memory.digest_schema — single-source schema contract.

Coverage map:
  VC1 — field-name constants correctness + scratch/digest separation
  VC2 — redact_text() positive hits + false-negative guard
  VC3 — redact_secret_path() secret globs + safe paths
  VC4 — sanitize_value() control-char stripping + ordering invariant
"""

from __future__ import annotations

from mapify_cli.memory.digest_schema import (
    DIGEST_FRONTMATTER_FIELDS,
    EVENT_ENDED,
    EVENT_TURN,
    REDACTION_TOKEN,
    SCRATCH_ENDED_FIELDS,
    SCRATCH_TURN_FIELDS,
    redact_secret_path,
    redact_text,
    sanitize_value,
)

# ---------------------------------------------------------------------------
# VC1: field-name constants
# ---------------------------------------------------------------------------


class TestVC1FieldNameConstants:
    """VC1 [AC-6][INV-7]: field-name constants correctness and scratch/digest separation."""

    def test_vc1_scratch_turn_fields_exact(self) -> None:
        assert SCRATCH_TURN_FIELDS == (
            "ts",
            "turn",
            "session_id",
            "files_touched",
            "prompt_ref",
            "event",
        )

    def test_vc1_scratch_ended_fields_exact(self) -> None:
        assert SCRATCH_ENDED_FIELDS == ("event", "ts", "session_id")

    def test_vc1_digest_frontmatter_fields_exact(self) -> None:
        assert DIGEST_FRONTMATTER_FIELDS == (
            "session_id",
            "branch",
            "date",
            "slug",
            "files_touched",
            "decisions",
            "findings",
            "ticket_refs",
        )

    def test_vc1_decisions_not_in_scratch_turn(self) -> None:
        """decisions must NOT appear in scratch shape (LLM-inferred at finalize only)."""
        assert "decisions" not in SCRATCH_TURN_FIELDS

    def test_vc1_findings_not_in_scratch_turn(self) -> None:
        """findings must NOT appear in scratch shape (LLM-inferred at finalize only)."""
        assert "findings" not in SCRATCH_TURN_FIELDS

    def test_vc1_decisions_not_in_scratch_ended(self) -> None:
        assert "decisions" not in SCRATCH_ENDED_FIELDS

    def test_vc1_findings_not_in_scratch_ended(self) -> None:
        assert "findings" not in SCRATCH_ENDED_FIELDS

    def test_vc1_event_literals(self) -> None:
        assert EVENT_TURN == "turn"
        assert EVENT_ENDED == "ended"

    def test_vc1_event_field_in_both_scratch_tuples(self) -> None:
        assert "event" in SCRATCH_TURN_FIELDS
        assert "event" in SCRATCH_ENDED_FIELDS

    def test_vc1_session_id_in_all_shapes(self) -> None:
        assert "session_id" in SCRATCH_TURN_FIELDS
        assert "session_id" in SCRATCH_ENDED_FIELDS
        assert "session_id" in DIGEST_FRONTMATTER_FIELDS


# ---------------------------------------------------------------------------
# VC2: redact_text() — positive hits and false-negative guard
# ---------------------------------------------------------------------------


class TestVC2RedactText:
    """VC2 [security]: redact_text() replaces secrets; leaves benign strings untouched."""

    # --- positive: secrets must be redacted ---

    def test_vc2_openai_key_redacted(self) -> None:
        secret = "sk-abcdefghij0123456789"
        result = redact_text(secret)
        assert REDACTION_TOKEN in result
        assert "sk-abcdefghij0123456789" not in result

    def test_vc2_openai_key_in_sentence(self) -> None:
        text = "Authorization: Bearer sk-ABCDEF1234567890xyz1"
        result = redact_text(text)
        assert REDACTION_TOKEN in result
        assert "sk-ABCDEF" not in result

    def test_vc2_anthropic_ant_key_redacted(self) -> None:
        secret = "sk-ant-api03-XXXXXXXXXXXXXXXXXXXXXXXXXXXX"
        result = redact_text(secret)
        assert REDACTION_TOKEN in result
        assert "sk-ant-" not in result

    def test_vc2_anthropic_ant_key_not_matched_as_generic_sk(self) -> None:
        """sk-ant- variant must be fully redacted (not just the sk- prefix portion)."""
        secret = "sk-ant-v1-LongSecretToken1234567890abcdef"
        result = redact_text(secret)
        # The entire secret should be gone
        assert "sk-ant-v1-LongSecretToken" not in result

    def test_vc2_github_personal_token_redacted(self) -> None:
        secret = "ghp_ABCDEFGHIJKLMNOPQRSTuvwxyz1234"
        result = redact_text(secret)
        assert REDACTION_TOKEN in result
        assert "ghp_" not in result

    def test_vc2_github_oauth_token_redacted(self) -> None:
        secret = "gho_ABCDEFGHIJKLMNOPQRSTuvwxyz1234"
        result = redact_text(secret)
        assert REDACTION_TOKEN in result
        assert "gho_" not in result

    def test_vc2_github_user_token_redacted(self) -> None:
        secret = "ghu_ABCDEFGHIJKLMNOPQRSTuvwxyz1234"
        result = redact_text(secret)
        assert REDACTION_TOKEN in result

    def test_vc2_github_server_token_redacted(self) -> None:
        secret = "ghs_ABCDEFGHIJKLMNOPQRSTuvwxyz1234"
        result = redact_text(secret)
        assert REDACTION_TOKEN in result

    def test_vc2_github_refresh_token_redacted(self) -> None:
        secret = "ghr_ABCDEFGHIJKLMNOPQRSTuvwxyz1234"
        result = redact_text(secret)
        assert REDACTION_TOKEN in result

    def test_vc2_base64_blob_redacted(self) -> None:
        # 40+ char base64 blob
        secret = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmn"  # 40 chars
        result = redact_text(secret)
        assert REDACTION_TOKEN in result
        assert "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmn" not in result

    def test_vc2_base64_blob_with_padding_redacted(self) -> None:
        secret = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqr=="
        result = redact_text(secret)
        assert REDACTION_TOKEN in result

    def test_vc2_aws_access_key_redacted(self) -> None:
        secret = "AKIAIOSFODNN7EXAMPLE"  # canonical AWS example
        result = redact_text(secret)
        assert REDACTION_TOKEN in result
        assert "AKIAIOSFODNN7EXAMPLE" not in result

    def test_vc2_aws_access_key_in_config(self) -> None:
        text = "aws_access_key_id = AKIAIOSFODNN7EXAMPLEX"
        result = redact_text(text)
        assert REDACTION_TOKEN in result

    # --- false-negative guard: benign strings must be untouched ---

    def test_vc2_short_sk_prefix_not_redacted(self) -> None:
        """sk-short has fewer than 16 alphanum chars after sk- -> must NOT be redacted."""
        benign = "sk-short"
        assert redact_text(benign) == benign

    def test_vc2_hello_world_not_redacted(self) -> None:
        assert redact_text("hello world") == "hello world"

    def test_vc2_short_akia_not_redacted(self) -> None:
        """AKIA123 (< 16 uppercase digits after AKIA) -> must NOT be redacted."""
        benign = "AKIA123"
        assert redact_text(benign) == benign

    def test_vc2_empty_string_not_redacted(self) -> None:
        assert redact_text("") == ""

    def test_vc2_normal_sentence_not_redacted(self) -> None:
        text = "The quick brown fox jumps over the lazy dog."
        assert redact_text(text) == text


# ---------------------------------------------------------------------------
# VC3: redact_secret_path()
# ---------------------------------------------------------------------------


class TestVC3RedactSecretPath:
    """VC3 [security]: secret file paths are masked; normal paths pass through."""

    _REDACTED = "<redacted-secret-path>"

    # --- secret paths ---

    def test_vc3_bare_env(self) -> None:
        assert redact_secret_path(".env") == self._REDACTED

    def test_vc3_env_local(self) -> None:
        assert redact_secret_path("config/.env.local") == self._REDACTED

    def test_vc3_env_production(self) -> None:
        assert redact_secret_path(".env.production") == self._REDACTED

    def test_vc3_pem_file(self) -> None:
        assert redact_secret_path("server.pem") == self._REDACTED

    def test_vc3_pem_in_subdir(self) -> None:
        assert redact_secret_path("deploy/server.pem") == self._REDACTED

    def test_vc3_key_file(self) -> None:
        assert redact_secret_path("id_rsa.key") == self._REDACTED

    def test_vc3_key_in_subdir(self) -> None:
        assert redact_secret_path("ssh/id_rsa.key") == self._REDACTED

    def test_vc3_credentials_json(self) -> None:
        assert redact_secret_path("credentials.json") == self._REDACTED

    def test_vc3_credentials_in_subdir(self) -> None:
        assert redact_secret_path("config/credentials.json") == self._REDACTED

    def test_vc3_secrets_yaml(self) -> None:
        assert redact_secret_path("secrets.yaml") == self._REDACTED

    def test_vc3_secrets_in_subdir(self) -> None:
        assert redact_secret_path("k8s/secrets.yaml") == self._REDACTED

    # --- safe paths ---

    def test_vc3_python_source_safe(self) -> None:
        assert redact_secret_path("src/app.py") == "src/app.py"

    def test_vc3_readme_safe(self) -> None:
        assert redact_secret_path("README.md") == "README.md"

    def test_vc3_config_toml_safe(self) -> None:
        assert redact_secret_path("pyproject.toml") == "pyproject.toml"

    def test_vc3_tests_safe(self) -> None:
        assert redact_secret_path("tests/test_app.py") == "tests/test_app.py"


# ---------------------------------------------------------------------------
# VC4: sanitize_value()
# ---------------------------------------------------------------------------


class TestVC4SanitizeValue:
    """VC4 [security]: control-char stripping with correct ordering invariant."""

    def test_vc4_crlf_becomes_space(self) -> None:
        result = sanitize_value("a\r\nb")
        assert result == "a b"

    def test_vc4_cr_only_becomes_space(self) -> None:
        result = sanitize_value("a\rb")
        assert result == "a b"

    def test_vc4_lf_becomes_space(self) -> None:
        result = sanitize_value("a\nb")
        assert result == "a b"

    def test_vc4_tab_becomes_space(self) -> None:
        result = sanitize_value("a\tb")
        assert result == "a b"

    def test_vc4_null_char_stripped(self) -> None:
        result = sanitize_value("a\x00b")
        assert "\x00" not in result
        assert result == "ab"

    def test_vc4_bel_char_stripped(self) -> None:
        result = sanitize_value("a\x07b")
        assert "\x07" not in result

    def test_vc4_del_char_stripped(self) -> None:
        result = sanitize_value("a\x7fb")
        assert "\x7f" not in result
        assert result == "ab"

    def test_vc4_complex_input_no_control_chars_remain(self) -> None:
        """Full example from spec: 'a\r\nb\tc\x00d\x07e\x7ff'"""
        result = sanitize_value("a\r\nb\tc\x00d\x07e\x7ff")
        for char in result:
            code = ord(char)
            assert not (0x00 <= code <= 0x1F), f"Control char U+{code:04X} still present"
            assert code != 0x7F, "DEL U+007F still present"

    def test_vc4_complex_input_newlines_became_spaces(self) -> None:
        result = sanitize_value("a\r\nb\tc\x00d\x07e\x7ff")
        # \r\n -> \n -> ' ' and \t -> ' ' must have happened
        # The 'a' and 'b' must be separated by a space
        assert "a b" in result

    def test_vc4_ordering_rn_flattened_before_strip(self) -> None:
        """Verify \r\n is normalised to ONE space, not two spaces or stripped differently."""
        result = sanitize_value("x\r\ny")
        # \r\n -> \n (step 1), then \n -> ' ' (step 2) -> exactly one space between x and y
        assert result == "x y"

    def test_vc4_plain_text_passes_through_unchanged(self) -> None:
        text = "Hello, world! This is plain ASCII text."
        assert sanitize_value(text) == text

    def test_vc4_unicode_text_passes_through(self) -> None:
        text = "Привет мир — здесь всё хорошо"
        assert sanitize_value(text) == text

    def test_vc4_empty_string(self) -> None:
        assert sanitize_value("") == ""

    def test_vc4_all_c0_chars_stripped(self) -> None:
        """Every character in U+0000-U+001F and U+007F must be removed (excluding space/tab which become space)."""
        # Build a string with all C0 except \n, \r, \t (those become spaces, not stripped)
        c0_chars = "".join(chr(i) for i in range(0x20) if i not in (0x09, 0x0A, 0x0D))
        c0_chars += "\x7f"
        result = sanitize_value(c0_chars)
        for char in result:
            code = ord(char)
            assert not (0x00 <= code <= 0x1F), f"Control char U+{code:04X} remains"
            assert code != 0x7F
