from __future__ import annotations

import json
import re
from pathlib import Path

from . import corpus, io, triggers
from .models import MatrixEntry, NormEntry, ValidationIssue
from .standards import required_fields_for_fkp
from .style import (
    UNIT_NUMBER_RE,
    validate_lacunae,
    validate_paragraph_types,
    validate_section_content,
    validate_style,
)
from .volume_structure import flattened_sections, structure_for_fkp

VALID_STATUSES = {"применимо", "неприменимо", "требует инженерной проверки"}
PARAGRAPH_TYPE_RE = re.compile(r"^\[Тип [АБВГ]\]\s+")
NORM_REF_RE = re.compile(r"\{norm:([^}]+)\}")
NUMBER_TOKEN_RE = re.compile(r"\d+(?:[.,]\d+)?")


def validate_passport(project_dir: Path) -> list[ValidationIssue]:
    state = io.read_state(project_dir)
    path = io.artifact_dir(project_dir) / "passport.json"
    if not path.exists():
        return [ValidationIssue("passport.missing", "passport.json is missing.", "passport.json")]

    data = io.read_json(path)
    issues: list[ValidationIssue] = []
    for section in ("confirmed", "clarifying", "missing"):
        if section not in data or not isinstance(data[section], dict):
            issues.append(ValidationIssue("passport.section", f"Passport section '{section}' must be an object.", "passport.json"))

    confirmed = data.get("confirmed", {})
    missing = data.get("missing", {})
    for field in required_fields_for_fkp(state.fkp):
        if field in confirmed:
            continue
        missing_info = missing.get(field)
        if isinstance(missing_info, dict) and missing_info.get("criticality") == "noncritical":
            continue
        issues.append(
            ValidationIssue(
                "passport.required",
                f"Required passport field is not confirmed or marked noncritical: {field}.",
                "passport.json",
            )
        )
    return issues


def validate_decisions(project_dir: Path) -> list[ValidationIssue]:
    path = io.artifact_dir(project_dir) / "decisions.json"
    if not path.exists():
        return [ValidationIssue("decisions.missing", "decisions.json is missing.", "decisions.json")]

    data = io.read_json(path)
    editions = data.get("standard_editions", [])
    if not editions:
        return [ValidationIssue("decisions.editions", "At least one accepted standard edition is required.", "decisions.json")]
    for index, edition in enumerate(editions):
        if not edition.get("document") or not edition.get("edition_year"):
            return [
                ValidationIssue(
                    "decisions.edition_format",
                    f"standard_editions[{index}] must include document and edition_year.",
                    "decisions.json",
                )
            ]
    return []


def validate_norms(project_dir: Path, section: str | None = None) -> list[ValidationIssue]:
    paths = io.artifact_paths(project_dir, section)
    label = paths.rel(paths.norms)
    if not paths.norms.exists():
        return [ValidationIssue("norms.missing", f"{label} is missing.", label)]

    issues: list[ValidationIssue] = []
    seen: set[str] = set()
    for norm in io.read_norms(project_dir, section):
        issues.extend(_validate_norm(norm, seen, project_dir, label))
        seen.add(norm.norm_id)
    if not seen:
        issues.append(ValidationIssue("norms.empty", "At least one norm entry is required.", label))
    return issues


