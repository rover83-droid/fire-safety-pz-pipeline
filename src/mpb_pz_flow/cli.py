from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import corpus, io
from .assembler import assemble_draft, finalize_markdown
from .codex_native import (
    format_status_card,
    missing_for_agent,
    passport_brief,
    record_passport_answer,
    start_codex_project,
    status_card,
)
from .demo import create_demo
from .docx_export import export_docx
from .gui_server import main as gui_main
from .calculators import CALCULATORS
from .pipeline import (
    audit_binding_issues,
    audit_project,
    build_initial_matrix,
    compute_stage,
    init_project,
    refresh_stage,
    run_calculations,
)
from .validators import validate_all


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mpb-pz", description="MPB PZ artifact-first pipeline.")
    sub = parser.add_subparsers(required=True)

    init = sub.add_parser("init", help="Create a new project workspace.")
    init.add_argument("--project-dir", required=True, type=Path)
    init.add_argument("--fkp", required=True)
    init.add_argument("--section", required=True)
    init.add_argument("--object-name", required=True)
    init.add_argument("--description", default="")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_init)

    demo = sub.add_parser("demo", help="Create a complete demo project.")
    demo.add_argument("--project-dir", required=True, type=Path)
    demo.set_defaults(func=cmd_demo)

    status = sub.add_parser("status", help="Print current project stage.")
    status.add_argument("--project-dir", required=True, type=Path)
    status.set_defaults(func=cmd_status)

    sections = sub.add_parser("sections", help="List registered section artifact sets and their stages.")
    sections.add_argument("--project-dir", required=True, type=Path)
    sections.set_defaults(func=cmd_sections)

    validate = sub.add_parser("validate", help="Validate all currently available artifacts.")
    validate.add_argument("--project-dir", required=True, type=Path)
    validate.add_argument("--section", default=None)
    validate.add_argument("--strict", action="store_true", help="Fail on warnings too, not only on errors.")
    validate.set_defaults(func=cmd_validate)

    matrix = sub.add_parser("build-matrix", help="Create an initial matrix from norms.")
    matrix.add_argument("--project-dir", required=True, type=Path)
    matrix.add_argument("--section", default=None)
    matrix.set_defaults(func=cmd_build_matrix)

    assemble = sub.add_parser("assemble", help="Assemble draft.md from applicable matrix rows.")
    assemble.add_argument("--project-dir", required=True, type=Path)
    assemble.add_argument("--section", default=None)
    assemble.set_defaults(func=cmd_assemble)

    audit = sub.add_parser("audit", help="Run level 1 and level 2 audit (merges agent_findings.json if present).")
    audit.add_argument("--project-dir", required=True, type=Path)
    audit.add_argument("--section", default=None)
    audit.set_defaults(func=cmd_audit)

    gate = sub.add_parser("gate", help="Verify that the stored audit verdict is valid for the current artifacts.")
    gate.add_argument("--project-dir", required=True, type=Path)
    gate.add_argument("--section", default=None)
    gate.set_defaults(func=cmd_gate)

    finalize = sub.add_parser("finalize", help="Create final.md after successful audit.")
    finalize.add_argument("--project-dir", required=True, type=Path)
    finalize.add_argument("--section", default=None)
    finalize.set_defaults(func=cmd_finalize)

    docx = sub.add_parser("export-docx", help="Export final.docx (GOST styling) after successful audit/finalize.")
    docx.add_argument("--project-dir", required=True, type=Path)
    docx.add_argument("--section", default=None)
    docx.add_argument("--front-matter", action="store_true", help="Prepend auto-generated abbreviations and normative documents lists.")
    docx.add_argument("--no-title-page", action="store_true", help="Skip the title page.")
    docx.set_defaults(func=cmd_export_docx)

    matter = sub.add_parser("front-matter", help="Generate front_matter.md: abbreviations list + normative documents list.")
    matter.add_argument("--project-dir", required=True, type=Path)
    matter.add_argument("--section", default=None)
    matter.set_defaults(func=cmd_front_matter)

    calc_run = sub.add_parser("calc-run", help="Run applicable engineering calculators and write artifacts/calculations.json.")
    calc_run.add_argument("--project-dir", required=True, type=Path)
    calc_run.add_argument("--only", default=None, help="Run a single calculator by id.")
    calc_run.set_defaults(func=cmd_calc_run)

    calc_list = sub.add_parser("calc-list", help="List available engineering calculators.")
    calc_list.set_defaults(func=cmd_calc_list)

    corpus_add = sub.add_parser("corpus-add", help="Ingest a normative source: normalize encoding, hash, register in manifest.")
    corpus_add.add_argument("--project-dir", required=True, type=Path)
    corpus_add.add_argument("--file", required=True, type=Path, help="Source file (md/txt; utf-8, utf-16 or cp1251).")
    corpus_add.add_argument("--document", required=True, help='Document id, e.g. "СП 4.13130".')
    corpus_add.add_argument("--edition-year", required=True, type=int)
    corpus_add.add_argument("--title", default="")
    corpus_add.add_argument("--status", default="неизвестно", choices=corpus.DOCUMENT_STATUSES)
    corpus_add.add_argument("--doc-id", default=None)
    corpus_add.add_argument("--filename", default=None, help="Target name inside standards/ (default: <doc-id>.md).")
    corpus_add.set_defaults(func=cmd_corpus_add)

    corpus_list = sub.add_parser("corpus-list", help="List registered corpus documents.")
    corpus_list.add_argument("--project-dir", required=True, type=Path)
    corpus_list.set_defaults(func=cmd_corpus_list)

    corpus_verify = sub.add_parser("corpus-verify", help="Verify corpus files against the manifest (existence, hash, readability).")
    corpus_verify.add_argument("--project-dir", required=True, type=Path)
    corpus_verify.set_defaults(func=cmd_corpus_verify)

    gui = sub.add_parser("gui", help="Run the local browser GUI (deprecated; CLI/agent dialog is the supported interface).")
    gui.add_argument("--host", default="127.0.0.1")
    gui.add_argument("--port", type=int, default=8765)
    gui.set_defaults(func=cmd_gui)

    codex_start = sub.add_parser("codex-start", help="Start a Codex-native dialog project.")
    codex_start.add_argument("--project-dir", required=True, type=Path)
    codex_start.add_argument("--object-name", required=True)
    codex_start.add_argument("--section", default="Наружное ВПС и проезды")
    codex_start.add_argument("--fkp")
    codex_start.add_argument("--standards-dir", default="standards")
    codex_start.add_argument("--description", default="")
    codex_start.set_defaults(func=cmd_codex_start)

    codex_status = sub.add_parser("codex-status", help="Print the Codex-native status card.")
    codex_status.add_argument("--project-dir", required=True, type=Path)
    codex_status.set_defaults(func=cmd_codex_status)

    codex_answer = sub.add_parser("codex-answer", help="Save an answer to the current passport question.")
    codex_answer.add_argument("--project-dir", required=True, type=Path)
    codex_answer.add_argument("--value", required=True)
    codex_answer.add_argument("--field")
    codex_answer.set_defaults(func=cmd_codex_answer)

    codex_passport = sub.add_parser("codex-passport", help="Print a concise passport summary.")
    codex_passport.add_argument("--project-dir", required=True, type=Path)
    codex_passport.set_defaults(func=cmd_codex_passport)

    codex_missing = sub.add_parser("codex-missing", help="Show blockers for an agent.")
    codex_missing.add_argument("--project-dir", required=True, type=Path)
    codex_missing.add_argument("--agent", type=int, choices=(1, 2, 3), required=True)
    codex_missing.set_defaults(func=cmd_codex_missing)
    return parser


