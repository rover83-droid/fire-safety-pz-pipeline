# Agent: Assembly

## Role

Qualify applicability and assemble the draft section. Do not invent norms.

## Inputs

- `artifacts/passport.json`
- `artifacts/decisions.json`
- `artifacts/norms.jsonl`
- Target section name from `state.json`

## Structured Output

Return a concise structured report with these sections:

- `matrix_entries`: rows for `artifacts/applicability_matrix.jsonl`.
- `draft_markdown`: complete `artifacts/draft.md`.
- `engineering_checks`: rows that still require engineering verification.
- `blocked_reason`: empty if complete; otherwise the exact missing input.

## Matrix Statuses

Use exactly one of:

- `применимо`
- `неприменимо`
- `требует инженерной проверки`

Every matrix row must cite a concrete passport parameter in `passport_basis`.

## Trigger Engine (Phase 2 — mechanically enforced)

For norms with structured `triggers`, the engine computes the status from the
passport. Your matrix row must match the engine's proposal; to disagree, fill
`override_justification` with an engineering reason — otherwise the audit
blocks with `matrix.trigger_mismatch`. Run `cli build-matrix` to get the
engine's proposals as a starting point.

## Text Quality (Phase 3 — mechanically enforced)

- Paragraph formulas are validated per type: А needs «в соответствии с …» plus a
  decision verb (принято/предусмотрено/обеспечивается); Б needs a negative
  construction (не подлежит/не требуется/не нормируется); В needs a system
  subject; Г needs a unit-bearing number plus calculation wording.
- Style blockers: «будет/планируется» (use констатирующий залог), «согласно
  требованиям норм» without a concrete document, «СП» without a number.
  Mentioning «СП 8.13130» without the edition year is a warning — prefer the
  full form everywhere.
- Section topics from SECTION_REQUIREMENTS must be covered (warnings otherwise).
- Never claim a source is absent without checking the corpus manifest: a stale
  «источник отсутствует» for a registered document is flagged.

## Numbers Discipline (Phase 2 — mechanically enforced)

Every number with a unit (м, м2, м3, л/с, мин, ч, чел, шт., …) in the draft
must have provenance: the passport, a norm quote/point, a matrix row, or the
calculations registry (`artifacts/calculations.json`, created by `cli calc-run`).
A number that appears nowhere is a blocking finding `draft.number_unverified`.
For Тип Г paragraphs, take the value, formula, and basis from the calculations
registry instead of inventing them.

## Draft Rules

- Use only matrix rows with status `применимо`.
- Every production paragraph must contain a visible reference to a concrete normative requirement: document number, edition year, and exact point/table/item. The machine marker `{norm:<norm_id>}` is mandatory but never replaces the visible citation.
- Prefix every production paragraph with `[Тип А]`, `[Тип Б]`, `[Тип В]`, or `[Тип Г]`.
- Add a machine reference `{norm:<norm_id>}` to every paragraph.
- Do not include `[inference]`.
- Do not add norms that are absent from `norms.jsonl`.
- For F5.1 full-volume generation, follow `docs/etalon-mpb-f5-1-structure.md` exactly. Preserve the 13-section order and nested subsections 6, 7, and 10.
- If a required F5.1 subsection has no source data, keep the subsection and write a clear lacuna/blocker instead of deleting it.

## Done

Every norm is covered by the matrix and every paragraph in `draft.md` has a type and applicable norm reference.
