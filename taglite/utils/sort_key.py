"""Shared sort key utilities for Chinese pinyin sorting."""

from pypinyin import lazy_pinyin


def pinyin_sort_key(text: str) -> str:
    """Return a lowercase pinyin sort key for a string.

    Chinese characters are converted to their pinyin representation.
    Non-Chinese characters pass through unchanged.
    """
    return "".join(lazy_pinyin(text)).lower()
