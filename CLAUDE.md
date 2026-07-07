# CLAUDE.md

This project is `mpb-pz-flow`: an artifact-first, Codex-native workflow for preparing Russian fire-safety explanatory note sections, especially Tome 9 "Мероприятия по обеспечению пожарной безопасности".

## How To Work

Use the repository instructions in this order:

1. Read `SKILL.md`.
2. Read `agents/orchestrator.md`.
3. Use the specialized agent prompts:
   - `agents/intelligence.md`
   - `agents/assembly.md`
   - `agents/audit.md`
4. For full-volume work, use `src/mpb_pz_flow/volume_structure.py` (`structure_for_fkp`): `docs/etalon-mpb-f5-1-structure.md` for FKP F5.1, `docs/etalon-generic-pp87-structure.md` (ПП87 §9 canon) for every other FKP.

The preferred interface is conversational. The user is a fire-safety engineer, not a programmer. Do not make them edit JSON or run terminal commands unless they explicitly ask.

## Core Invariants

- Normative requirements must come from local project files.
- Every norm used in a draft must exist in the section's `norms.jsonl`.
- Every matrix row must reference a concrete passport parameter.
- Every project decision paragraph must visibly cite a concrete normative source: document number, edition year, and exact point/table/item.
- Internal markers such as `{norm:<norm_id>}` are traceability aids only and do not satisfy the visible-citation requirement.
- Do not skip pipeline stages.
- Do not finalize DOCX unless audit passes.

## Integrity Contract (Phase 0)

- `audit_report.json` is written ONLY by `python -m mpb_pz_flow.cli audit`. The report stores SHA-256 hashes of passport, decisions, norms, matrix, draft, and agent findings; `refresh_stage` rejects any report without a valid binding (hand-written reports are void).
- Audit agents write findings to `agent_findings.json` (schema: `schemas/agent_findings.schema.json`), never to `audit_report.json`.
- Each section has its own artifact set under `artifacts/sections/<slug>/` (registered in `artifacts/sections/index.json`). The artifacts root serves only the active `state.section` as a legacy layout. Prefixed artifact files (`<section>_draft.md`) are forbidden.
- Completion is announced only after `cli gate` exits 0.

## Corpus Contract (Phase 1)

- Normative sources are registered via `cli corpus-add` into `projects/<name>/standards/manifest.json` (document, edition year, status, SHA-256). Encodings are normalized to UTF-8; corrupted exports are rejected at ingestion.
- Every norm `quote` is mechanically verified against its source (verbatim, `...` allowed for omissions, source order preserved). `norms.quote_unverified` blocks the stage machine and the audit.
- Every cited `(document, edition_year)` must be accepted in `decisions.standard_editions`; one edition per document; declared collisions require a `resolution` record.
- The supported interfaces are the Claude Code / Codex dialog and the CLI. The browser GUI is deprecated and frozen.

## Engineering Contract (Phase 2)

- Norms may carry machine-evaluable `triggers`; the engine proposes the matrix status from the passport. A status that contradicts the proposal without `override_justification` blocks the audit (`matrix.trigger_mismatch`).
- Engineering values come from `cli calc-run` → `artifacts/calculations.json` (value + formula + normative basis; part of the audit hash binding). `cli calc-list` shows available calculators; outside encoded table ranges they refuse instead of extrapolating.
- Every unit-bearing number in a draft must have provenance (passport / norm quotes / matrix / calculations registry) — `draft.number_unverified` blocks otherwise.
- `final.md` renders decimal commas before units (12,18 м), clause numbers untouched.

## Export Contract (Phase 5)

- `cli export-docx` renders GOST styling (Times New Roman, 25/10/20/20 mm, justified + 12.5 mm indent, black headings, table captions, title page, page numbers); `--front-matter` prepends auto-generated abbreviations and normative-documents lists.
- `cli front-matter` generates `front_matter.md`: abbreviations actually used in the text (dictionary: `standards.ABBREVIATIONS`) and the normative documents list built from `decisions.standard_editions` + corpus manifest (title, обязательный/добровольный status). Never hand-write these lists.

## Audit Loop Contract (Phase 4)

- Every audit finding carries `route`: `agent_1` (passport/norms/decisions/corpus), `agent_2` (matrix/draft/structure), or `orchestrator` (ambiguous cases). Dispatch findings only to their owners.
- Fix iterations are capped at 3 (`audit_loop.json`, written by the pipeline; reruns without artifact changes do not burn attempts). The third failed iteration yields verdict `ЭСКАЛАЦИЯ ПОЛЬЗОВАТЕЛЮ` with `persistent_findings` — present it to the user and stop.

## Text Quality Contract (Phase 3)

- Paragraph types А/Б/В/Г are validated against their formulas (`draft.type_grammar` blocks).
- Style blockers: future/intent wording («будет», «планируется»), vague citations («согласно требованиям норм» without a document), «СП» without a number. «СП X.XXXXX» without edition year is a warning.
- SECTION_REQUIREMENTS covers all 17 ПП-87 sections; missing mandatory topics are warnings (`draft.section_content_missing`), visible in the audit and failing `validate --strict`.
- Lacuna lifecycle: claims that a source is absent are cross-checked against the corpus manifest (`draft.lacuna_stale`, `decisions.lacuna_stale`).

## Main Commands For Testing

```powershell
$env:PYTHONPATH='src'
python -m unittest discover -s tests -v
python -m mpb_pz_flow.cli status --project-dir .\projects\demo
python -m mpb_pz_flow.cli codex-status --project-dir .\projects\demo
```

## Project Memory

Project state is stored under:

```text
projects/<project-name>/
  state.json
  conversation_state.json
  standards/
  artifacts/
```

Do not rely on chat history as project memory. Read the artifacts.

