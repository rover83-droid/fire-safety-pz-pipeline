# Architecture

`mpb-pz-flow` separates agent reasoning from pipeline control.

## Layers

| Layer | Responsibility |
|---|---|
| Agent prompts | Domain reasoning and artifact authoring |
| Artifacts | Durable source of truth between phases |
| Validators | Mechanical gates that prevent phase skipping |
| CLI | State transitions and local execution |
| Exporters | Final Markdown/DOCX output |

## Why This Shape

Fire-safety explanatory notes are compliance artifacts. The system therefore optimizes for traceability:

- every object parameter belongs in the passport;
- every norm enters through a verified norm table;
- every applicability decision is recorded in the matrix;
- every draft paragraph points back to an applicable norm.

## MVP Boundary

The first implementation covers a complete demo path and one production-ready section skeleton. Next iterations should add local PDF/DOCX norm extraction, richer DOCX tables, and section-specific assemblers.

