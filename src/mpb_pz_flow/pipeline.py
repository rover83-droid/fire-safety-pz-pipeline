from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import calculators, corpus, io, routing, triggers
from .models import MatrixEntry, ProjectState, Stage, ValidationIssue
from .standards import FKP_TABLE
from .style import validate_lacunae, validate_paragraph_types, validate_section_content, validate_style
from .validators import (
    validate_decisions,
    validate_draft,
    validate_editions,
    validate_matrix,
    validate_norms,
    validate_numbers,
    validate_passport,
    validate_quotes,
    validate_triggers,
    validate_volume_structure,
)

AUDIT_ENGINE = "mpb-pz-flow.audit_project"
AGENT_FINDING_LEVELS = ("level_1", "level_2")
MAX_AUDIT_ITERATIONS = 3
AUDIT_LOOP_FILE = "audit_loop.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_project(project_dir: Path, fkp: str, section: str, object_name: str, description: str = "", force: bool = False) -> ProjectState:
    if fkp not in FKP_TABLE:
        raise ValueError(f"Unsupported FKP: {fkp}. Expected one of: {', '.join(FKP_TABLE)}")
    if project_dir.exists() and not force:
        raise FileExistsError(f"Project already exists: {project_dir}. Use force=True to reinitialize it.")
    if project_dir.exists() and force:
        _clear_project(project_dir)

    project_dir.mkdir(parents=True, exist_ok=True)
    artifacts = io.artifact_dir(project_dir)
    artifacts.mkdir(parents=True, exist_ok=True)

    state = ProjectState(
        version=1,
        stage=Stage.FKP_DETECTED,
        fkp=fkp,
        section=section,
        object_name=object_name,
        last_updated=now_iso(),
        notes=[description] if description else [],
    )
    io.write_state(project_dir, state)
    _write_initial_passport(artifacts, fkp, object_name, description)
    _write_initial_decisions(artifacts)
    return state


def compute_stage(project_dir: Path, section: str | None = None) -> Stage:
    paths = io.artifact_paths(project_dir, section)

    stage = Stage.FKP_DETECTED
    if _errors_only(validate_passport(project_dir) + validate_decisions(project_dir)):
        return stage
    stage = Stage.PASSPORT_READY
    norm_issues = validate_norms(project_dir, paths.section)
    if not _errors_only(norm_issues):
        norm_issues = norm_issues + validate_quotes(project_dir, paths.section)
        norm_issues = norm_issues + validate_editions(project_dir, paths.section)
        norm_issues = norm_issues + corpus.verify_corpus(project_dir)
    if _errors_only(norm_issues):
        return stage
    stage = Stage.NORMS_EXTRACTED
    if _errors_only(validate_matrix(project_dir, paths.section) + validate_triggers(project_dir, paths.section)):
        return stage
    stage = Stage.MATRIX_READY
    draft_issues = (
        validate_draft(project_dir, paths.section)
        + validate_numbers(project_dir, paths.section)
        + validate_paragraph_types(project_dir, paths.section)
        + validate_style(project_dir, paths.section)
    )
    if _errors_only(draft_issues):
        return stage
    stage = Stage.DRAFT_READY
    if audit_binding_issues(project_dir, paths.section):
        return stage
    stage = Stage.AUDIT_PASSED
    if paths.final_docx.exists():
        stage = Stage.DOCX_READY
    return stage


def refresh_stage(project_dir: Path) -> ProjectState:
    state = io.read_state(project_dir)
    state.stage = compute_stage(project_dir, state.section)
    state.last_updated = now_iso()
    io.write_state(project_dir, state)
    return state


def build_initial_matrix(project_dir: Path, section: str | None = None) -> list[MatrixEntry]:
    paths = io.artifact_paths(project_dir, section)
    passport = io.read_json(paths.passport) if paths.passport.exists() else {}
    norms = io.read_norms(project_dir, section)
    rows: list[MatrixEntry] = []
    for norm in norms:
        proposal = triggers.propose_status(norm, passport)
        if proposal is not None:
            status, basis = proposal
            if status == "требует инженерной проверки" and "отсутств" not in basis.lower():
                basis = f"Отсутствуют данные для вычисления применимости: {basis}"
        else:
            status = "требует инженерной проверки"
            basis = (
                f"Применимость требования {norm.document}, {norm.point} требует дополнительной "
                f"инженерной проверки: отсутствует подтвержденное сопоставление с параметром "
                f"'{norm.trigger_parameter}'."
            )
        rows.append(
            MatrixEntry(
                norm_id=norm.norm_id,
                document_point=f"{norm.document}.{norm.edition_year}, {norm.point}",
                status=status,
                passport_basis=basis,
                numeric_thresholds="",
                collisions=norm.collision_with or "",
                text_parameters="",
            )
        )
    io.write_matrix(project_dir, rows, section)
    return rows


