"""Качество производственного текста ПЗ: грамматики типов абзацев,
стилевой линтер, полнота секций, жизненный цикл лакун.

Эталон стиля — ВНИИПО: констатирующий залог («принято», «предусмотрено»),
конкретные реквизиты норм, решения вместо намерений.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import corpus, io
from .models import ValidationIssue
from .standards import SECTION_REQUIREMENTS
from .volume_structure import flattened_sections, structure_for_fkp

# Число с единицей измерения (используется также валидатором провенанса чисел).
UNIT_NUMBER_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*"
    r"(тыс\.?\s*м3|м3|м2|км|мм|см|л/с|мин|часа|часов|час|чел|кВт|МВт|кг|шт\.?|м|ч|т)(?![а-яa-z0-9])",
    re.IGNORECASE,
)

PARAGRAPH_TYPE_RE = re.compile(r"^\[Тип ([АБВГ])\]\s+")

# Формулы типов абзацев.
_REFERENCE_RE = re.compile(r"в соответствии с|по требованию|согласно (?:СП|ГОСТ|СНиП|ФЗ)", re.IGNORECASE)
_DECISION_RE = re.compile(
    r"\b(принят|принято|принята|приняты|принимается|принимаются|"
    r"предусмотрен|предусмотрено|предусмотрена|предусмотрены|предусматривается|предусматриваются|"
    r"обеспечивается|обеспечиваются|выполняется|выполняются|"
    r"запроектирован|запроектировано|запроектированы|"
    r"применяется|применяются|устанавливается|устанавливаются|"
    r"составляет|составляют|определен|определена|определено|определены)",
    re.IGNORECASE,
)
_NEGATION_RE = re.compile(
    r"не\s+(подлежит|требуется|требуются|предусматривается|предусматриваются|"
    r"нормируется|нормируются|распространяется|устраивается|устраиваются)|"
    r"отсутствует необходимость",
    re.IGNORECASE,
)
_SYSTEM_RE = re.compile(r"\b(систем|установк|алгоритм|сигнал|оборудовани|автоматик)", re.IGNORECASE)
_CALC_RE = re.compile(r"\b(расчет|расчёт|принят|составляет|определен|равен|равна|равно)|=|→", re.IGNORECASE)

# Стилевой линтер.
_FUTURE_RE = re.compile(r"\b(будет|будут|планируется|планируются|предполагается|намечается|намечаются)\b", re.IGNORECASE)
_VAGUE_RE = re.compile(
    r"согласно требованиям норм|в соответствии с требованиями норм|"
    r"согласно действующим нормам|в соответствии с действующими нормами|"
    r"согласно нормативным документам",
    re.IGNORECASE,
)
_DOC_ID_RE = re.compile(r"\b(?:СП|ГОСТ|СНиП)\s*\d|ФЗ\s*-?\s*\d|№\s*123-ФЗ")
_SP_BARE_RE = re.compile(r"\bСП\b(?![\s.]*\d)")
# «СП 8.13130» без года редакции (за номером не следует .ГГГГ).
_SP_NO_YEAR_RE = re.compile(r"\bСП\s*\d+\.\d{4,5}(?!\.\d{4})\b")

# Лакуны.
_LACUNA_PHRASE_RE = re.compile(
    r"отсутству\w*\s+в\s+(?:проектной|нормативной)\s+базе|источник[^.]{0,80}отсутству", re.IGNORECASE
)
_DOC_MENTION_RE = re.compile(r"\b(СП|ГОСТ|СНиП)\s*(\d+\.\d+)")
_RESOLVED_STATUSES = {"resolved", "closed", "снята", "закрыта", "устранена"}


def validate_paragraph_types(project_dir: Path, section: str | None = None) -> list[ValidationIssue]:
    """Абзац обязан соответствовать формуле своего типа.

    А — решение по норме («в соответствии с … принято/предусмотрено»);
    Б — отрицательное решение (требование не распространяется/не требуется);
    В — системное решение (система/установка/алгоритм с параметрами);
    Г — расчёт (число с единицей + расчётная лексика).
    """
    paths = io.artifact_paths(project_dir, section)
    label = paths.rel(paths.draft)
    if not paths.draft.exists():
        return []

    issues: list[ValidationIssue] = []
    paragraph_number = 0
    for block in _paragraphs(paths.draft.read_text(encoding="utf-8")):
        if block.startswith("#") or block.startswith("|") or block.startswith("<!--"):
            continue
        paragraph_number += 1
        match = PARAGRAPH_TYPE_RE.match(block)
        if not match:
            continue  # отсутствие маркера ловит validate_draft
        paragraph_type = match.group(1)
        problem = _type_problem(paragraph_type, block)
        if problem:
            issues.append(
                ValidationIssue(
                    "draft.type_grammar",
                    f"Абзац {paragraph_number} [Тип {paragraph_type}]: {problem}",
                    label,
                )
            )
    return issues


def _type_problem(paragraph_type: str, block: str) -> str | None:
    if paragraph_type == "А":
        if not _REFERENCE_RE.search(block):
            return "нет конструкции «в соответствии с …» (привязка решения к норме)."
        if not _DECISION_RE.search(block):
            return "нет глагола проектного решения (принято/предусмотрено/обеспечивается…)."
        return None
    if paragraph_type == "Б":
        if not _NEGATION_RE.search(block):
            return "нет отрицательной конструкции (не подлежит/не требуется/не нормируется…)."
        return None
    if paragraph_type == "В":
        if not _SYSTEM_RE.search(block):
            return "нет предмета системного решения (система/установка/алгоритм/оборудование)."
        return None
    # Г — расчётный абзац
    if not UNIT_NUMBER_RE.search(block):
        return "расчётный абзац не содержит числа с единицей измерения."
    if not _CALC_RE.search(block):
        return "нет расчётной лексики (расчет/принят/составляет/=)."
    return None


def validate_style(project_dir: Path, section: str | None = None) -> list[ValidationIssue]:
    """Производственный стиль: решения, а не намерения; реквизиты, а не «нормы вообще»."""
    paths = io.artifact_paths(project_dir, section)
    label = paths.rel(paths.draft)
    if not paths.draft.exists():
        return []

    issues: list[ValidationIssue] = []
    paragraph_number = 0
    for block in _paragraphs(paths.draft.read_text(encoding="utf-8")):
        if block.startswith("#") or block.startswith("|") or block.startswith("<!--"):
            continue
        paragraph_number += 1

        future = _FUTURE_RE.search(block)
        if future:
            issues.append(
                ValidationIssue(
                    "draft.style_future",
                    f"Абзац {paragraph_number}: «{future.group(0)}» — намерение вместо решения; "
                    "используйте констатирующий залог (предусмотрено/принято).",
                    label,
                )
            )

        vague = _VAGUE_RE.search(block)
        if vague:
            severity = "warning" if _DOC_ID_RE.search(block) else "error"
            issues.append(
                ValidationIssue(
                    "draft.style_vague_citation",
                    f"Абзац {paragraph_number}: «{vague.group(0)}» — ссылка без конкретного документа; "
                    "укажите документ, год редакции и пункт.",
                    label,
                    severity=severity,
                )
            )

        if _SP_BARE_RE.search(block):
            issues.append(
                ValidationIssue(
                    "draft.style_sp_without_number",
                    f"Абзац {paragraph_number}: «СП» без номера документа.",
                    label,
                )
            )

        for match in _SP_NO_YEAR_RE.finditer(block):
            issues.append(
                ValidationIssue(
                    "draft.style_missing_edition_year",
                    f"Абзац {paragraph_number}: «{match.group(0)}» упомянут без года редакции.",
                    label,
                    severity="warning",
                )
            )
    return issues


def validate_section_content(project_dir: Path, section: str | None = None) -> list[ValidationIssue]:
    """Обязательное содержание раздела присутствует в тексте (тематический контроль).

    Warning, а не error: формулировки тем могут законно отличаться, но пропуск
    обязательной темы должен быть виден в протоколе аудита.
    """
    paths = io.artifact_paths(project_dir, section)
    label = paths.rel(paths.draft)
    if not paths.draft.exists():
        return []

    text = _normalize(paths.draft.read_text(encoding="utf-8"))
    issues: list[ValidationIssue] = []

    requirements = SECTION_REQUIREMENTS.get(paths.section)
    if requirements:
        issues.extend(_missing_topics(requirements, text, paths.section, label))

    state = io.read_state(project_dir)
    sections = structure_for_fkp(state.fkp)
    if sections and _is_full_volume(paths.section, text):
        for volume_section in flattened_sections(sections):
            issues.extend(
                _missing_topics(
                    list(volume_section.required_content),
                    text,
                    f"{volume_section.number} {volume_section.title}",
                    label,
                )
            )
    return issues


def _missing_topics(requirements: list[str], normalized_text: str, scope: str, label: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for requirement in requirements:
        variants = [_normalize(variant) for variant in requirement.split("|")]
        if any(variant and variant in normalized_text for variant in variants):
            continue
        issues.append(
            ValidationIssue(
                "draft.section_content_missing",
                f"Раздел «{scope}»: не раскрыта обязательная тема «{requirement}».",
                label,
                severity="warning",
            )
        )
    return issues


def validate_lacunae(project_dir: Path, section: str | None = None) -> list[ValidationIssue]:
    """Устаревшие лакуны: источник уже зарегистрирован в корпусе,
    а журнал/текст всё ещё заявляет его отсутствие."""
    registered = {doc.document for doc in corpus.read_manifest(project_dir)}
    if not registered:
        return []

    issues: list[ValidationIssue] = []
    paths = io.artifact_paths(project_dir, section)

    if paths.decisions.exists():
        decisions = io.read_json(paths.decisions)
        for index, entry in enumerate(decisions.get("lacunae", [])):
            if not isinstance(entry, dict):
                continue
            if str(entry.get("status", "")).strip().lower() in _RESOLVED_STATUSES:
                continue
            entry_text = str(entry)
            for prefix, number in _DOC_MENTION_RE.findall(entry_text):
                document = f"{prefix} {number}"
                if document in registered:
                    issues.append(
                        ValidationIssue(
                            "decisions.lacuna_stale",
                            f"lacunae[{index}]: {document} уже зарегистрирован в корпусе — "
                            "актуализируйте лакуну (переизвлеките нормы или закройте запись).",
                            "decisions.json",
                            severity="warning",
                        )
                    )
                    break

    if paths.draft.exists():
        label = paths.rel(paths.draft)
        paragraph_number = 0
        for block in _paragraphs(paths.draft.read_text(encoding="utf-8")):
            if block.startswith("#") or block.startswith("|") or block.startswith("<!--"):
                continue
            paragraph_number += 1
            # Точка — граница предложения только перед пробелом/концом строки,
            # иначе резались бы номера документов вида «СП 4.13130».
            for sentence in re.split(r";|\.(?=\s|$)", block):
                if not _LACUNA_PHRASE_RE.search(sentence):
                    continue
                for prefix, number in _DOC_MENTION_RE.findall(sentence):
                    document = f"{prefix} {number}"
                    if document in registered:
                        issues.append(
                            ValidationIssue(
                                "draft.lacuna_stale",
                                f"Абзац {paragraph_number}: заявлено отсутствие источника {document}, "
                                "но он зарегистрирован в корпусе — текст устарел.",
                                label,
                                severity="warning",
                            )
                        )
                        break
    return issues


def _paragraphs(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").strip()
    if not normalized:
        return []
    return [block.strip() for block in re.split(r"\n\s*\n", normalized) if block.strip()]


def _normalize(text: str) -> str:
    text = text.lower().replace("ё", "е")
    return re.sub(r"\s+", " ", text)


def _is_full_volume(section: str, normalized_text: str) -> bool:
    lowered = section.lower()
    return (
        "том 9" in lowered
        or "мероприятия по обеспечению пожарной безопасности" in lowered
        or "<!-- volume_structure: f5.1 -->" in normalized_text
    )
