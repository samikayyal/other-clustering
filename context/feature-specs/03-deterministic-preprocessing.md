# Spec 03 — Deterministic Preprocessing

**Status:** Planned
**Dependencies:** Spec 01, Spec 02
**Implementation order:** 03 of 11

## Outcome

Every validated answer row is classified, normalized, language-assessed, redacted when eligible, and mapped to a deterministic unique variant without changing the locally preserved raw answer. This slice performs no semantic provider calls.

## Processing contract

Process each validated answer as follows:

1. Preserve `answer_text` exactly for local audit output.
2. Classify blank and configured non-semantic values before semantic work. Use explicit statuses such as `blank` and `nonsemantic_marker`.
3. Normalize analysis text with Unicode NFC, removal of emoji grapheme sequences and remaining Unicode `So`/`Sk` symbols according to pinned data, removal of unprintable controls, whitespace replacement/collapse, and trimming.
4. Preserve letters, combining marks, numbers, ordinary punctuation, currency/math symbols, Arabic marks, and language-relevant zero-width joiners/non-joiners when they are not part of an emoji sequence.
5. Do not translate, transliterate, correct spelling, or perform language-dependent rewriting. If cleanup leaves no substantive text, classify the row as blank/non-semantic and exclude it from provider calls.
6. Create a stable `variant_id` from the canonical normalized value and retain all source `answer_id` mappings and occurrence counts.
7. Detect language only once per unique normalized variant after deduplication. Prefer a valid analyst-supplied `answer_language`; otherwise use Lingua low-accuracy mode with the configured supported set plus `unknown`.
8. Treat low-confidence/unsupported detection as metadata warnings, not exclusion decisions. Arabic dialectal variation must remain usable even when the detector records only Arabic or `unknown`.
9. Apply deterministic redaction to the question, choice anchor fields, and eligible answer text before any remote request. Use stable placeholders such as `[EMAIL_1]` so equivalent redacted variants remain comparable.
10. Record cleanup counts, redaction counts/warnings, detector mode/language/confidence, and the cleanup/redaction policy hashes.

Expected statuses include `blank`, `nonsemantic_marker`, `eligible`, `redaction_warning`, and `language_uncertain`. `language_uncertain` is a warning state and must not by itself become final `unresolved_language`.

## Privacy boundary

- Raw answer text remains local only.
- Passthrough metadata is retained for local output but is never a clustering feature and never enters a provider request.
- Every eligible original-language redacted variant continues to embedding regardless of detector confidence.
- Deterministic redaction does not guarantee removal of names or informal locations; this limitation must appear in warnings/manifest documentation.

## Implementation tasks

1. Implement pure normalization and symbol-cleanup functions with pinned policy metadata.
2. Implement configurable exact/regex non-semantic classification.
3. Implement stable variant hashing and source-row remapping.
4. Implement redaction with deterministic placeholder numbering and redaction summaries.
5. Implement language-hint precedence and post-deduplication Lingua assessment.
6. Return typed `NormalizedVariant` and `LanguageAssessment` records for downstream stages.

## Tests

- Raw text is unchanged after every preprocessing operation.
- NFC normalization and whitespace cleanup are deterministic.
- Emoji sequences, variation selectors, skin-tone modifiers, joiners, `So`, and `Sk` cleanup are deterministic and counted.
- Arabic letters/marks, dialectal Arabic text, English text, punctuation, numbers, currency/math symbols, spelling errors, and other scripts remain usable.
- Symbol-only/cleanup-empty values receive explicit non-semantic/blank outcomes.
- Exact and regex marker matching is configurable and does not classify ordinary meaningful answers accidentally.
- Duplicate normalized values produce one semantic variant with correct source-row mapping and occurrence count.
- Stable redaction placeholders produce equal redacted variants for equal source patterns and preserve non-sensitive text.
- Analyst language hint wins over local detection; uncertain detection emits a warning but does not skip embedding.
- Question and choice text use the same redaction policy as answers.
- No provider adapter receives passthrough metadata or unredacted text in an integration spy test.

## Acceptance criteria

- The same validated workbook and configuration produce byte-stable preprocessing records and policy hashes.
- Every source row has an explicit preprocessing status and either a variant mapping or a deliberate non-semantic/blank exclusion.
- Arabic—including dialectal Arabic—and English are preserved in their supplied scripts with no translation call or translated field.
- Downstream stages can process only typed redacted variants and cannot accidentally recover raw answer text through provider-bound models.

## Non-goals

- Embeddings, similarity scoring, clustering, LLM verification, category labels, or final assignment.
