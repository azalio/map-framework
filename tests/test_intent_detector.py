"""
Tests for Intent Detection Module.

Validates:
- Detection of all 6 Russian finish phrases
- Case-insensitive matching
- Edge case handling (None, empty string)
- False negatives (unrelated text)
- Word boundary detection
"""

from mapify_cli.intent_detector import detect_finish_intent


class TestDetectFinishIntent:
    """Test suite for detect_finish_intent function."""

    # ========================================================================
    # Individual Phrase Detection Tests
    # ========================================================================

    def test_detect_zakonchili(self):
        """Test detection of 'закончили' phrase."""
        assert detect_finish_intent("закончили работу") is True
        assert detect_finish_intent("мы закончили") is True
        assert detect_finish_intent("ЗАКОНЧИЛИ") is True

    def test_detect_ostanovimsya(self):
        """Test detection of 'остановимся' phrase."""
        assert detect_finish_intent("остановимся здесь") is True
        assert detect_finish_intent("давайте остановимся") is True
        assert detect_finish_intent("ОСТАНОВИМСЯ") is True

    def test_detect_khvatit(self):
        """Test detection of 'хватит' phrase."""
        assert detect_finish_intent("хватит на сегодня") is True
        assert detect_finish_intent("хватит") is True
        assert detect_finish_intent("ХВАТИТ работать") is True

    def test_detect_dalshe_ne_delay(self):
        """Test detection of 'дальше не делай' phrase."""
        assert detect_finish_intent("дальше не делай") is True
        assert detect_finish_intent("пожалуйста, дальше не делай") is True
        assert detect_finish_intent("ДАЛЬШЕ НЕ ДЕЛАЙ ничего") is True

    def test_detect_prekrashchay(self):
        """Test detection of 'прекращай' phrase."""
        assert detect_finish_intent("прекращай работу") is True
        assert detect_finish_intent("прекращай") is True
        assert detect_finish_intent("ПРЕКРАЩАЙ это") is True

    def test_detect_zakryvaem(self):
        """Test detection of 'закрываем' phrase."""
        assert detect_finish_intent("закрываем задачу") is True
        assert detect_finish_intent("закрываем") is True
        assert detect_finish_intent("ЗАКРЫВАЕМ проект") is True

    # ========================================================================
    # Case-Insensitivity Tests
    # ========================================================================

    def test_case_insensitive_lowercase(self):
        """Test case-insensitive matching with lowercase."""
        assert detect_finish_intent("закончили") is True
        assert detect_finish_intent("остановимся") is True
        assert detect_finish_intent("хватит") is True

    def test_case_insensitive_uppercase(self):
        """Test case-insensitive matching with uppercase."""
        assert detect_finish_intent("ЗАКОНЧИЛИ") is True
        assert detect_finish_intent("ОСТАНОВИМСЯ") is True
        assert detect_finish_intent("ХВАТИТ") is True

    def test_case_insensitive_mixed(self):
        """Test case-insensitive matching with mixed case."""
        assert detect_finish_intent("ЗаКоНчИлИ") is True
        assert detect_finish_intent("ОсТаНоВиМсЯ") is True
        assert detect_finish_intent("ХвАтИт") is True

    # ========================================================================
    # False Negative Tests (Unrelated Text)
    # ========================================================================

    def test_no_match_unrelated_russian(self):
        """Test that unrelated Russian text returns False."""
        assert detect_finish_intent("продолжаем работу") is False
        assert detect_finish_intent("давайте продолжим") is False
        assert detect_finish_intent("начинаем проект") is False
        assert detect_finish_intent("делаем дальше") is False

    def test_no_match_english_text(self):
        """Test that English text returns False."""
        assert detect_finish_intent("finish the work") is False
        assert detect_finish_intent("stop processing") is False
        assert detect_finish_intent("that's enough") is False

    def test_no_match_partial_phrase(self):
        """Test that partial phrases don't match (word boundaries)."""
        # These contain the letters but not as whole words
        assert detect_finish_intent("незакончили") is False
        assert detect_finish_intent("прекращайте") is False  # Different word form

    # ========================================================================
    # Edge Case Tests
    # ========================================================================

    def test_none_input(self):
        """Test handling of None input."""
        assert detect_finish_intent(None) is False

    def test_empty_string(self):
        """Test handling of empty string."""
        assert detect_finish_intent("") is False

    def test_whitespace_only(self):
        """Test handling of whitespace-only string."""
        assert detect_finish_intent("   ") is False
        assert detect_finish_intent("\n\t") is False

    # ========================================================================
    # Multiple Phrases Tests
    # ========================================================================

    def test_multiple_finish_phrases(self):
        """Test text containing multiple finish phrases."""
        assert detect_finish_intent("закончили и остановимся") is True
        assert detect_finish_intent("хватит, прекращай") is True

    def test_finish_phrase_in_sentence(self):
        """Test finish phrase embedded in longer sentence."""
        assert (
            detect_finish_intent("я думаю мы закончили эту задачу сегодня") is True
        )
        assert detect_finish_intent("давайте остановимся на этом моменте") is True
        assert detect_finish_intent("ну хватит уже на сегодня") is True

    # ========================================================================
    # Word Boundary Tests
    # ========================================================================

    def test_word_boundary_detection(self):
        """Test that regex respects word boundaries."""
        # Should match when phrase is a complete word
        assert detect_finish_intent("закончили") is True
        assert detect_finish_intent("слово закончили слово") is True

        # Should NOT match when phrase is part of a larger word
        # (Russian word boundaries work differently, but testing the concept)
        assert detect_finish_intent("незакончилиработу") is False  # no spaces

    # ========================================================================
    # Special Characters and Punctuation Tests
    # ========================================================================

    def test_finish_phrase_with_punctuation(self):
        """Test finish phrases with punctuation."""
        assert detect_finish_intent("закончили!") is True
        assert detect_finish_intent("хватит.") is True
        assert detect_finish_intent("остановимся?") is True
        assert detect_finish_intent("прекращай,") is True

    # ========================================================================
    # Contract Validation Tests
    # ========================================================================

    def test_postcondition_all_phrases(self):
        """Validate postcondition: result == True WHEN text CONTAINS finish_phrase."""
        finish_phrases = [
            "закончили",
            "остановимся",
            "хватит",
            "дальше не делай",
            "прекращай",
            "закрываем",
        ]

        for phrase in finish_phrases:
            # Direct phrase
            assert (
                detect_finish_intent(phrase) is True
            ), f"Failed for phrase: {phrase}"

            # Phrase in sentence
            assert (
                detect_finish_intent(f"давайте {phrase} работу") is True
            ), f"Failed for phrase in sentence: {phrase}"

            # Uppercase
            assert (
                detect_finish_intent(phrase.upper()) is True
            ), f"Failed for uppercase: {phrase}"

    def test_postcondition_no_phrase(self):
        """Validate postcondition: result == False WHEN text does NOT contain finish_phrase."""
        non_finish_texts = [
            "продолжаем",
            "начинаем",
            "делаем",
            "работаем дальше",
            "",
            None,
        ]

        for text in non_finish_texts:
            assert (
                detect_finish_intent(text) is False
            ), f"False positive for: {text}"

    # ========================================================================
    # Integration Tests
    # ========================================================================

    def test_realistic_user_messages(self):
        """Test realistic user messages that should trigger finish intent."""
        # Real-world examples of user finish requests
        finish_messages = [
            "закончили с этой задачей",
            "хватит на сегодня, остановимся",
            "дальше не делай, пожалуйста",
            "прекращай выполнение",
            "закрываем этот тикет",
            "мы закончили работу",
        ]

        for msg in finish_messages:
            assert (
                detect_finish_intent(msg) is True
            ), f"Failed to detect finish intent in: {msg}"

    def test_realistic_continue_messages(self):
        """Test realistic user messages that should NOT trigger finish intent."""
        continue_messages = [
            "продолжаем работу над задачей",
            "давайте сделаем еще одну итерацию",
            "начинаем следующий шаг",
            "делаем дальше по плану",
            "работаем над функцией",
        ]

        for msg in continue_messages:
            assert (
                detect_finish_intent(msg) is False
            ), f"False positive for: {msg}"

    # ========================================================================
    # Performance Test
    # ========================================================================

    def test_performance_large_text(self):
        """Test that detection works efficiently on large text."""
        # Create large text with finish phrase at the end
        large_text = "продолжаем работу " * 1000 + " закончили"

        # Should still detect the phrase
        assert detect_finish_intent(large_text) is True

        # Create large text without finish phrase
        large_text_no_match = "продолжаем работу " * 1000

        assert detect_finish_intent(large_text_no_match) is False
