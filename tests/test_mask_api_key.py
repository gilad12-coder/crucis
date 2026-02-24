"""Tests for mask_api_key in crucis.diagnostics."""

import pytest

from crucis.diagnostics import mask_api_key

# Named constants for boundary values
MASK_THRESHOLD = 8
MASK_CHAR = "*"
SEPARATOR = "..."
PREFIX_LEN = 4
SUFFIX_LEN = 4


class TestMaskApiKeyEmpty:
    """Tests for empty string input."""

    def test_empty_string_returns_empty(self):
        """Verify empty input produces empty output."""
        assert mask_api_key("") == ""


class TestMaskApiKeyShortKeys:
    """Tests for keys shorter than the masking threshold."""

    @pytest.mark.parametrize(
        "key,expected",
        [
            ("a", "*"),
            ("ab", "**"),
            ("abc", "***"),
            ("abcd", "****"),
            ("short", "*****"),
            ("123456", "******"),
            ("1234567", "*******"),
        ],
        ids=[
            "length-1",
            "length-2",
            "length-3",
            "length-4",
            "length-5",
            "length-6",
            "length-7-boundary-minus-one",
        ],
    )
    def test_short_key_fully_masked(self, key: str, expected: str) -> None:
        """Verify keys below threshold are fully replaced with mask characters.

        Args:
            key: The input API key shorter than MASK_THRESHOLD.
            expected: The expected masked output of all '*' characters.
        """
        result = mask_api_key(key)
        assert result == expected
        assert len(result) == len(key)
        assert all(c == MASK_CHAR for c in result)


class TestMaskApiKeyLongKeys:
    """Tests for keys at or above the masking threshold."""

    @pytest.mark.parametrize(
        "key,expected",
        [
            ("12345678", "1234...5678"),
            ("123456789", "1234...6789"),
            ("abcdefghij", "abcd...ghij"),
            ("sk-ant-api03-abc123xyz789", "sk-a...z789"),
            ("1234567890abc", "1234...0abc"),
        ],
        ids=[
            "length-8-exact-boundary",
            "length-9-one-hidden-char",
            "length-10",
            "real-world-api-key",
            "length-13",
        ],
    )
    def test_long_key_partial_mask(self, key: str, expected: str) -> None:
        """Verify keys at or above threshold show first 4 and last 4 with separator.

        Args:
            key: The input API key at or above MASK_THRESHOLD length.
            expected: The expected masked output with prefix...suffix format.
        """
        result = mask_api_key(key)
        assert result == expected
        assert result.startswith(key[:PREFIX_LEN])
        assert result.endswith(key[-SUFFIX_LEN:])
        assert SEPARATOR in result


class TestMaskApiKeyMiddleStripped:
    """Tests verifying the middle portion is truly removed, not just separated."""

    def test_middle_chars_absent_from_output(self):
        """Verify characters between prefix and suffix do not appear in output."""
        key = "1234567890abc"
        result = mask_api_key(key)
        middle = key[PREFIX_LEN:-SUFFIX_LEN]
        assert middle not in result
        assert result == "1234...0abc"

    def test_length_9_single_hidden_char(self):
        """Verify length-9 key hides exactly 1 middle character."""
        key = "123456789"
        result = mask_api_key(key)
        assert result == "1234...6789"
        assert key[PREFIX_LEN] not in result

    def test_output_length_is_prefix_separator_suffix(self):
        """Verify masked output length equals prefix + separator + suffix."""
        key = "abcdefghijklmnop"
        result = mask_api_key(key)
        assert len(result) == PREFIX_LEN + len(SEPARATOR) + SUFFIX_LEN


class TestMaskApiKeySpecialCharacters:
    """Tests for keys containing non-standard characters."""

    def test_null_bytes_in_key(self):
        """Verify null bytes are handled correctly without C-string truncation."""
        key = "ab\x00cd\x00efgh"
        result = mask_api_key(key)
        assert result == "ab\x00c...efgh"

    def test_unicode_emoji_characters(self):
        """Verify multibyte Unicode characters are sliced by character, not byte."""
        key = "\U0001f600\U0001f601\U0001f602\U0001f603\U0001f604\U0001f605\U0001f606\U0001f607"
        result = mask_api_key(key)
        assert result.startswith(key[:PREFIX_LEN])
        assert result.endswith(key[-SUFFIX_LEN:])
        assert SEPARATOR in result

    def test_cjk_characters(self):
        """Verify CJK multibyte characters are handled at character level."""
        key = "\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b"
        result = mask_api_key(key)
        assert result == "\u4e00\u4e8c\u4e09\u56db...\u4e94\u516d\u4e03\u516b"

    def test_short_key_with_unicode(self):
        """Verify short Unicode keys are fully masked."""
        key = "\U0001f600\U0001f601\U0001f602"
        result = mask_api_key(key)
        assert result == "***"
        assert len(result) == len(key)


class TestMaskApiKeyReturnType:
    """Tests for return type consistency."""

    def test_returns_string_for_empty(self):
        """Verify return type is str for empty input."""
        assert isinstance(mask_api_key(""), str)

    def test_returns_string_for_short(self):
        """Verify return type is str for short input."""
        assert isinstance(mask_api_key("abc"), str)

    def test_returns_string_for_long(self):
        """Verify return type is str for long input."""
        assert isinstance(mask_api_key("abcdefghij"), str)
