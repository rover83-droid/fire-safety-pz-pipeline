"""Композиция норм по паттернам СП 1/2/4: общее → частное, область ФКП, границы применимости.

Не заменяет канон тома 9 (ПП87 / Ф5.1). Управляет отбором и порядком норм
внутри раздела пояснительной записки.
"""

from __future__ import annotations

import re
from typing import Any

from .models import (
    COMPOSITION_LAYERS,
    DEFAULT_COMPOSITION_LAYER,
    CompositionLayer,
    MatrixEntry,
    NormEntry,
    ValidationIssue,
)

_LAYER_ORDER: dict[str, int] = {name: index for index, name in enumerate(COMPOSITION_LAYERS)}

# Границы области применения серии 13130 (типичные исключения из §1 СП).
_RESIDENTIAL_HEIGHT_M = 75.0
_PUBLIC_HEIGHT_M = 50.0
_SPECIAL_OBJECT_TOKENS = (
    "военн",
    "метрополитен",
    "горн",
    "выработк",
    "взрывчат",
    "радиоактив",
    "ядерн",
)


def normalize_fkp(fkp: str) -> str:
    return str(fkp or "").strip().upper().replace("Ф", "F")


def fkp_family(fkp: str) -> str:
    normalized = normalize_fkp(fkp)
    if "." in normalized:
        return normalized.split(".", 1)[0]
    return normalized


def fkp_token_matches(token: str, fkp: str) -> bool:
    """Проверка одного токена fkp_scope против ФКП проекта."""
    raw = str(token or "").strip()
    if not raw or raw == "*":
        return True

    normalized = normalize_fkp(fkp)
    family = fkp_family(normalized)
    token_norm = raw.upper().replace("Ф", "F").replace(" ", "")

    if token_norm == normalized:
        return True
    if token_norm == family:
        return True

    # Диапазоны вида F1-F4 или F1–F4
    range_match = re.fullmatch(r"F([1-5])[-–]F([1-5])", token_norm)
    if range_match and family.startswith("F") and family[1:].isdigit():
        start = int(range_match.group(1))
        end = int(range_match.group(2))
        current = int(family[1:])
        low, high = (start, end) if start <= end else (end, start)
        return low <= current <= high

    # Семейства через запятую уже разнесены по элементам массива; здесь — одиночный токен.
    return False


def norm_in_scope(norm: NormEntry, fkp: str) -> bool:
    scope = norm.fkp_scope or ["*"]
    return any(fkp_token_matches(token, fkp) for token in scope)


def effective_composition_layer(norm: NormEntry) -> CompositionLayer:
    layer = norm.composition_layer or DEFAULT_COMPOSITION_LAYER
    if layer not in COMPOSITION_LAYERS:
        return DEFAULT_COMPOSITION_LAYER
    return layer  # type: ignore[return-value]


def sort_key_for_assembly(norm: NormEntry, index: int = 0) -> tuple[int, str, int]:
    """Ключ сортировки: слой → номер раздела источника → исходный индекс."""
    layer_rank = _LAYER_ORDER.get(effective_composition_layer(norm), 0)
    section = str(norm.source_section or "").strip()
    return (layer_rank, section, index)


def sort_matrix_rows_for_assembly(
    rows: list[MatrixEntry],
    norms_by_id: dict[str, NormEntry],
) -> list[MatrixEntry]:
    decorated: list[tuple[tuple[int, str, int], MatrixEntry]] = []
    for index, row in enumerate(rows):
        norm = norms_by_id.get(row.norm_id)
        if norm is None:
            decorated.append(((99, "", index), row))
        else:
            decorated.append((sort_key_for_assembly(norm, index), row))
    decorated.sort(key=lambda item: item[0])
    return [row for _, row in decorated]


def out_of_scope_basis(norm: NormEntry, fkp: str) -> str:
    scope = ", ".join(norm.fkp_scope) if norm.fkp_scope else "*"
    return (
        f"Норма {norm.document}, {norm.point} вне области ФКП проекта {normalize_fkp(fkp)} "
        f"(fkp_scope={scope})."
    )


