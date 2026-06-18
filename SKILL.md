---
name: mpb-pz-flow
description: Use for generating and auditing Russian fire-safety explanatory note sections with a three-agent Codex workflow.
---

# MPB PZ Flow

This skill orchestrates a controlled pipeline for the project documentation section "Мероприятия по обеспечению пожарной безопасности".

## Primary Interface: Codex Dialog

The main workflow is a dialog inside Codex. The user should not need to edit JSON, run terminal commands, or operate the browser GUI for routine work.

Supported conversational commands:

- `Начать новый проект ПЗ МПБ`
- `Продолжить проект <имя>`
- `Покажи статус`
- `Покажи паспорт`
- `Что не хватает для запуска агента 1?`
- `Запусти агента 1`
- `Запусти агента 2`
- `Запусти аудит`
- `Собери финальный DOCX`

The orchestrator must answer with engineering summaries and short status cards, not raw artifact dumps.

## Core Rule

Normative clauses must come from local project sources and must be recorded in `artifacts/norms.jsonl` before they can appear in a draft.

Every project decision in the explanatory note must visibly cite a concrete normative requirement: document number, edition year, and exact point/table/item. Internal markers such as `{norm:<norm_id>}` are traceability aids only and do not satisfy the visible-citation requirement.

## Pipeline

1. Detect FKP.
2. Build `passport.json` and `decisions.json`.
3. Extract verified norms into `norms.jsonl`.
4. Qualify norms into `applicability_matrix.jsonl`.
5. Assemble `draft.md`.
6. Audit level 1 and level 2.
7. Finalize Markdown and optionally export DOCX.

## Integrity Rules (Phase 0)

- `audit_report.json` is produced only by `python -m mpb_pz_flow.cli audit`; it binds the verdict to SHA-256 hashes of the audited artifacts. Hand-written reports are rejected by the stage machine.
- Audit agents put findings into `agent_findings.json` of the section set; the CLI merges them with mechanical checks.
- Each section lives in `artifacts/sections/<slug>/` (see `artifacts/sections/index.json`); the artifacts root serves only the active section (legacy layout).
- `КОНВЕЙЕР ЗАВЕРШЁН` is announced only after `python -m mpb_pz_flow.cli gate` exits 0.

## Corpus Rules (Phase 1)

- Sources are registered via `cli corpus-add` (encoding normalization, SHA-256, status обязательный/добровольный) into `standards/manifest.json`.
- Every norm quote is mechanically verified against its registered source; paraphrases fail the audit (`norms.quote_unverified`).
- Every cited edition must be accepted in `decisions.standard_editions`; one edition per document; collisions require a recorded `resolution`.
- Interfaces: Claude Code / Codex dialog and CLI. The browser GUI is deprecated.

## Audit Loop Rules (Phase 4)

- Findings are routed: `agent_1` (нормы/паспорт/редакции/корпус), `agent_2` (матрица/текст/структура), `orchestrator` (неоднозначные).
- Maximum 3 fix iterations per section (`audit_loop.json`); the third failure escalates to the user with persistent findings. Never close the pipeline after escalation.

## Text Quality Rules (Phase 3)

- Paragraph formulas А/Б/В/Г are mechanically validated; style blockers: future tense, vague citations, «СП» without number.
- All 17 ПП-87 sections have mandatory topic lists; gaps are warnings in the audit protocol.
- Stale lacunae («источник отсутствует» for a corpus-registered document) are flagged automatically.

## Engineering Rules (Phase 2)

- Norms with structured `triggers` get their matrix status computed from the passport; overrides require `override_justification`.
- Engineering values come from `cli calc-run` (registry `artifacts/calculations.json` with formula + basis); unit-bearing numbers without provenance block the audit (`draft.number_unverified`).

## Codex-Native Orchestration

Use `agents/orchestrator.md` as the top-level behavior contract. The orchestrator owns stage control, one-question-at-a-time intake, and subagent dispatch.

For F5.1 full-volume work, use `docs/etalon-mpb-f5-1-structure.md` as the canonical structure of Tome 9. It was derived from the root file `эталон МПБ Ф5.1.md`.

Use real Codex subagents for:

- Agent 1: `agents/intelligence.md`
- Agent 2: `agents/assembly.md`
- Agent 3: `agents/audit.md`

Simple status checks and saving user answers may be handled directly by the orchestrator.

## Commands

Commands are auxiliary for testing and recovery. They are not the preferred user interface.

```powershell
python -m mpb_pz_flow.cli init --project-dir .\projects\shop --fkp F3.1 --section "Наружное ВПС и проезды" --object-name "Магазин"
python -m mpb_pz_flow.cli validate --project-dir .\projects\shop
python -m mpb_pz_flow.cli build-matrix --project-dir .\projects\shop
python -m mpb_pz_flow.cli assemble --project-dir .\projects\shop
python -m mpb_pz_flow.cli audit --project-dir .\projects\shop
```

## Agent Prompts

- `agents/intelligence.md`: passport, decision journal, norm extraction.
- `agents/assembly.md`: matrix and draft.
- `agents/audit.md`: level 1 and level 2 audit.
