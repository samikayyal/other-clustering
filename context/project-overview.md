# Project Overview

## Product Summary

`other-cluster` is a Python workflow that groups free-text survey answers submitted through an "Other" option into coded categories. It uses a command-line pipeline for processing and a review web application for analyst approval.

The application receives either an `.xlsx` coding workbook or a native Google Sheets link. A Google Sheets link is exported as `.xlsx` into `./.temp/` for the duration of the run and the downloaded file is deleted when the run finishes or fails. The workbook is shaped like the supplied synthetic example:

<https://docs.google.com/spreadsheets/d/17k1eFC7paInFW6tlz6dzETvg5tfciQOH5L0zwQeyd7E/edit?gid=15457928#gid=15457928>

The synthetic workbook is expected to contain repeated, non-unique answers. The application uses those answers as evidence for assigning existing survey choices and discovering new recurring meanings.

Answers remain in their original language. Expected input includes Arabic, dialectal Arabic, and English. The application must not translate answers before embedding or categorizing them.

## Primary Outcome

For each supported "Other" question, the application must:

1. Read the question identifier and bilingual question text from `Survey`.
2. Read the question's already existing choices from `Code`, excluding the "Other" choice itself.
3. Read each respondent's free-text answer from `Data` and retain its exact respondent `KEY`, source row, and source answer column.
4. Conservatively assign answers to an existing choice when that meaning is verified.
5. Discover dense groups among answers that do not safely match an existing choice.
6. Give each proposed new group an English and Arabic label.
7. Allocate a proposed workbook-wide unique value greater than `100` to each proposed new category.
8. Present every proposed assignment, new category, and unresolved answer to an analyst for a complete review.
9. Only after the analyst confirms the entire review, add approved new categories to `Code` and write approved results through the output contract defined for the later review/finalization features.

An example new code-list row is:

```text
B5_other | 101 | Lebanese | لبناني
```

## Users and Operating Model

The intended user is a survey-coding operator who runs the application locally from a terminal against a prepared workbook, then reviews or uses the coded workbook.

- Invocation is through the `other-cluster` console entry point.
- Python execution and dependency management use `uv`.
- A run is fully non-interactive after invocation; the application does not prompt the operator while processing.
- Every assignment and generated category requires analyst review and explicit confirmation before any coding result is written to the workbook.
- The intended review surface is a web application defined by Feature 06.
- Until the web application is implemented, the CLI prints a structured review package in the terminal. The analyst returns a matching structured approval response through a separate finalization step, so the analysis run itself remains non-interactive.
- A partial approval is never enough to modify the workbook: the analyst must confirm the disposition of every proposed assignment, new category, noise point, rare answer, rejected cluster, and uncertain match.

## In Scope

- Local `.xlsx` workbook ingestion and output.
- Native Google Sheets link ingestion through temporary `.xlsx` export.
- Extraction of question metadata, existing choices, respondent answers, and workbook row locations.
- Original-language multilingual embeddings.
- Conservative assignment to existing choices using structured Gemini verification.
- Dimensionality reduction for discovery.
- Density-based discovery of new categories, including explicit preservation of noise.
- English and Arabic labels for accepted new categories.
- Addition of new code-list rows with values greater than `100`.
- Preservation of exact respondent source rows and answer columns for later review and output work.
- A web application for complete analyst review and approval.
- An interim terminal-based structured review and approval workflow until the web application is available.
- Automated tests with `pytest`.

## Out of Scope

- Translation of respondent answers.
- Editing the survey instrument itself.
- Manual data-cleaning tools beyond what is required to categorize the supplied workbook.
- Categories or workflow features not described in the six feature specifications.

## Workbook Contract

The supplied coding workbook defines three primary tabs for this application:

- `Survey` defines which questions require coding and supplies their bilingual question text.
- `Code` is the existing choice and generated-category dictionary. There is no separate `Choices` tab.
- `Data` contains the raw respondent records and original free-text answers.

Other workbook tabs are outside the current extraction contract. They are not primary extraction sources and must be preserved unchanged unless their existing workbook formulas update them automatically.