def run_calculations(project_dir: Path, only: str | None = None) -> dict[str, object]:
    """Выполняет уместные калькуляторы и пишет реестр расчётов (единственный писатель)."""
    state = io.read_state(project_dir)
    paths = io.artifact_paths(project_dir)
    passport = io.read_json(paths.passport) if paths.passport.exists() else {}
    results, skipped = calculators.run_applicable(passport, state.fkp, only=only)
    registry = {
        "engine": calculators.CALC_ENGINE,
        "fkp": state.fkp,
        "results": [result.to_dict() for result in results],
        "skipped": skipped,
        "generated_at": now_iso(),
    }
    io.write_json(paths.calculations, registry)
    return registry


def artifact_hashes(paths: io.ArtifactPaths) -> dict[str, str | None]:
    """Hashes of every input the audit verdict depends on.

    A stored verdict is only valid while all of these match the files on disk.
    """
    manifest = corpus.manifest_path(paths.project_dir)
    return {
        paths.rel(paths.passport): io.sha256_path(paths.passport),
        paths.rel(paths.decisions): io.sha256_path(paths.decisions),
        paths.rel(paths.calculations): io.sha256_path(paths.calculations),
        paths.rel(paths.norms): io.sha256_path(paths.norms),
        paths.rel(paths.matrix): io.sha256_path(paths.matrix),
        paths.rel(paths.draft): io.sha256_path(paths.draft),
        paths.rel(paths.agent_findings): io.sha256_path(paths.agent_findings),
        f"{corpus.STANDARDS_DIRNAME}/{corpus.MANIFEST_FILE}": io.sha256_path(manifest),
    }


def audit_binding_issues(project_dir: Path, section: str | None = None) -> list[str]:
    """Why the stored audit verdict cannot be trusted right now. Empty list = trusted pass."""
    paths = io.artifact_paths(project_dir, section)
    if not paths.audit_report.exists():
        return ["audit_report.json отсутствует."]
    try:
        report = io.read_json(paths.audit_report)
    except (json.JSONDecodeError, OSError):
        return ["audit_report.json не читается."]
    if report.get("engine") != AUDIT_ENGINE:
        return ["Отчёт аудита создан не конвейером (нет подписи engine); перезапустите аудит через CLI."]
    if not report.get("passed"):
        return ["Аудит не пройден."]
    recorded = report.get("artifact_hashes")
    if not isinstance(recorded, dict):
        return ["В отчёте аудита нет привязки к артефактам (artifact_hashes)."]
    current = artifact_hashes(paths)
    problems: list[str] = []
    for name, current_hash in current.items():
        recorded_hash = recorded.get(name)
        if recorded_hash != current_hash:
            problems.append(f"Артефакт изменён после аудита: {name}.")
    for name in recorded:
        if name not in current:
            problems.append(f"Отчёт аудита ссылается на неизвестный артефакт: {name}.")
    return problems


def audit_is_valid(project_dir: Path, section: str | None = None) -> bool:
    return not audit_binding_issues(project_dir, section)


