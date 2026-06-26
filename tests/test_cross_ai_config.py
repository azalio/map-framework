"""Cross-AI peer review (#288) — project config behavior.

Covers the MapConfig dataclass fields, the dotted-key YAML aliasing
(`review.cross_ai.*` -> snake_case), enum/bounds validation fallbacks, and the
generated default-config documentation.
"""

from __future__ import annotations

from mapify_cli.config.project_config import (
    VALID_CROSS_AI_RUNTIMES,
    MapConfig,
    generate_default_config,
    load_map_config,
)


def _write_config(tmp_path, body: str) -> None:
    (tmp_path / ".map").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".map" / "config.yaml").write_text(body, encoding="utf-8")


class TestCrossAiConfigDefaults:
    def test_defaults_are_off_and_codex(self):
        cfg = MapConfig()
        assert cfg.review_cross_ai_enabled is False
        assert cfg.review_cross_ai_runtime == "codex"
        assert cfg.review_cross_ai_timeout_seconds == 180

    def test_known_runtimes_set(self):
        assert {"claude", "codex", "gemini", "opencode"} <= VALID_CROSS_AI_RUNTIMES


class TestCrossAiConfigLoad:
    def test_absent_config_uses_defaults(self, tmp_path):
        cfg = load_map_config(tmp_path)
        assert cfg.review_cross_ai_enabled is False
        assert cfg.review_cross_ai_runtime == "codex"

    def test_dotted_keys_alias_to_fields(self, tmp_path):
        _write_config(
            tmp_path,
            "review.cross_ai.enabled: true\n"
            "review.cross_ai.runtime: gemini\n"
            "review.cross_ai.timeout_seconds: 90\n",
        )
        cfg = load_map_config(tmp_path)
        assert cfg.review_cross_ai_enabled is True
        assert cfg.review_cross_ai_runtime == "gemini"
        assert cfg.review_cross_ai_timeout_seconds == 90

    def test_invalid_runtime_falls_back_to_codex(self, tmp_path):
        _write_config(tmp_path, "review.cross_ai.runtime: notarealcli\n")
        assert load_map_config(tmp_path).review_cross_ai_runtime == "codex"

    def test_nonpositive_timeout_falls_back(self, tmp_path):
        _write_config(tmp_path, "review.cross_ai.timeout_seconds: 0\n")
        assert load_map_config(tmp_path).review_cross_ai_timeout_seconds == 180

    def test_enabled_alone_keeps_runtime_default(self, tmp_path):
        _write_config(tmp_path, "review.cross_ai.enabled: true\n")
        cfg = load_map_config(tmp_path)
        assert cfg.review_cross_ai_enabled is True
        assert cfg.review_cross_ai_runtime == "codex"


class TestCrossAiConfigDoc:
    def test_default_config_documents_cross_ai(self):
        body = generate_default_config(include_comments=True)
        assert "review.cross_ai.enabled" in body
        assert "review.cross_ai.runtime" in body
        assert "review.cross_ai.timeout_seconds" in body