### Question Identity and Metadata

The relevant `Survey` headers are:

```text
type | name | label:english | label:arabic
```

- A supported "Other" question is identified by a `Code.list_name` whose matching Survey metadata is found through ordered deterministic normalization for the `Survey.name` lookup only. A trailing `_other` is removed to target the parent question. For a trailing `_exp`, the exact Code ID is preferred and the ID without `_exp` is a fallback because either shape occurs in supported workbooks. For each base, its exact spelling is preferred and a variant with an underscore inserted between an ASCII letter and terminal digits is a fallback. The first existing candidate is selected; no candidate is an error. The original Code list name remains the exact `Data` answer-column identifier.
- `Code.list_name` is the primary question/choice-list key, with values such as `B2_other` and `B5_other`.
- The matching normalized `Survey.name` supplies the bilingual question metadata. The original `Code.list_name` remains the exact answer-column header in `Data`.
- `Survey.label:english` is the English question text.
- `Survey.label:arabic` is the Arabic question text.
- When one Survey label is blank or whitespace-only, ingestion uses the other
  label for both language fields. If both are blank, the workbook is invalid.

`Survey` rows that do not match the normalized `Code.list_name` values are not extracted as coding questions.

### Existing Choices and New Categories

The `Code` sheet requires these columns:

```text
list_name | value | label:english | label:arabic
```

Additional headers on any supported sheet are ignored. Required headers remain
validated. No coding-destination sheet or coding-triplet schema is required by
the current ingestion boundary.

- `list_name` is the primary key that groups choices and links them to `Survey.name` after applying the deterministic metadata-lookup normalization described above. No fuzzy matching is used.
- `value` is the stored numeric choice value.
- `label:english` is the English category label used for existing-choice review and later output work.
- `label:arabic` is the Arabic category label.
- When one Code label is blank or whitespace-only, ingestion uses the other
  label for both language fields. If both are blank, the workbook is invalid.
- The "Other" choice has value `-96` and is excluded as an existing semantic category.
- Generated categories are added to the matching question's reserved `Code` block, using the first available row in that block rather than being appended to an unrelated question or the global end of the sheet.

For example:

```text
B5_other | 101 | Lebanese | لبناني
```

### Respondent Answers and Coding Columns

`Data` starts with respondent metadata such as:

```text
KEY | enumerator_id | enumerator_name | enumerator_phone
```

The remaining supported answer columns are named with the exact question ID, such as `B5_other`. `KEY` is the stable respondent identifier.

The current ingestion boundary does not require a coding-destination sheet. For
each answer, it retains the exact `Data` source cell, respondent `KEY`, row,
and question ID. The later output destination is intentionally outside this
Feature 01 contract.

Fixed schema headers are matched case-insensitively (for example,
`Label:Arabic` matches `label:arabic`); dynamic question IDs remain
case-sensitive.

Blank and whitespace-only answers are skipped. Numeric answer cells are invalid; the application does not use Excel number formats to convert them to displayed text. Exact duplicate answer text is valid and expected. For later provider and computation stages, exact duplicates are processed once per question and their result is fanned out to every row-level answer record; every respondent `KEY` and row still receives its own mapped coding result. Hidden `Data` rows are processed like visible rows. Formula-based or merged respondent-answer cells in `Data` are outside the supported raw-data contract.

## Category Rules

- Existing survey choices are eligible targets, but the "Other" choice itself is excluded.
- Assignment to an existing choice must be conservative and structurally verified by Gemini.
- New categories must represent dense discovered meanings rather than forced assignments.
- Noise must remain identifiable and must not be silently absorbed into a category.
- Rare meanings must be retained rather than discarded merely because they are rare.
- New category values must be integers greater than `100`.
- Generated values must be unique across the entire workbook, not merely within one `list_name`.
- `101` is the conventional first candidate for the first generated category, but it is not a required fixed starting value.
- Allocation considers every existing workbook value greater than `100` and every value proposed in the current run, then selects an unused workbook-wide value.
- A duplicate generated value is a fatal validation error. The application must stop before workbook mutation and report the duplicated value plus the conflicting `Code` rows or proposed categories; it must not silently renumber after detecting the collision.
- New categories require an English label and an Arabic label.
- Nothing is written to `Code` or a respondent output destination until the analyst confirms the complete review.
- Noise, rare one-off meanings, rejected clusters, and uncertain existing-choice matches receive no automatic output value. Their source cells remain unchanged unless a later output contract explicitly assigns and approves a category during review.