def audit_project(project_dir: Path, section: str | None = None) -> dict[str, object]:
    paths = io.artifact_paths(project_dir, section)

    level_1 = []
    level_1.extend(validate_passport(project_dir))
    level_1.extend(validate_decisions(project_dir))
    level_1.extend(corpus.verify_corpus(project_dir))
    level_1.extend(validate_norms(project_dir, paths.section))
    if not _errors_only(level_1):
        level_1.extend(validate_quotes(project_dir, paths.section))
        level_1.extend(validate_editions(project_dir, paths.section))
    level_1.extend(validate_matrix(project_dir, paths.section))
    level_1.extend(validate_triggers(project_dir, paths.section))

    level_2: list[ValidationIssue] = []
    if not _errors_only(level_1):
        level_2.extend(validate_draft(project_dir, paths.section))
        level_2.extend(validate_numbers(project_dir, paths.section))
        level_2.extend(validate_paragraph_types(project_dir, paths.section))
        level_2.extend(validate_style(project_dir, paths.section))
        level_2.extend(validate_section_content(project_dir, paths.section))
        level_2.extend(validate_lacunae(project_dir, paths.section))
        level_2.extend(validate_volume_structure(project_dir, paths.section))

    agent_level_1, agent_level_2 = _load_agent_findings(paths)
    level_1.extend(agent_level_1)
    level_2.extend(agent_level_2)

    passed = not _errors_only(level_1 + level_2)
    error_codes = sorted({issue.code for issue in _errors_only(level_1 + level_2)})
    report: dict[str, Any] = {
        "engine": AUDIT_ENGINE,
        "section": paths.section,
        "section_slug": paths.slug,
        "passed": passed,
        "level_1": [_issue_to_dict(issue) for issue in level_1],
        "level_2": [_issue_to_dict(issue) for issue in level_2],
        "verdict": "КОНВЕЙЕР ЗАВЕРШЁН" if passed else "ВЕРНУТЬ НА ПРАВКУ",
        "routing_summary": routing.routing_summary(error_codes),
        "artifact_hashes": artifact_hashes(paths),
        "generated_at": now_iso(),
    }

    loop = _update_audit_loop(paths, report, error_codes)
    report["iteration"] = loop["iteration"]
    report["max_iterations"] = MAX_AUDIT_ITERATIONS
    report["escalation_required"] = loop["escalated"]
    if loop["escalated"]:
        report["verdict"] = "ЭСКАЛАЦИЯ ПОЛЬЗОВАТЕЛЮ"
        report["persistent_findings"] = loop["persistent_findings"]
        report["iteration_history"] = loop["history"]

    _archive_previous_audit(paths)
    io.write_json(paths.audit_report, report)

    state = io.read_state(project_dir)
    if paths.section == state.section:
        state.stage = compute_stage(project_dir, state.section)
        state.last_updated = now_iso()
        io.write_state(project_dir, state)

    return report


def audit_loop_path(paths: io.ArtifactPaths) -> Path:
    return paths.root / AUDIT_LOOP_FILE


def read_audit_loop(project_dir: Path, section: str | None = None) -> dict[str, Any]:
    path = audit_loop_path(io.artifact_paths(project_dir, section))
    if not path.exists():
        return {"iteration": 0, "history": [], "escalated": False, "last_hashes": None}
    try:
        return io.read_json(path)
    except (json.JSONDecodeError, OSError):
        return {"iteration": 0, "history": [], "escalated": False, "last_hashes": None}


def _update_audit_loop(paths: io.ArtifactPaths, report: dict[str, Any], error_codes: list[str]) -> dict[str, Any]:
    """Счётчик итераций правок (методология: максимум 3, затем эскалация).

    Повторный прогон без изменения артефактов — та же попытка, итерация не
    тратится. Успешный аудит закрывает петлю.
    """
    state = read_audit_loop(paths.project_dir, paths.section)
    current_hashes = report["artifact_hashes"]

    if report["passed"]:
        state = {
            "iteration": 0,
            "history": [],
            "escalated": False,
            "last_hashes": current_hashes,
            "closed_at": report["generated_at"],
            "last_result": "passed",
        }
        io.write_json(audit_loop_path(paths), state)
        state["persistent_findings"] = []
        return state

    same_attempt = state.get("last_hashes") == current_hashes and state.get("last_result") == "failed"
    history = list(state.get("history", []))
    record = {
        "iteration": state.get("iteration", 0) if same_attempt else state.get("iteration", 0) + 1,
        "generated_at": report["generated_at"],
        "error_codes": error_codes,
        "routing_summary": routing.routing_summary(error_codes),
    }
    if same_attempt and history:
        history[-1] = record
    else:
        history.append(record)

    iteration = record["iteration"]
    escalated = iteration >= MAX_AUDIT_ITERATIONS
    persistent: list[str] = []
    if escalated:
        recent = history[-MAX_AUDIT_ITERATIONS:]
        persistent = sorted(set.intersection(*(set(entry["error_codes"]) for entry in recent)))

    state = {
        "iteration": iteration,
        "history": history,
        "escalated": escalated,
        "last_hashes": current_hashes,
        "last_result": "failed",
    }
    io.write_json(audit_loop_path(paths), state)
    state["persistent_findings"] = persistent
    return state