def applicability_boundary_issues(passport: dict[str, Any], fkp: str = "") -> list[ValidationIssue]:
    """Границы применимости серии 13130: высотность и спецобъекты.

    Возвращает предупреждения/ошибки паспорта — не подменяет текст ПЗ.
    """
    confirmed = passport.get("confirmed", {})
    if not isinstance(confirmed, dict):
        confirmed = {}
    issues: list[ValidationIssue] = []

    project_fkp = normalize_fkp(fkp or str(confirmed.get("functional_fire_hazard_class", "")))
    family = fkp_family(project_fkp)
    height = _as_float(confirmed.get("height_m"))

    if height is not None:
        if family == "F1" and height > _RESIDENTIAL_HEIGHT_M:
            issues.append(
                ValidationIssue(
                    "passport.applicability_boundary",
                    f"Высота {height} м превышает типичную границу применения СП серии 13130 "
                    f"для жилых зданий ({_RESIDENTIAL_HEIGHT_M:g} м). Зафиксируйте СТУ/лакуну в decisions.",
                    "passport.json",
                )
            )
        if family in {"F2", "F3", "F4"} and height > _PUBLIC_HEIGHT_M:
            issues.append(
                ValidationIssue(
                    "passport.applicability_boundary",
                    f"Высота {height} м превышает типичную границу применения СП серии 13130 "
                    f"для общественных зданий ({_PUBLIC_HEIGHT_M:g} м). Зафиксируйте СТУ/лакуну в decisions.",
                    "passport.json",
                )
            )

    special = confirmed.get("special_object_type") or confirmed.get("special_purpose")
    blobs = [str(special or "")]
    for key in ("object_purpose", "description", "notes"):
        if key in confirmed:
            blobs.append(str(confirmed[key]))
    description = str(passport.get("description") or "")
    blobs.append(description)
    joined = " ".join(blobs).lower().replace("ё", "е")
    for token in _SPECIAL_OBJECT_TOKENS:
        if token in joined:
            issues.append(
                ValidationIssue(
                    "passport.applicability_boundary",
                    "Признаки спецобъекта (военное/метро/горные выработки/ВВ/РАО) выводят объект "
                    "за типичную область СП 1/2/4. Зафиксируйте основание применимости или лакуну.",
                    "passport.json",
                    severity="warning",
                )
            )
            break

    return issues


def validate_composition_layer_value(norm: NormEntry) -> ValidationIssue | None:
    layer = norm.composition_layer
    if layer not in COMPOSITION_LAYERS:
        return ValidationIssue(
            "norms.composition_layer_invalid",
            f"Норма {norm.norm_id}: composition_layer «{layer}» недопустим "
            f"(ожидается: {', '.join(COMPOSITION_LAYERS)}).",
            "norms.jsonl",
        )
    if not norm.fkp_scope:
        return ValidationIssue(
            "norms.fkp_scope_empty",
            f"Норма {norm.norm_id}: fkp_scope пуст (нужен хотя бы '*' или класс ФКП).",
            "norms.jsonl",
        )
    return None


def validate_matrix_scope(
    rows: list[MatrixEntry],
    norms_by_id: dict[str, NormEntry],
    fkp: str,
    label: str,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for row in rows:
        norm = norms_by_id.get(row.norm_id)
        if norm is None:
            continue
        if row.status == "применимо" and not norm_in_scope(norm, fkp):
            issues.append(
                ValidationIssue(
                    "matrix.scope_mismatch",
                    f"Строка {row.norm_id}: статус «применимо», но норма вне области ФКП "
                    f"{normalize_fkp(fkp)} (fkp_scope={norm.fkp_scope}).",
                    label,
                )
            )
    return issues


def validate_draft_composition_order(
    draft_text: str,
    norms_by_id: dict[str, NormEntry],
    label: str,
) -> list[ValidationIssue]:
    """Порядок абзацев с {{norm:...}} должен идти general → fkp_specific → special."""
    refs: list[str] = []
    for block in re.split(r"\n\s*\n", draft_text.replace("\r\n", "\n").strip()):
        block = block.strip()
        if not block or block.startswith("#") or block.startswith("|") or block.startswith("<!--"):
            continue
        found = re.findall(r"\{norm:([^}]+)\}", block)
        refs.extend(found)

    last_rank = -1
    last_norm = ""
    issues: list[ValidationIssue] = []
    for ref in refs:
        norm = norms_by_id.get(ref)
        if norm is None:
            continue
        rank = _LAYER_ORDER.get(effective_composition_layer(norm), 0)
        if rank < last_rank:
            issues.append(
                ValidationIssue(
                    "draft.composition_order",
                    f"Нарушен порядок слоёв композиции: норма {ref} "
                    f"({effective_composition_layer(norm)}) идёт после {last_norm}. "
                    "Ожидается general → fkp_specific → special.",
                    label,
                )
            )
        last_rank = rank
        last_norm = ref
    return issues


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().replace(",", ".").replace(" ", ""))
        except ValueError:
            return None
    return None
