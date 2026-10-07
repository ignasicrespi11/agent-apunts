"""Language detection restricted to the configured languages (D16)."""

import pytest

from agent_apunts.ingestion.language import detect_language
from tests.pdf_factory import CATALAN, ENGLISH, SPANISH

LANGS = ("ca", "es", "en")


@pytest.mark.parametrize("text,expected", [(CATALAN, "ca"), (SPANISH, "es"), (ENGLISH, "en")])
def test_detects_configured_languages(text, expected):
    assert detect_language(text, LANGS, min_chars=20, min_confidence=0.8) == expected


def test_too_short_is_none():
    assert detect_language("Tema 3", LANGS, min_chars=20, min_confidence=0.8) is None


def test_unsure_is_none():
    # With an impossible confidence bar nothing passes: None rather than a guess.
    assert detect_language(CATALAN, LANGS, min_chars=20, min_confidence=1.01) is None