def _load_agent_findings(paths: io.ArtifactPaths) -> tuple[list[ValidationIssue], list[ValidationIssue]]:
    """Agent auditors contribute findings only through agent_findings.json.

    The file is the structured channel: agents never write audit_report.json.
    A malformed file is itself a blocking finding, never a silent pass.
    """
    label = paths.rel(paths.agent_findings)
    if not paths.agent_findings.exists():
        return [], []
    try:
        data = io.read_json(paths.agent_findings)
    except (json.JSONDecodeError, OSError) as exc:
        return [ValidationIssue("agent_findings.invalid", f"agent_findings.json не читается: {exc}.", label, source="agent")], []
    if not isinstance(data, dict):
        return [ValidationIssue("agent_findings.invalid", "agent_findings.json должен быть JSON-объектом с ключами level_1/level_2.", label, source="agent")], []

    parsed: dict[str, list[ValidationIssue]] = {level: [] for level in AGENT_FINDING_LEVELS}
    for level in AGENT_FINDING_LEVELS:
        entries = data.get(level, [])
        if not isinstance(entries, list):
            parsed["level_1"].append(
                ValidationIssue("agent_findings.invalid", f"Поле {level} должно быть списком находок.", label, source="agent")
            )
            continue
        for position, entry in enumerate(entries):
            issue = _parse_agent_finding(entry, position, level, label)
            parsed[level].append(issue)
    return parsed["level_1"], parsed["level_2"]


def _parse_agent_finding(entry: object, position: int, level: str, label: str) -> ValidationIssue:
    if not isinstance(entry, dict) or not str(entry.get("message", "")).strip():
        return ValidationIssue(
            "agent_findings.invalid",
            f"{level}[{position}] должен быть объектом с непустым полем message.",
            label,
            source="agent",
        )
    severity = str(entry.get("severity", "error"))
    if severity not in ("error", "warning"):
        severity = "error"
    return ValidationIssue(
        code=str(entry.get("code", "agent.finding")),
        message=str(entry["message"]),
        artifact=str(entry.get("artifact", label)),
        severity=severity,  # type: ignore[arg-type]
        source="agent",
    )


def _write_initial_passport(artifacts: Path, fkp: str, object_name: str, description: str) -> None:
    fkp_info = FKP_TABLE[fkp]
    passport = {
        "object_name": object_name,
        "description": description,
        "confirmed": {
            "functional_fire_hazard_class": fkp,
            "functional_fire_hazard_basis": fkp_info["basis"],
        },
        "clarifying": {},
        "missing": {},
    }
    io.write_json(artifacts / "passport.json", passport)


def _write_initial_decisions(artifacts: Path) -> None:
    decisions = {
        "standard_editions": [],
        "collisions": [],
        "assumptions": [],
        "system_algorithms": [],
    }
    io.write_json(artifacts / "decisions.json", decisions)


def _errors_only(issues: list[ValidationIssue]) -> list[ValidationIssue]:
    return [issue for issue in issues if issue.severity == "error"]


def _issue_to_dict(issue: ValidationIssue) -> dict[str, str]:
    return {
        "code": issue.code,
        "message": issue.message,
        "artifact": issue.artifact,
        "severity": issue.severity,
        "source": issue.source,
        "route": routing.route_code(issue.code),
    }


def _archive_previous_audit(paths: io.ArtifactPaths) -> None:
    if not paths.audit_report.exists():
        return

    history = paths.audit_history
    history.mkdir(parents=True, exist_ok=True)
    try:
        previous = io.read_json(paths.audit_report)
        stamp = str(previous.get("generated_at") or now_iso()).replace(":", "-")
    except (json.JSONDecodeError, OSError):
        stamp = now_iso().replace(":", "-")
    target = history / f"audit_report_{stamp}.json"
    try:
        shutil.copy2(paths.audit_report, target)
    except OSError:
        return


def _clear_project(project_dir: Path) -> None:
    root = project_dir.resolve()
    for child in project_dir.iterdir():
        resolved = child.resolve()
        if root not in resolved.parents:
            raise ValueError(f"Refusing to remove path outside project: {child}")
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
