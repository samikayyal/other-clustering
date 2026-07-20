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
6. Compute a language-conservative grouping key from the normalized value (see "Variant grouping key" below) and create a stable `variant_id` from that grouping key. Retain all source `answer_id` mappings and occurrence counts. For each variant group, select a deterministic representative surface form — the member normalized value with the highest occurrence count, ties broken by the lexicographically smallest canonical normalized string — and use that representative for redaction and embedding. Raw and normalized member texts are stored unchanged.
7. Detect language only once per unique normalized variant after deduplication. Prefer a valid analyst-supplied `answer_language`; otherwise use Lingua low-accuracy mode with the configured supported set plus `unknown`.
8. Treat low-confidence/unsupported detection as metadata warnings, not exclusion decisions. Arabic dialectal variation must remain usable even when the detector records only Arabic or `unknown`.
9. Apply deterministic redaction to the question, choice anchor fields, and eligible answer text before any remote request. Use stable placeholders such as `[EMAIL_1]` so equivalent redacted variants remain comparable.
10. Record cleanup counts, redaction counts/warnings, detector mode/language/confidence, and the cleanup/redaction policy hashes.

Expected statuses include `blank`, `nonsemantic_marker`, `eligible`, `redaction_warning`, and `language_uncertain`. `language_uncertain` is a warning state and must not by itself become final `unresolved_language`.

## Variant grouping key

Exact-normalized-value dedup fragments Arabic badly: orthographic variance (hamza/alef seat forms, taa marbuta versus haa, tatweel, mixed digit classes) makes equivalent dialectal answers count as distinct variants, which inflates embedding cost and biases frequency-driven discovery against Arabic. The grouping key fixes variant *identity* only; no stored raw, normalized, or redacted text is ever rewritten by these folds.

The key is computed from the normalized value in two tiers:

- **Safe tier (always applied):** tatweel (U+0640) removal; unification of Arabic-Indic (U+0660–U+0669) and Extended Arabic-Indic (U+06F0–U+06F9) digits with ASCII digits; folding of Arabic tashkeel/combining diacritics.
- **Aggressive tier (configurable, default enabled for the pilot):** alef/hamza-seat folding (أ/إ/آ → ا), taa marbuta → haa (ة → ه), and alef maqsura → yaa (ى → ي). These folds can merge distinct words (for example إن and أن), which is the standard Arabic-IR recall/precision trade; the tier must be a visible configuration knob, never a silent behavior.

Rules:

- The grouping policy (tier contents, tier enablement, and fold tables) is hashed and is a run-fingerprint input alongside the normalization and redaction policies.
- Occurrence counts, bounded expansion in discovery, and per-language dedup diagnostics all operate on grouped variants.
- Redaction and embedding operate on the group's representative surface form, never on the folded key text.
- Record per-language unique-variant counts before and after grouping in the preprocessing diagnostics and manifest so the dedup effect is measurable per language.

## Redaction digit-class coverage

Every digit-sensitive deterministic redaction rule — phone numbers, national IDs, long digit runs, and similar patterns — must match a defined digit class covering ASCII `0-9`, Arabic-Indic U+0660–U+0669, and Extended Arabic-Indic U+06F0–U+06F9. Implementations may either use explicit multi-class character classes or map digits to a common class for pattern *matching* only; in both cases the placeholder replaces the original span and the surrounding stored text is untouched. Rules must also tolerate Arabic thousands/decimal separators (U+066C, U+066B) and tatweel- or space-broken digit sequences where the pattern intent covers them. Redaction runs on the representative normalized text, never on the folded grouping key. The digit-class policy is part of the redaction policy hash.

## Privacy boundary

- Raw answer text remains local only.
- Passthrough metadata is retained for local output but is never a clustering feature and never enters a provider request.
- Every eligible original-language redacted variant continues to embedding regardless of detector confidence.
- Deterministic redaction does not guarantee removal of names or informal locations; this limitation must appear in warnings/manifest documentation.

## Implementation tasks

1. Implement pure normalization and symbol-cleanup functions with pinned policy metadata.
2. Implement configurable exact/regex non-semantic classification.
3. Implement the tiered grouping key, stable variant hashing from the grouping key, deterministic representative-surface-form selection, and source-row remapping.
4. Implement redaction with deterministic placeholder numbering, full digit-class coverage, and redaction summaries.
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
- Safe-tier folds group tatweel, mixed-digit-class, and tashkeel variants of the same text into one variant; stored raw/normalized/redacted texts remain byte-identical to their sources.
- Aggressive-tier folds group hamza-seat, taa marbuta, and alef maqsura variants when enabled, and do not apply when the tier is disabled; tier enablement changes the grouping policy hash.
- Representative-surface-form selection is deterministic under input reordering (highest occurrence count, then lexicographically smallest normalized value).
- Per-language unique-variant counts before and after grouping appear in the preprocessing diagnostics.
- Stable redaction placeholders produce equal redacted variants for equal source patterns and preserve non-sensitive text.
- Digit-sensitive redaction rules redact pure Arabic-Indic sequences (for example `٠٥٥١٢٣٤٥٦٧`), Extended Arabic-Indic sequences, mixed-class sequences, and sequences containing Arabic separators or benign breaks; equivalent numbers in different digit classes produce equivalent placeholders.
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
