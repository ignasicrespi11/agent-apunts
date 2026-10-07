"""Per-page language detection (D16) with py3langid.

py3langid (a maintained langid.py: Naive Bayes over character n-grams, ~5 MB, offline,
deterministic) is restricted to the configured languages. Choosing among 3 languages instead of 97
is what makes short slide text reliable, e.g. Catalan vs Spanish.
Rejected: lingua (more accurate on tiny texts, but a 170 MB wheel), langdetect (non-deterministic
unless seeded), fastText-based detectors (download a model at runtime).
"""

from functools import cache

from py3langid.langid import MODEL_FILE, LanguageIdentifier


@cache  # the model takes ~1 s to load: load it once per set of languages
def _identifier(languages: tuple[str, ...]) -> LanguageIdentifier:
    identifier = LanguageIdentifier.from_model_file(MODEL_FILE, norm_probs=True)
    identifier.set_languages(list(languages))
    return identifier


def detect_language(
    text: str, languages: tuple[str, ...], min_chars: int, min_confidence: float
) -> str | None:
    """ISO 639-1 code ('ca', 'es', 'en') or None if the text is too short or the guess is unsure.

    None is an honest answer: a wrong language label is worse than no label.
    """
    letters = sum(c.isalpha() for c in text)
    if letters < min_chars:
        return None
    language, confidence = _identifier(languages).classify(text)
    return language if confidence >= min_confidence else None
