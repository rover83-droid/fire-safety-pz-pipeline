"""Опорные пересечения СП 2.13130 (огнестойкость): ФКП × степень × КПО.

Не полный парсер таблиц документа — seed для пилотных ФКП (F3.x общественные,
F5.x производственные). Значения согласованы с типовыми строками табл. 6.11 и 6.1
актуальной редакции СП 2.13130.2020 и служат источником структурированных triggers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Sp2CompartmentLimit:
    """Допустимые параметры пожарного отсека для сочетания степень/КПО."""

    fire_resistance_degree: str
    structural_fire_hazard_class: str
    max_floors: int | None
    max_compartment_area_m2: float | None
    table_ref: str
    notes: str = ""


# Табл. 6.11 СП 2.13130.2020 — общественные здания (пилотные строки для F3).
# Упрощённый seed: III/С0 до 5 этажей / 3000 м² отсека; II/С0 до 8 / 4000.
_SP2_TABLE_6_11: tuple[Sp2CompartmentLimit, ...] = (
    Sp2CompartmentLimit("I", "С0", 16, 5000.0, "СП 2.13130, таблица 6.11"),
    Sp2CompartmentLimit("II", "С0", 8, 4000.0, "СП 2.13130, таблица 6.11"),
    Sp2CompartmentLimit("II", "С1", 3, 2000.0, "СП 2.13130, таблица 6.11"),
    Sp2CompartmentLimit("III", "С0", 5, 3000.0, "СП 2.13130, таблица 6.11"),
    Sp2CompartmentLimit("III", "С1", 3, 2000.0, "СП 2.13130, таблица 6.11"),
    Sp2CompartmentLimit("IV", "С0", 2, 1400.0, "СП 2.13130, таблица 6.11"),
    Sp2CompartmentLimit("V", "С0", 1, 800.0, "СП 2.13130, таблица 6.11"),
)

# Табл. 6.1 СП 2.13130.2020 — производственные/складские (пилотные строки для F5).
_SP2_TABLE_6_1: tuple[Sp2CompartmentLimit, ...] = (
    Sp2CompartmentLimit("I", "С0", None, 52000.0, "СП 2.13130, таблица 6.1"),
    Sp2CompartmentLimit("II", "С0", None, 52000.0, "СП 2.13130, таблица 6.1"),
    Sp2CompartmentLimit("III", "С0", 3, 5200.0, "СП 2.13130, таблица 6.1"),
    Sp2CompartmentLimit("III", "С1", 2, 3500.0, "СП 2.13130, таблица 6.1"),
    Sp2CompartmentLimit("IV", "С0", 2, 2600.0, "СП 2.13130, таблица 6.1"),
    Sp2CompartmentLimit("IV", "С1", 1, 2000.0, "СП 2.13130, таблица 6.1"),
    Sp2CompartmentLimit("V", "С0", 1, 1200.0, "СП 2.13130, таблица 6.1"),
)

_PUBLIC_FAMILIES = frozenset({"F2", "F3", "F4"})
_INDUSTRIAL_FAMILIES = frozenset({"F5"})


def _family(fkp: str) -> str:
    text = str(fkp or "").strip().upper().replace("Ф", "F")
    return text.split(".", 1)[0] if text else ""


def table_for_fkp(fkp: str) -> tuple[Sp2CompartmentLimit, ...]:
    family = _family(fkp)
    if family in _PUBLIC_FAMILIES:
        return _SP2_TABLE_6_11
    if family in _INDUSTRIAL_FAMILIES:
        return _SP2_TABLE_6_1
    return ()


def lookup_compartment_limit(
    fkp: str,
    fire_resistance_degree: str,
    structural_fire_hazard_class: str,
) -> Sp2CompartmentLimit | None:
    degree = str(fire_resistance_degree or "").strip().upper()
    kpo = str(structural_fire_hazard_class or "").strip().upper().replace("C", "С")
    for row in table_for_fkp(fkp):
        if row.fire_resistance_degree.upper() == degree and row.structural_fire_hazard_class.upper() == kpo:
            return row
    return None


def triggers_for_limit(limit: Sp2CompartmentLimit) -> list[dict[str, Any]]:
    """Триггеры «объект укладывается в строку таблицы» (AND)."""
    triggers: list[dict[str, Any]] = [
        {"param": "fire_resistance_degree", "op": "==", "value": limit.fire_resistance_degree},
        {"param": "structural_fire_hazard_class", "op": "==", "value": limit.structural_fire_hazard_class},
    ]
    if limit.max_floors is not None:
        triggers.append({"param": "floors", "op": "<=", "value": limit.max_floors})
    if limit.max_compartment_area_m2 is not None:
        triggers.append(
            {
                "param": "fire_compartment_area_m2",
                "op": "<=",
                "value": limit.max_compartment_area_m2,
                "unit": "м2",
            }
        )
    return triggers


def propose_triggers_for_passport(fkp: str, confirmed: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Если паспорт попал в seed-таблицу — вернуть AND-триггеры для нормы огнестойкости."""
    degree = confirmed.get("fire_resistance_degree")
    kpo = confirmed.get("structural_fire_hazard_class")
    if degree is None or kpo is None:
        return None
    limit = lookup_compartment_limit(fkp, str(degree), str(kpo))
    if limit is None:
        return None
    return triggers_for_limit(limit)


def seed_rows_for_fkp(fkp: str) -> list[dict[str, Any]]:
    """Сериализуемые строки seed-таблицы (для тестов и документации)."""
    return [
        {
            "fire_resistance_degree": row.fire_resistance_degree,
            "structural_fire_hazard_class": row.structural_fire_hazard_class,
            "max_floors": row.max_floors,
            "max_compartment_area_m2": row.max_compartment_area_m2,
            "table_ref": row.table_ref,
            "triggers": triggers_for_limit(row),
        }
        for row in table_for_fkp(fkp)
    ]