def cmd_init(args: argparse.Namespace) -> int:
    state = init_project(args.project_dir, args.fkp, args.section, args.object_name, args.description, force=args.force)
    print(f"Created project: {args.project_dir}")
    print(f"Stage: {state.stage.value}")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    create_demo(args.project_dir)
    print(f"Demo project created: {args.project_dir}")
    cmd_status(args)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    state = refresh_stage(args.project_dir)
    print(f"Object: {state.object_name}")
    print(f"FKP: {state.fkp}")
    print(f"Section: {state.section}")
    print(f"Stage: {state.stage.value}")
    return 0


def cmd_sections(args: argparse.Namespace) -> int:
    state = io.read_state(args.project_dir)
    index = io.read_section_index(args.project_dir)
    listed: dict[str, str] = {}
    listed[io.section_slug(args.project_dir, state.section)] = state.section
    listed.update(index)
    for slug, section in listed.items():
        stage = compute_stage(args.project_dir, section)
        active = " (активная)" if section == state.section else ""
        print(f"{slug}: {section}{active} -> {stage.value}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    issues = validate_all(args.project_dir, args.section)
    if not issues:
        print("Validation passed.")
        return 0
    _print_issues(issues)
    if any(issue.severity == "error" for issue in issues):
        return 2
    return 2 if args.strict else 0


def cmd_build_matrix(args: argparse.Namespace) -> int:
    rows = build_initial_matrix(args.project_dir, args.section)
    print(f"Matrix rows written: {len(rows)}")
    return 0


def cmd_assemble(args: argparse.Namespace) -> int:
    draft = assemble_draft(args.project_dir, args.section)
    paths = io.artifact_paths(args.project_dir, args.section)
    print(f"Draft written: {paths.draft}")
    print(f"Paragraphs: {draft.count('[Тип ')}")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    from .routing import ROUTE_LABELS

    report = audit_project(args.project_dir, args.section)
    print(report["verdict"])
    if report["passed"]:
        return 0

    print(f"Итерация правок: {report['iteration']} из {report['max_iterations']}")
    summary = report.get("routing_summary", {})
    parts = [f"{ROUTE_LABELS[route]}: {count}" for route, count in summary.items() if count]
    if parts:
        print("Маршрутизация находок -> " + "; ".join(parts))

    for level in ("level_1", "level_2"):
        for issue in report[level]:
            print(f"{level}: [{issue['route']}] [{issue['source']}/{issue['code']}] {issue['artifact']} - {issue['message']}")

    if report.get("escalation_required"):
        print()
        print("ЭСКАЛАЦИЯ: лимит итераций правок исчерпан. Конвейер не закрывается автоматически.")
        persistent = report.get("persistent_findings", [])
        if persistent:
            print("Не закрыты после всех итераций: " + ", ".join(persistent))
        for entry in report.get("iteration_history", []):
            print(f"  итерация {entry['iteration']}: {len(entry['error_codes'])} код(ов) ошибок")
    return 2


def cmd_gate(args: argparse.Namespace) -> int:
    problems = audit_binding_issues(args.project_dir, args.section)
    issues = validate_all(args.project_dir, args.section)
    errors = [issue for issue in issues if issue.severity == "error"]
    if not problems and not errors:
        print("КОНВЕЙЕР ЗАВЕРШЁН")
        print("Вердикт аудита действителен: артефакты не менялись после аудита.")
        return 0
    print("ВЕРНУТЬ НА ПРАВКУ")
    for problem in problems:
        print(f"- {problem}")
    _print_issues(errors)
    return 2


def cmd_finalize(args: argparse.Namespace) -> int:
    finalize_markdown(args.project_dir, args.section)
    paths = io.artifact_paths(args.project_dir, args.section)
    print(f"Final Markdown written: {paths.final_md}")
    return 0


def cmd_export_docx(args: argparse.Namespace) -> int:
    paths = io.artifact_paths(args.project_dir, args.section)
    if not paths.final_md.exists():
        finalize_markdown(args.project_dir, args.section)
    output = export_docx(
        args.project_dir,
        args.section,
        title_page=not args.no_title_page,
        front_matter=args.front_matter,
    )
    print(f"DOCX written: {output}")
    return 0


def cmd_front_matter(args: argparse.Namespace) -> int:
    from .front_matter import build_front_matter, unknown_abbreviations, write_front_matter

    target = write_front_matter(args.project_dir, args.section)
    content = build_front_matter(args.project_dir, args.section)
    print(f"Front matter written: {target}")
    if not content.strip():
        print("Внимание: обвязка пуста (нет принятых редакций и употреблённых сокращений).")

    paths = io.artifact_paths(args.project_dir, args.section)
    source = paths.final_md if paths.final_md.exists() else paths.draft
    if source.exists():
        unknown = unknown_abbreviations(source.read_text(encoding="utf-8"))
        if unknown:
            print("Сокращения без расшифровки в словаре (дополните standards.ABBREVIATIONS): " + ", ".join(unknown))
    return 0


def cmd_calc_run(args: argparse.Namespace) -> int:
    registry = run_calculations(args.project_dir, only=args.only)
    results = registry["results"]
    skipped = registry["skipped"]
    print(f"Выполнено расчетов: {len(results)}; пропущено: {len(skipped)}")
    for result in results:
        unit = f" {result['unit']}".rstrip()
        print(f"- {result['title']}: {result['value']}{unit} ({result['basis']})")
        print(f"  {result['formula']}")
    for skip in skipped:
        print(f"- ПРОПУЩЕН {skip['title']}: {skip['reason']}")
    return 0


def cmd_calc_list(args: argparse.Namespace) -> int:
    for calc_id, (title, _func) in CALCULATORS.items():
        print(f"{calc_id}: {title}")
    return 0


def cmd_corpus_add(args: argparse.Namespace) -> int:
    entry = corpus.ingest_file(
        args.project_dir,
        args.file,
        document=args.document,
        edition_year=args.edition_year,
        title=args.title,
        status=args.status,
        doc_id=args.doc_id,
        filename=args.filename,
    )
    print(f"Зарегистрирован: {entry.doc_id} -> standards/{entry.file}")
    print(f"Документ: {entry.document} ({entry.edition_year}), статус: {entry.status}")
    print(f"SHA-256: {entry.sha256}")
    return 0


def cmd_corpus_list(args: argparse.Namespace) -> int:
    documents = corpus.read_manifest(args.project_dir)
    if not documents:
        print("Корпус пуст: standards/manifest.json отсутствует или не содержит документов.")
        return 0
    for doc in documents:
        title = f" — {doc.title}" if doc.title else ""
        print(f"{doc.doc_id}: {doc.document} ({doc.edition_year}), статус: {doc.status}, файл: {doc.file}{title}")
    return 0


def cmd_corpus_verify(args: argparse.Namespace) -> int:
    issues = corpus.verify_corpus(args.project_dir)
    if not issues:
        documents = corpus.read_manifest(args.project_dir)
        print(f"Корпус целостен: {len(documents)} документ(ов) соответствуют манифесту.")
        return 0
    _print_issues(issues)
    return 2


def cmd_gui(args: argparse.Namespace) -> int:
    return gui_main(["--host", args.host, "--port", str(args.port)])


def cmd_codex_start(args: argparse.Namespace) -> int:
    result = start_codex_project(
        args.project_dir,
        object_name=args.object_name,
        fkp=args.fkp,
        section=args.section,
        standards_dir=args.standards_dir,
        description=args.description,
    )
    print(format_status_card(result["status_card"]))
    if result.get("next_question"):
        print()
        print(f"Следующий вопрос: {result['next_question']}")
    return 0


def cmd_codex_status(args: argparse.Namespace) -> int:
    print(format_status_card(status_card(args.project_dir)))
    return 0


def cmd_codex_answer(args: argparse.Namespace) -> int:
    result = record_passport_answer(args.project_dir, args.value, args.field)
    print(f"Сохранено: {result['saved_field']}")
    print()
    print(format_status_card(result["status_card"]))
    if result.get("next_question"):
        print()
        print(f"Следующий вопрос: {result['next_question']}")
    return 0


def cmd_codex_passport(args: argparse.Namespace) -> int:
    for row in passport_brief(args.project_dir):
        print(row)
    return 0


def cmd_codex_missing(args: argparse.Namespace) -> int:
    blockers = missing_for_agent(args.project_dir, args.agent)
    if not blockers:
        print(f"Агент {args.agent} может быть запущен.")
        return 0
    print(f"Агент {args.agent} пока не запускается:")
    for blocker in blockers:
        print(f"- {blocker}")
    return 2


def _print_issues(issues: list[object]) -> None:
    for issue in issues:
        print(f"[{issue.severity}] {issue.artifact}: {issue.code}: {issue.message}")


if __name__ == "__main__":
    raise SystemExit(main())