def _validate_norm(norm: NormEntry, seen: set[str], project_dir: Path, label: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if norm.norm_id in seen:
        issues.append(ValidationIssue("norms.duplicate_id", f"Duplicate norm_id: {norm.norm_id}.", label))
    required = {
        "document": norm.document,
        "edition_year": str(norm.edition_year),
        "point": norm.point,
        "quote": norm.quote,
        "subject": norm.subject,
        "trigger_parameter": norm.trigger_parameter,
        "source_file": norm.source_file,
    }
    for field, value in required.items():
        if not value.strip():
            issues.append(ValidationIssue("norms.required", f"Norm {norm.norm_id} has empty field: {field}.", label))
    if len(norm.quote.strip()) < 20:
        issues.append(ValidationIssue("norms.quote_too_short", f"Norm {norm.norm_id} quote is too short.", label))
    if norm.edition_year < 1900:
        issues.append(ValidationIssue("norms.edition_year", f"Norm {norm.norm_id} has invalid edition year.", label))
    source = Path(norm.source_file)
    project_source = project_dir / norm.source_file
    if norm.source_file.strip() and not source.exists() and not project_source.exists():
        issues.append(
            ValidationIssue(
                "norms.source_file_missing",
                f"Norm {norm.norm_id} source file is not found: {norm.source_file}.",
                label,
                severity="warning",
            )
        )
    return issues


def validate_quotes(project_dir: Path, section: str | None = None) -> list[ValidationIssue]:
    """Каждая цитата нормы обязана быть найдена в её локальном источнике.

    Отсутствующий источник остаётся warning'ом validate_norms; здесь ловятся
    случаи, когда источник есть, но заявленного текста в нём нет — главный
    механизм против галлюцинированных цитат.
    """
    paths = io.artifact_paths(project_dir, section)
    label = paths.rel(paths.norms)
    issues: list[ValidationIssue] = []
    for norm in io.read_norms(project_dir, section):
        source = corpus.resolve_source(project_dir, norm)
        if source is None:
            continue
        try:
            normalized = corpus.read_source_normalized(source)
        except corpus.CorpusError as exc:
            issues.append(
                ValidationIssue(
                    "norms.source_unreadable",
                    f"Норма {norm.norm_id}: источник {source.name} не читается: {exc}",
                    label,
                )
            )
            continue
        if not corpus.quote_matches(normalized, norm.quote):
            issues.append(
                ValidationIssue(
                    "norms.quote_unverified",
                    f"Норма {norm.norm_id}: цитата не найдена в источнике {source.name} "
                    f"({norm.document}.{norm.edition_year}, {norm.point}). Сверьте текст с документом.",
                    label,
                )
            )
    return issues


def validate_editions(project_dir: Path, section: str | None = None) -> list[ValidationIssue]:
    """Контроль редакций: одна редакция на документ, каждая цитируемая пара
    (документ, год) принята в журнале решений, коллизии норм имеют решение."""
    paths = io.artifact_paths(project_dir, section)
    norms_label = paths.rel(paths.norms)
    decisions_path = io.artifact_dir(project_dir) / "decisions.json"
    if not decisions_path.exists():
        return []

    decisions = io.read_json(decisions_path)
    issues: list[ValidationIssue] = []

    accepted: dict[str, set[int]] = {}
    for edition in decisions.get("standard_editions", []):
        document = str(edition.get("document", "")).strip()
        year = edition.get("edition_year")
        if not document or not year:
            continue
        accepted.setdefault(document, set()).add(int(year))
    for document, years in sorted(accepted.items()):
        if len(years) > 1:
            issues.append(
                ValidationIssue(
                    "decisions.duplicate_edition",
                    f"В журнале решений принято несколько редакций одного документа: {document} "
                    f"({', '.join(str(year) for year in sorted(years))}). Оставьте одну редакцию.",
                    "decisions.json",
                )
            )

    collisions = [entry for entry in decisions.get("collisions", []) if isinstance(entry, dict)]
    for norm in io.read_norms(project_dir, section):
        if norm.edition_year not in accepted.get(norm.document, set()):
            issues.append(
                ValidationIssue(
                    "norms.edition_not_accepted",
                    f"Норма {norm.norm_id} цитирует {norm.document} ({norm.edition_year}), "
                    "но эта редакция не принята в decisions.standard_editions.",
                    norms_label,
                )
            )
        if norm.collision_with and norm.collision_with.strip():
            if not _collision_resolved(norm, collisions):
                issues.append(
                    ValidationIssue(
                        "decisions.collision_unresolved",
                        f"Норма {norm.norm_id} заявляет коллизию с «{norm.collision_with}», "
                        "но в decisions.collisions нет записи с непустым полем resolution, "
                        "упоминающей эту норму или её документ.",
                        "decisions.json",
                    )
                )
    return issues


def _collision_resolved(norm: NormEntry, collisions: list[dict]) -> bool:
    for entry in collisions:
        if not str(entry.get("resolution", "")).strip():
            continue
        entry_text = str(entry).lower()
        if norm.norm_id.lower() in entry_text or norm.document.lower() in entry_text:
            return True
    return False


def validate_matrix(project_dir: Path, section: str | None = None) -> list[ValidationIssue]:
    paths = io.artifact_paths(project_dir, section)
    label = paths.rel(paths.matrix)
    if not paths.matrix.exists():
        return [ValidationIssue("matrix.missing", f"{label} is missing.", label)]

    norms = {norm.norm_id: norm for norm in io.read_norms(project_dir, section)}
    rows = io.read_matrix(project_dir, section)
    row_ids = {row.norm_id for row in rows}
    issues: list[ValidationIssue] = []

    for norm_id in sorted(set(norms) - row_ids):
        issues.append(ValidationIssue("matrix.coverage", f"Norm {norm_id} is not covered by matrix.", label))
    for row in rows:
        issues.extend(_validate_matrix_row(row, norms, label))
    return issues


def _validate_matrix_row(row: MatrixEntry, norms: dict[str, NormEntry], label: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if row.norm_id not in norms:
        issues.append(ValidationIssue("matrix.unknown_norm", f"Matrix references unknown norm_id: {row.norm_id}.", label))
    if row.status not in VALID_STATUSES:
        issues.append(ValidationIssue("matrix.status", f"Invalid status for {row.norm_id}: {row.status}.", label))
    if not row.passport_basis.strip():
        issues.append(ValidationIssue("matrix.passport_basis", f"Matrix row {row.norm_id} lacks passport basis.", label))
    if row.status == "требует инженерной проверки" and "отсутств" not in row.passport_basis.lower():
        issues.append(
            ValidationIssue(
                "matrix.engineering_check_reason",
                f"Engineering-check row {row.norm_id} must name the missing parameter.",
                label,
            )
        )
    return issues


def validate_triggers(project_dir: Path, section: str | None = None) -> list[ValidationIssue]:
    """Статус матрицы обязан совпадать с предложением триггер-движка
    либо нести записанное обоснование переопределения."""
    paths = io.artifact_paths(project_dir, section)
    norms_label = paths.rel(paths.norms)
    matrix_label = paths.rel(paths.matrix)
    if not paths.passport.exists():
        return []
    passport = io.read_json(paths.passport)

    issues: list[ValidationIssue] = []
    norms_by_id: dict[str, NormEntry] = {}
    for norm in io.read_norms(project_dir, section):
        norms_by_id[norm.norm_id] = norm
        for index, trigger in enumerate(norm.triggers or []):
            problem = triggers.validate_trigger_spec(trigger)
            if problem:
                issues.append(
                    ValidationIssue(
                        "norms.trigger_invalid",
                        f"Норма {norm.norm_id}, triggers[{index}]: {problem}.",
                        norms_label,
                    )
                )

    if not paths.matrix.exists():
        return issues

    for row in io.read_matrix(project_dir, section):
        norm = norms_by_id.get(row.norm_id)
        if norm is None or not norm.triggers:
            continue
        proposal = triggers.propose_status(norm, passport)
        if proposal is None:
            continue
        proposed_status, explanation = proposal
        if row.status == proposed_status:
            continue
        if row.override_justification.strip():
            issues.append(
                ValidationIssue(
                    "matrix.trigger_override",
                    f"Строка {row.norm_id}: статус «{row.status}» переопределяет предложение движка "
                    f"«{proposed_status}» ({explanation}). Обоснование: {row.override_justification}",
                    matrix_label,
                    severity="warning",
                )
            )
        else:
            issues.append(
                ValidationIssue(
                    "matrix.trigger_mismatch",
                    f"Строка {row.norm_id}: статус «{row.status}» противоречит вычисленному по паспорту "
                    f"«{proposed_status}» ({explanation}). Исправьте статус или добавьте override_justification.",
                    matrix_label,
                )
            )
    return issues


def validate_numbers(project_dir: Path, section: str | None = None) -> list[ValidationIssue]:
    """Каждое число с единицей измерения в черновике обязано иметь провенанс:
    паспорт, цитаты/пункты норм, матрица, реестр расчётов или журнал решений."""
    paths = io.artifact_paths(project_dir, section)
    label = paths.rel(paths.draft)
    if not paths.draft.exists():
        return []

    pool = _provenance_pool(project_dir, section, paths)
    issues: list[ValidationIssue] = []
    paragraph_number = 0
    for block in _paragraphs(paths.draft.read_text(encoding="utf-8")):
        if block.startswith("#") or block.startswith("|") or block.startswith("<!--"):
            continue
        paragraph_number += 1
        for match in UNIT_NUMBER_RE.finditer(block):
            token = match.group(1)
            canonical = _canonical_number(token)
            if canonical in pool:
                continue
            issues.append(
                ValidationIssue(
                    "draft.number_unverified",
                    f"Абзац {paragraph_number}: число «{match.group(0).strip()}» не имеет провенанса "
                    "(нет ни в паспорте, ни в цитатах норм, ни в матрице, ни в реестре расчётов).",
                    label,
                )
            )
    return issues


def _provenance_pool(project_dir: Path, section: str | None, paths: io.ArtifactPaths) -> set[str]:
    texts: list[str] = []
    if paths.passport.exists():
        texts.append(json.dumps(io.read_json(paths.passport), ensure_ascii=False))
    if paths.decisions.exists():
        texts.append(json.dumps(io.read_json(paths.decisions), ensure_ascii=False))
    if paths.calculations.exists():
        texts.append(json.dumps(io.read_json(paths.calculations), ensure_ascii=False))
    for norm in io.read_norms(project_dir, section):
        texts.append(json.dumps(norm.to_dict(), ensure_ascii=False))
    for row in io.read_matrix(project_dir, section):
        texts.append(json.dumps(row.to_dict(), ensure_ascii=False))

    pool: set[str] = set()
    for text in texts:
        for token in NUMBER_TOKEN_RE.findall(text):
            pool.add(_canonical_number(token))
    return pool


def _canonical_number(token: str) -> str:
    normalized = token.replace(",", ".")
    try:
        value = float(normalized)
    except ValueError:
        return normalized
    if value == int(value):
        return str(int(value))
    return repr(value)


def validate_draft(project_dir: Path, section: str | None = None) -> list[ValidationIssue]:
    paths = io.artifact_paths(project_dir, section)
    label = paths.rel(paths.draft)
    if not paths.draft.exists():
        return [ValidationIssue("draft.missing", f"{label} is missing.", label)]

    applicable_norms = {row.norm_id for row in io.read_matrix(project_dir, section) if row.status == "применимо"}
    norms_by_id = {norm.norm_id: norm for norm in io.read_norms(project_dir, section)}
    text = paths.draft.read_text(encoding="utf-8")
    issues: list[ValidationIssue] = []
    paragraph_number = 0

    for block in _paragraphs(text):
        if block.startswith("#") or block.startswith("|") or block.startswith("<!--"):
            continue
        paragraph_number += 1
        if not PARAGRAPH_TYPE_RE.search(block):
            issues.append(ValidationIssue("draft.paragraph_type", f"Paragraph {paragraph_number} lacks [Тип А/Б/В/Г].", label))
        refs = NORM_REF_RE.findall(block)
        if not refs:
            issues.append(ValidationIssue("draft.norm_ref", f"Paragraph {paragraph_number} has no {{norm:...}} reference.", label))
        for ref in refs:
            if ref not in norms_by_id:
                issues.append(ValidationIssue("draft.unknown_norm", f"Paragraph {paragraph_number} references unknown norm {ref}.", label))
            elif ref not in applicable_norms:
                issues.append(ValidationIssue("draft.non_applicable_norm", f"Paragraph {paragraph_number} uses non-applicable norm {ref}.", label))
            elif not _has_visible_norm_reference(block, norms_by_id[ref]):
                issues.append(
                    ValidationIssue(
                        "draft.visible_norm_reference",
                        f"Paragraph {paragraph_number} references norm {ref} internally but lacks visible document/year/point citation.",
                        label,
                    )
                )
        if "[inference]" in block:
            issues.append(ValidationIssue("draft.inference", f"Paragraph {paragraph_number} contains [inference].", label))
    return issues


def validate_volume_structure(project_dir: Path, section: str | None = None) -> list[ValidationIssue]:
    state = io.read_state(project_dir)
    sections = structure_for_fkp(state.fkp)
    if not sections:
        return []

    paths = io.artifact_paths(project_dir, section)
    label = paths.rel(paths.draft)
    if not paths.draft.exists():
        return []

    text = paths.draft.read_text(encoding="utf-8")
    if not _is_full_volume_draft(paths.section, text):
        return []

    normalized = _normalize_heading_text(text)
    issues: list[ValidationIssue] = []
    position = 0
    for volume_section in flattened_sections(sections):
        title = _normalize_heading_text(volume_section.title)
        found = normalized.find(title, position)
        if found == -1:
            issues.append(
                ValidationIssue(
                    "volume_structure.missing_section",
                    f"F5.1 volume structure is missing section: {volume_section.number} {volume_section.title}.",
                    label,
                )
            )
            continue
        if found < position:
            issues.append(
                ValidationIssue(
                    "volume_structure.order",
                    f"F5.1 section is out of order: {volume_section.number} {volume_section.title}.",
                    label,
                )
            )
        position = found
    return issues


def validate_all(project_dir: Path, section: str | None = None) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    issues.extend(validate_passport(project_dir))
    issues.extend(validate_decisions(project_dir))
    issues.extend(corpus.verify_corpus(project_dir))
    issues.extend(validate_norms(project_dir, section))
    if not _has_blocking_errors(issues, io.NORMS_FILE):
        issues.extend(validate_quotes(project_dir, section))
        issues.extend(validate_editions(project_dir, section))
        issues.extend(validate_matrix(project_dir, section))
        issues.extend(validate_triggers(project_dir, section))
    if not _has_blocking_errors(issues, io.MATRIX_FILE):
        issues.extend(validate_draft(project_dir, section))
        issues.extend(validate_numbers(project_dir, section))
        issues.extend(validate_paragraph_types(project_dir, section))
        issues.extend(validate_style(project_dir, section))
        issues.extend(validate_section_content(project_dir, section))
        issues.extend(validate_lacunae(project_dir, section))
        issues.extend(validate_volume_structure(project_dir, section))
    return issues


def _paragraphs(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").strip()
    if not normalized:
        return []
    return [block.strip() for block in re.split(r"\n\s*\n", normalized) if block.strip()]


def _is_full_volume_draft(section: str, text: str) -> bool:
    lowered = section.lower()
    return (
        "том 9" in lowered
        or "мероприятия по обеспечению пожарной безопасности" in lowered
        or "<!-- volume_structure: f5.1 -->" in text.lower()
    )


def _normalize_heading_text(text: str) -> str:
    text = text.lower().replace("ё", "е")
    text = re.sub(r"[*_#`\\]+", " ", text)
    text = re.sub(r"[^а-яa-z0-9.]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _has_visible_norm_reference(paragraph: str, norm: NormEntry) -> bool:
    normalized_paragraph = _normalize_heading_text(paragraph)
    document_year = _normalize_heading_text(f"{norm.document}.{norm.edition_year}")
    document_year_alt = _normalize_heading_text(f"{norm.document} {norm.edition_year}")
    point = _normalize_heading_text(norm.point)
    return (
        (document_year in normalized_paragraph or document_year_alt in normalized_paragraph)
        and point in normalized_paragraph
    )


def _has_blocking_errors(issues: list[ValidationIssue], artifact_suffix: str) -> bool:
    return any(issue.artifact.endswith(artifact_suffix) and issue.severity == "error" for issue in issues)