The following category-discovery decisions are fixed:

- A cluster becomes a proposed new category only when it contains at least `3` distinct exact answer texts by default. This minimum is configurable. A cluster below the threshold remains represented as a rejected or rare cluster in the review evidence, and its members remain unresolved; it is not automatically labeled or coded.
- The system detects semantic overlap between separate clusters and proposes a merge for analyst confirmation. An approved merge produces one English label, one Arabic label, one workbook-wide value, and one combined member set.
- The destination for approved coding results is not defined by the current ingestion contract.

## Technical Stack

- Runtime: Python `>=3.13`
- Dependency and execution tool: `uv`
- CLI: standard-library `argparse`
- Workbook I/O: `openpyxl`
- Configuration: `tomllib` and `python-dotenv`
- HTTP: `httpx` for provider calls; the standard library downloader handles Google Sheets XLSX export.
- Vector calculations: NumPy
- Embeddings: Nebius Token Factory API using `Qwen/Qwen3-Embedding-8B`
- Embedding representation: `4096`-dimensional, `float32`, L2-normalized vectors stored as a memory map with a row map
- Dimensionality reduction: scikit-learn `PCA` or `IncrementalPCA`, default discovery dimension `50`
- Discovery: HDBSCAN-style density clustering with noise and membership probability
- Generation and verification: direct Google Gemini API using `gemini-3.5-flash`
- Review application: intentionally deferred until Feature 06 implementation; the web framework, browser UI approach, review-state storage, and local or hosted deployment model remain undecided for now.
- Tests: `pytest`

## Product Constraints

- Simplicity is the governing implementation principle.
- Implement only the behavior described by the six feature specifications.
- Do not create speculative extension points, frameworks, or single-use abstractions.
- Workbook writes must not corrupt unrelated sheets, cells, styles, formulas, or workbook structure.
- The relationship between each source answer and its workbook row must remain exact throughout embedding, clustering, and writing.
- Workbook mutation is prohibited until a complete structured analyst approval has been validated against the same analysis run and workbook.
- API secrets must come from environment configuration and must not be written into the workbook, logs, vector files, or source control.

## End-to-End Success

The project succeeds when a user can run `other-cluster` against a valid local workbook or accessible Google Sheets link and receive a valid output workbook in which:

- eligible answers have been conservatively assigned to existing or accepted new categories;
- accepted new categories appear in the code list with values greater than `100` and both English and Arabic labels;
- proposed new categories have received human review and explicit approval before final workbook output;
- every proposed existing-choice assignment and unresolved answer has also received an explicit analyst disposition;
- every generated value greater than `100` is unique across the entire workbook;
- each later output assignment remains tied to the exact respondent row captured during ingestion;
- uncertain answers, noise, and rare meanings follow a clearly defined policy rather than being forced into a category;
- all original-language text remains unchanged; and
- unrelated workbook content is preserved.

The exact web stack and the remaining open provider, discovery, labeling, and review contracts must be supplied before this outcome is fully testable.

## Feature Map

1. `01-workbook-ingestion-and-cli.md` — invoke the application and extract a stable workbook dataset.
2. `02-original-language-embeddings.md` — create and persist normalized multilingual vectors.
3. `03-existing-choice-assignment.md` — conservatively reuse existing choices.
4. `04-category-discovery.md` — reduce dimensions and discover dense new meanings without forcing noise.
5. `05-labeling-and-workbook-output.md` — label proposed groups, allocate globally unique codes, and prepare the review package and gated workbook changes.
6. `06-analyst-review-webapp.md` — review every result, capture complete structured approval, and authorize the final workbook write.
