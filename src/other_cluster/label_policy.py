"""Provider-independent bilingual category-label policy."""

from __future__ import annotations

import re
import unicodedata

from .errors import ClusterClassificationError

_ARABIC_DIACRITICS = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]")
_ARABIC_LETTER = re.compile(r"[\u0621-\u063A\u0641-\u064A\u0671-\u06D3]")
_ARABIC_ALLOWED = re.compile(
    r"^[0-9\u0660-\u0669\u0621-\u063A\u0641-\u064A\u0671-\u06D3\s-]+$"
)
_ENGLISH_ALLOWED = re.compile(r"^[A-Za-z0-9\s'-]+$")
_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)
_PROHIBITED_ENGLISH = {"other", "miscellaneous", "various", "unknown", "unclear"}
_PROHIBITED_ARABIC = {
    "اخرى",
    "أخرى",
    "متنوع",
    "متنوعة",
    "متنوعات",
    "غير معروف",
    "غير واضحة",
}
_SENSITIVE_TERMS = {
    "respondent",
    "enumerator",
    "identifier",
    "personal id",
    "phone number",
    "national id",
    "رقم الهوية",
    "رقم الهاتف",
    "اسم المبحوث",
}


def collapse_whitespace(value: str) -> str:
    return " ".join(value.split())


def normalize_label(value: str) -> str:
    """Normalize one label for same-question exact-duplicate checks."""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = _ARABIC_DIACRITICS.sub("", normalized)
    return collapse_whitespace(_PUNCTUATION.sub(" ", normalized))


def validate_label_pair(
    english: str,
    arabic: str,
    *,
    existing_normalized: set[str],
    proposed_normalized: set[str],
) -> list[str]:
    """Return mechanical bilingual-label validation failures."""

    errors: list[str] = []
    english_clean, arabic_clean = (
        collapse_whitespace(english),
        collapse_whitespace(arabic),
    )
    if not 1 <= len(english_clean.split()) <= 6:
        errors.append("English label must contain 1 to 6 words")
    if not 1 <= len(arabic_clean.split()) <= 6:
        errors.append("Arabic label must contain 1 to 6 words")
    if not _ENGLISH_ALLOWED.fullmatch(english_clean) or not re.search(
        r"[A-Za-z]", english_clean
    ):
        errors.append(
            "English label must use Latin letters and supported punctuation only"
        )
    if (
        _ARABIC_DIACRITICS.search(arabic_clean)
        or not _ARABIC_ALLOWED.fullmatch(arabic_clean)
        or not _ARABIC_LETTER.search(arabic_clean)
    ):
        errors.append("Arabic label must use Arabic script without diacritics")
    normalized_english, normalized_arabic = (
        normalize_label(english_clean),
        normalize_label(arabic_clean),
    )
    if normalized_english in _PROHIBITED_ENGLISH or normalized_arabic in {
        normalize_label(item) for item in _PROHIBITED_ARABIC
    }:
        errors.append("labels must not use a prohibited generic category")
    if (
        normalized_english in existing_normalized
        or normalized_arabic in existing_normalized
    ):
        errors.append("labels must not duplicate an existing choice")
    if (
        normalized_english in proposed_normalized
        or normalized_arabic in proposed_normalized
    ):
        errors.append("labels must not duplicate another proposed category")
    if any(
        term in f"{normalized_english} {normalized_arabic}" for term in _SENSITIVE_TERMS
    ):
        errors.append("labels must not contain personal or sensitive details")
    return errors


def validate_analyst_label_pair(
    english: str,
    arabic: str,
    *,
    existing_labels: set[str],
    other_category_labels: set[str],
) -> tuple[str, str]:
    """Validate and normalize one analyst-supplied bilingual label pair."""

    errors = validate_label_pair(
        english,
        arabic,
        existing_normalized={normalize_label(item) for item in existing_labels},
        proposed_normalized={normalize_label(item) for item in other_category_labels},
    )
    if errors:
        raise ClusterClassificationError("; ".join(errors))
    return collapse_whitespace(english), collapse_whitespace(arabic)
