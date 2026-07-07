from __future__ import annotations

import re
from pathlib import Path

from . import io
from .models import MatrixEntry, NormEntry
from .pipeline import audit_binding_issues
from .standards import SECTION_REQUIREMENTS
from .volume_structure import canon_label_for_fkp, structure_for_fkp

# Десятичная точка перед единицей измерения → запятая (русская техдокументация).
_DECIMAL_BEFORE_UNIT_RE = re.compile(
    r"(\d+)\.(\d+)(\s*(?:тыс\.?\s*м3|м3|м2|км|мм|см|л/с|мин|часа|часов|час|чел|кВт|МВт|кг|шт\.?|м|ч|т)(?![а-яa-z0-9]))"
)


def assemble_draft(project_dir: Path, section: str | None = None) -> str:
    state = io.read_state(project_dir)
    paths = io.artifact_paths(project_dir, section)
    passport = io.read_json(paths.passport)
    norms = {norm.norm_id: norm for norm in io.read_norms(project_dir, paths.section)}
    matrix = io.read_matrix(project_dir, paths.section)
    applicable = [row for row in matrix if row.status == "применимо"]

    lines: list[str] = [f"# {paths.section}", ""]
    if structure_for_fkp(state.fkp) and _is_full_volume_request(paths.section):
        lines.append(f"<!-- volume_structure: {canon_label_for_fkp(state.fkp)} -->")
        lines.append("")
    lines.extend(_tep_table(passport))
    lines.extend(_calc_table(paths))
    section_requirements = SECTION_REQUIREMENTS.get(paths.section, [])
    if section_requirements:
        lines.append("<!-- section_requirements: " + ", ".join(section_requirements) + " -->")
        lines.append("")

    for row in applicable:
        norm = norms[row.norm_id]
        lines.append(_paragraph_for(row, norm, passport))
        lines.append("")

    draft = "\n".join(lines).strip() + "\n"
    io.write_text(paths.draft, draft)
    return draft


def _is_full_volume_request(section: str) -> bool:
    lowered = section.lower()
    return "том 9" in lowered or "мероприятия по обеспечению пожарной безопасности" in lowered


def finalize_markdown(project_dir: Path, section: str | None = None) -> str:
    paths = io.artifact_paths(project_dir, section)
    problems = audit_binding_issues(project_dir, paths.section)
    if problems:
        raise RuntimeError(
            "final.md нельзя собрать: вердикт аудита недействителен. " + " ".join(problems)
        )
    final_text = _strip_machine_refs(paths.draft.read_text(encoding="utf-8"))
    io.write_text(paths.final_md, final_text)
    return final_text


def _tep_table(passport: dict[str, object]) -> list[str]:
    confirmed = passport.get("confirmed", {})
    if not isinstance(confirmed, dict):
        confirmed = {}
    rows = [
        ("Класс функциональной пожарной опасности", confirmed.get("functional_fire_hazard_class", "")),
        ("Степень огнестойкости", confirmed.get("fire_resistance_degree", "")),
        ("Класс конструктивной пожарной опасности", confirmed.get("structural_fire_hazard_class", "")),
        ("Этажность", confirmed.get("floors", "")),
        ("Высота здания, м", confirmed.get("height_m", "")),
        ("Строительный объем, м3", confirmed.get("building_volume_m3", "")),
    ]
    if not any(value not in ("", None) for _, value in rows):
        return []
    lines = [
        "## Технико-экономические показатели",
        "",
        "| Показатель | Значение |",
        "|---|---|",
    ]
    for name, value in rows:
        if value not in ("", None):
            lines.append(f"| {name} | {value} |")
    lines.append("")
    return lines


def _calc_table(paths: io.ArtifactPaths) -> list[str]:
    if not paths.calculations.exists():
        return []
    registry = io.read_json(paths.calculations)
    results = registry.get("results", [])
    if not results:
        return []
    lines = [
        "## Расчетные показатели",
        "",
        "| Показатель | Значение | Основание | Вывод |",
        "|---|---|---|---|",
    ]
    for result in results:
        unit = f" {result.get('unit', '')}".rstrip()
        lines.append(
            f"| {result.get('title', '')} | {result.get('value', '')}{unit} "
            f"| {result.get('basis', '')} | {result.get('formula', '')} |"
        )
    lines.append("")
    return lines


def _paragraph_for(row: MatrixEntry, norm: NormEntry, passport: dict[str, object]) -> str:
    subject = norm.subject.lower()
    reference = f"{norm.document}.{norm.edition_year}, {norm.point}"
    params = row.text_parameters.strip() or row.passport_basis.strip()

    if "расход" in subject or "формул" in subject:
        return f"[Тип Г] В соответствии с {reference} {params}. {{norm:{norm.norm_id}}}"
    if "исключ" in subject or "не подлежит" in params.lower():
        return f"[Тип Б] Объект не подлежит указанному мероприятию в соответствии с {reference} вследствие {params}. {{norm:{norm.norm_id}}}"
    if "алгоритм" in subject or "система" in subject:
        return f"[Тип В] Система проектируется в соответствии с {reference} с учетом следующих параметров: {params}. {{norm:{norm.norm_id}}}"
    return f"[Тип А] В соответствии с {reference} при характеристиках объекта ({row.passport_basis}) принято проектное решение: {params}. {{norm:{norm.norm_id}}}"


def _strip_machine_refs(text: str) -> str:
    cleaned_lines = []
    for line in text.splitlines():
        if line.startswith("<!-- section_requirements:"):
            continue
        line = line.replace("[Тип А] ", "").replace("[Тип Б] ", "").replace("[Тип В] ", "").replace("[Тип Г] ", "")
        while "{norm:" in line:
            start = line.find("{norm:")
            end = line.find("}", start)
            if end == -1:
                break
            line = line[:start].rstrip() + line[end + 1 :]
        line = _DECIMAL_BEFORE_UNIT_RE.sub(r"\1,\2\3", line)
        cleaned_lines.append(line.rstrip())
    return "\n".join(cleaned_lines).strip() + "\n"
