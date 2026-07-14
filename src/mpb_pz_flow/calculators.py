"""Инженерные калькуляторы: нормативные таблицы как данные + прозрачные формулы.

Каждый результат несёт значение, единицу, формулу с подстановкой и нормативное
основание (документ, год, пункт/таблица) — это провенанс для абзацев Типа Г
и для валидатора числовой согласованности.

ВАЖНО: табличные данные закодированы по указанным редакциям документов.
За пределами закодированного диапазона калькулятор отказывает (CalcError),
а не экстраполирует. Перед использованием в реальном проекте значения таблиц
подлежат сверке с зарегистрированным источником корпуса (Фаза 1).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

CALC_ENGINE = "mpb-pz-flow.calculators"


class CalcError(RuntimeError):
    """Входные данные вне области применения калькулятора."""


@dataclass(slots=True)
class CalcResult:
    calc_id: str
    title: str
    value: str
    unit: str
    formula: str
    basis: str
    inputs: dict[str, Any]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "calc_id": self.calc_id,
            "title": self.title,
            "value": self.value,
            "unit": self.unit,
            "formula": self.formula,
            "basis": self.basis,
            "inputs": self.inputs,
            "notes": self.notes,
        }


# --- СП 8.13130.2020, табл. 3: НПВ производственных зданий ---------------------
# Здания с фонарями, а также без фонарей шириной 60 м и менее.
# Ключ: (группа категорий, группа степеней ОО) -> [(верхняя граница объёма, тыс. м3; расход, л/с)]

_SP8_T3_CATEGORY_GROUPS = {"Г": "ГД", "Д": "ГД", "А": "АБВ", "Б": "АБВ", "В": "АБВ"}
_SP8_T3_DEGREE_GROUPS = {"I": "I-II", "II": "I-II", "III": "III", "IV": "IV-V", "V": "IV-V"}

SP8_TABLE3: dict[tuple[str, str], list[tuple[float, int]]] = {
    ("ГД", "I-II"): [(5, 10), (20, 10), (50, 15), (200, 20), (400, 25), (600, 35)],
    ("АБВ", "I-II"): [(5, 10), (20, 15), (50, 20), (200, 30), (400, 35), (600, 40)],
    ("ГД", "III"): [(5, 10), (20, 15), (50, 20), (200, 25)],
    ("АБВ", "III"): [(5, 15), (20, 20), (50, 25), (200, 40)],
    ("ГД", "IV-V"): [(5, 10), (20, 15), (50, 20), (200, 30)],
    ("АБВ", "IV-V"): [(5, 15), (20, 20), (50, 25), (200, 40)],
}

# --- СП 8.13130.2020, табл. 2: НПВ общественных зданий (закодированное подмножество) ---
# Здания высотой не более 2 этажей: (верхняя граница объёма, тыс. м3; расход, л/с)
SP8_TABLE2_PUBLIC_LOW_RISE: list[tuple[float, int]] = [(1, 10), (5, 10), (25, 15)]


def calc_external_water_flow_f5(confirmed: dict[str, Any]) -> CalcResult:
    volume = _require_number(confirmed, ("building_volume_m3",), "строительный объем, м3")
    degree = _require_text(confirmed, ("fire_resistance_degree",), "степень огнестойкости")
    category = _building_category(confirmed)

    degree_group = _SP8_T3_DEGREE_GROUPS.get(degree.upper().strip())
    category_group = _SP8_T3_CATEGORY_GROUPS.get(category.upper().strip())
    if degree_group is None:
        raise CalcError(f"Степень огнестойкости '{degree}' не распознана (ожидается I–V).")
    if category_group is None:
        raise CalcError(f"Категория здания '{category}' не распознана (ожидается А/Б/В/Г/Д).")

    width = _optional_number(confirmed, ("building_width_m",))
    notes = []
    if width is not None and width > 60:
        raise CalcError(
            "Ширина здания более 60 м: таблица 3 СП 8.13130.2020 неприменима, "
            "используйте таблицу 4 (в калькуляторе не закодирована)."
        )
    if width is None:
        notes.append("Ширина здания не подтверждена; принято допущение «не более 60 м» (область действия табл. 3).")

    rows = SP8_TABLE3[(category_group, degree_group)]
    volume_thousands = volume / 1000.0
    flow = _lookup_band(rows, volume_thousands)
    if flow is None:
        raise CalcError(
            f"Объем {_fmt(volume)} м3 вне закодированного диапазона табл. 3 "
            f"для категории {category} и степени {degree}: сверьте с источником."
        )
    band = _band_text(rows, volume_thousands)
    notes.append("Табличное значение подлежит сверке с зарегистрированным источником СП 8.13130.2020.")
    return CalcResult(
        calc_id="sp8_t3_external_flow_f5",
        title="Расход воды на наружное пожаротушение (производственное здание)",
        value=str(flow),
        unit="л/с",
        formula=(
            f"V = {_fmt(volume)} м3 = {_fmt(volume_thousands)} тыс. м3 → диапазон {band}; "
            f"категория {category}; {degree} степень огнестойкости → q = {flow} л/с"
        ),
        basis="СП 8.13130.2020, табл. 3",
        inputs={"building_volume_m3": volume, "fire_resistance_degree": degree, "building_category": category},
        notes=notes,
    )


def calc_external_water_flow_public(confirmed: dict[str, Any]) -> CalcResult:
    volume = _require_number(confirmed, ("building_volume_m3",), "строительный объем, м3")
    floors = _require_number(confirmed, ("floors",), "этажность")
    if floors > 2:
        raise CalcError(
            "Закодировано только подмножество табл. 2 для общественных зданий не более 2 этажей; "
            "для большей этажности сверьте расход с источником."
        )
    volume_thousands = volume / 1000.0
    flow = _lookup_band(SP8_TABLE2_PUBLIC_LOW_RISE, volume_thousands)
    if flow is None:
        raise CalcError(
            f"Объем {_fmt(volume)} м3 вне закодированного диапазона табл. 2: сверьте с источником."
        )
    band = _band_text(SP8_TABLE2_PUBLIC_LOW_RISE, volume_thousands)
    return CalcResult(
        calc_id="sp8_t2_external_flow_public",
        title="Расход воды на наружное пожаротушение (общественное здание)",
        value=str(flow),
        unit="л/с",
        formula=(
            f"V = {_fmt(volume)} м3 = {_fmt(volume_thousands)} тыс. м3 → диапазон {band}; "
            f"этажность {_fmt(floors)} (не более 2) → q = {flow} л/с"
        ),
        basis="СП 8.13130.2020, табл. 2",
        inputs={"building_volume_m3": volume, "floors": floors},
        notes=["Табличное значение подлежит сверке с зарегистрированным источником СП 8.13130.2020."],
    )


def calc_fire_truck_access_sides(confirmed: dict[str, Any], fkp: str) -> CalcResult:
    if not fkp.upper().startswith("F5"):
        raise CalcError("Правило сторон подъезда закодировано для зданий класса Ф5 (СП 4.13130.2013, п. 8.2).")
    width = _require_number(confirmed, ("building_width_m",), "ширина здания, м")
    two_sides = width > 18
    value = "с двух продольных сторон" if two_sides else "с одной продольной стороны"
    return CalcResult(
        calc_id="sp4_8_2_access_sides",
        title="Стороны подъезда пожарных автомобилей",
        value=value,
        unit="",
        formula=f"ширина здания {_fmt(width)} м {'>' if two_sides else '≤'} 18 м → подъезд {value}",
        basis="СП 4.13130.2013, п. 8.2",
        inputs={"building_width_m": width, "fkp": fkp},
    )


def calc_fire_drive_width(confirmed: dict[str, Any]) -> CalcResult:
    height = _require_number(confirmed, ("height_m",), "высота здания, м")
    if height <= 13:
        width, condition = 3.5, "до 13 м включительно"
    elif height <= 46:
        width, condition = 4.2, "более 13 м, но не более 46 м"
    else:
        width, condition = 6.0, "более 46 м"
    return CalcResult(
        calc_id="sp4_8_6_drive_width",
        title="Минимальная ширина проезда для пожарной техники",
        value=_fmt(width),
        unit="м",
        formula=f"высота здания {_fmt(height)} м ({condition}) → ширина проезда не менее {_fmt(width)} м",
        basis="СП 4.13130.2013, п. 8.6",
        inputs={"height_m": height},
    )


def calc_fire_drive_distance(confirmed: dict[str, Any]) -> CalcResult:
    height = _require_number(confirmed, ("height_m",), "высота здания, м")
    # СП 4.13130.2013, п. 8.2.6 (здания класса Ф5): три тира по высоте.
    if height <= 12:
        distance, condition = "не более 25", "не более 12 м"
    elif height <= 28:
        distance, condition = "5–8", "более 12 м, но не более 28 м"
    else:
        distance, condition = "8–10", "более 28 м"
    return CalcResult(
        calc_id="sp4_8_8_drive_distance",
        title="Расстояние от края проезда до стены здания",
        value=distance,
        unit="м",
        formula=f"высота здания {_fmt(height)} м ({condition}) → расстояние {distance} м",
        basis="СП 4.13130.2013, п. 8.2.6",
        inputs={"height_m": height},
    )


def calc_roof_access(confirmed: dict[str, Any], fkp: str) -> CalcResult:
    height = _require_number(
        confirmed, ("height_to_parapet_m", "height_m"), "высота до карниза/парапета, м"
    )
    required = height >= 10
    value = "требуются" if required else "не требуются"
    return CalcResult(
        calc_id="sp4_7_2_roof_access",
        title="Выходы на кровлю",
        value=value,
        unit="",
        formula=f"высота здания {_fmt(height)} м {'≥' if required else '<'} 10 м → выходы на кровлю {value}",
        basis="СП 4.13130.2013, п. 7.2",
        inputs={"height_m": height, "fkp": fkp},
    )


def calc_roof_ladder_count(confirmed: dict[str, Any], fkp: str) -> CalcResult:
    if not fkp.upper().startswith("F5"):
        raise CalcError("Интервал 200 м по периметру закодирован для зданий класса Ф5 (СП 4.13130.2013, п. 7.3).")
    perimeter = _optional_number(confirmed, ("building_perimeter_m",))
    derivation = ""
    if perimeter is None:
        length = _optional_number(confirmed, ("building_length_m",))
        width = _optional_number(confirmed, ("building_width_m",))
        if length is None or width is None:
            raise CalcError(
                "Не подтверждены периметр здания (building_perimeter_m) либо габариты "
                "(building_length_m, building_width_m)."
            )
        perimeter = 2 * (length + width)
        derivation = f"P = 2 × ({_fmt(length)} + {_fmt(width)}) = {_fmt(perimeter)} м; "
    count = max(1, math.ceil(perimeter / 200))
    return CalcResult(
        calc_id="sp4_7_3_roof_ladders",
        title="Число выходов на кровлю по пожарным лестницам (Ф5)",
        value=str(count),
        unit="шт.",
        formula=(
            f"{derivation}лестницы через каждые 200 м периметра: "
            f"n = max(1, ⌈{_fmt(perimeter)} / 200⌉) = {count}"
        ),
        basis="СП 4.13130.2013, п. 7.3",
        inputs={"building_perimeter_m": perimeter, "fkp": fkp},
    )


def calc_fire_duration(confirmed: dict[str, Any], fkp: str = "") -> CalcResult:
    # СП 8.13130.2020, п. 5.17 (ред. приказа МЧС от 25.12.2023 N 1329):
    # по умолчанию 3 ч; для жилых и общественных зданий I и II степеней
    # огнестойкости класса С0 — 2 ч.
    degree = str(confirmed.get("fire_resistance_degree", "")).strip().upper()
    structural = str(confirmed.get("structural_fire_hazard_class", "")).strip()
    public_or_resid = fkp.upper().startswith(("F1", "F2", "F3", "F4"))
    if public_or_resid and degree in ("I", "II") and structural in ("С0", "C0"):
        value = "2"
        formula = (
            "для жилых и общественных зданий I и II степеней огнестойкости "
            "класса С0 продолжительность тушения пожара принимается 2 часа"
        )
    else:
        value = "3"
        formula = "продолжительность тушения пожара принимается 3 часа"
    return CalcResult(
        calc_id="sp8_6_3_duration",
        title="Расчетная продолжительность наружного пожаротушения",
        value=value,
        unit="ч",
        formula=formula,
        basis="СП 8.13130.2020, п. 5.17",
        inputs={"fire_resistance_degree": degree, "fkp": fkp},
    )


def calc_risk_threshold(fkp: str) -> CalcResult:
    from .standards import FKP_TABLE

    info = FKP_TABLE.get(fkp)
    if info is None or "risk_threshold" not in info:
        raise CalcError(f"Порог пожарного риска для ФКП {fkp} не закодирован.")
    threshold = info["risk_threshold"]
    article = "ст. 93" if str(threshold) == "1e-4" else "ст. 79"
    value = "1·10⁻⁴" if str(threshold) == "1e-4" else "1·10⁻⁶"
    return CalcResult(
        calc_id="fz123_risk_threshold",
        title="Нормативный порог индивидуального пожарного риска",
        value=value,
        unit="год⁻¹",
        formula=f"ФКП {fkp} → допустимый индивидуальный пожарный риск {value} в год",
        basis=f"ФЗ-123, {article}",
        inputs={"fkp": fkp},
    )


# --- Реестр калькуляторов -------------------------------------------------------

CALCULATORS: dict[str, tuple[str, Callable[[dict[str, Any], str], CalcResult]]] = {
    "sp8_t3_external_flow_f5": (
        "НПВ производственного здания (СП 8.13130.2020, табл. 3)",
        lambda confirmed, fkp: calc_external_water_flow_f5(confirmed),
    ),
    "sp8_t2_external_flow_public": (
        "НПВ общественного здания (СП 8.13130.2020, табл. 2)",
        lambda confirmed, fkp: calc_external_water_flow_public(confirmed),
    ),
    "sp4_8_2_access_sides": (
        "Стороны подъезда пожарной техники (СП 4.13130.2013, п. 8.2)",
        calc_fire_truck_access_sides,
    ),
    "sp4_8_6_drive_width": (
        "Ширина пожарного проезда (СП 4.13130.2013, п. 8.6)",
        lambda confirmed, fkp: calc_fire_drive_width(confirmed),
    ),
    "sp4_8_8_drive_distance": (
        "Расстояние проезд—стена (СП 4.13130.2013, п. 8.2.6)",
        lambda confirmed, fkp: calc_fire_drive_distance(confirmed),
    ),
    "sp4_7_2_roof_access": (
        "Выходы на кровлю (СП 4.13130.2013, п. 7.2)",
        calc_roof_access,
    ),
    "sp4_7_3_roof_ladders": (
        "Число пожарных лестниц на кровлю (СП 4.13130.2013, п. 7.3)",
        calc_roof_ladder_count,
    ),
    "sp8_6_3_duration": (
        "Продолжительность тушения (СП 8.13130.2020, п. 5.17)",
        lambda confirmed, fkp: calc_fire_duration(confirmed, fkp),
    ),
    "fz123_risk_threshold": (
        "Порог пожарного риска (ФЗ-123)",
        lambda confirmed, fkp: calc_risk_threshold(fkp),
    ),
}

# По ФКП: какие калькуляторы уместны (None = любой ФКП).
_F5_ONLY = {"sp8_t3_external_flow_f5", "sp4_8_2_access_sides", "sp4_7_3_roof_ladders"}
_PUBLIC_ONLY = {"sp8_t2_external_flow_public"}


def run_applicable(passport: dict[str, Any], fkp: str, only: str | None = None) -> tuple[list[CalcResult], list[dict[str, str]]]:
    """Выполняет уместные калькуляторы; недостаток данных — в skipped, не ошибка."""
    confirmed = passport.get("confirmed", {})
    if not isinstance(confirmed, dict):
        confirmed = {}
    results: list[CalcResult] = []
    skipped: list[dict[str, str]] = []
    for calc_id, (title, func) in CALCULATORS.items():
        if only and calc_id != only:
            continue
        if calc_id in _F5_ONLY and not fkp.upper().startswith("F5"):
            continue
        if calc_id in _PUBLIC_ONLY and fkp.upper().startswith("F5"):
            continue
        try:
            results.append(func(confirmed, fkp))
        except CalcError as exc:
            skipped.append({"calc_id": calc_id, "title": title, "reason": str(exc)})
    return results, skipped


# --- Вспомогательные ------------------------------------------------------------


def _building_category(confirmed: dict[str, Any]) -> str:
    for key in ("building_fire_category", "preliminary_fire_category", "fire_category"):
        value = confirmed.get(key)
        if value:
            return str(value)
    raise CalcError(
        "Не подтверждена категория здания по пожарной опасности "
        "(building_fire_category / preliminary_fire_category)."
    )


def _require_number(confirmed: dict[str, Any], keys: tuple[str, ...], label: str) -> float:
    value = _optional_number(confirmed, keys)
    if value is None:
        raise CalcError(f"Не подтвержден числовой параметр паспорта: {label} ({' / '.join(keys)}).")
    return value


def _optional_number(confirmed: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        raw = confirmed.get(key)
        if raw is None or raw == "":
            continue
        if isinstance(raw, bool):
            continue
        if isinstance(raw, (int, float)):
            return float(raw)
        text = str(raw).strip().replace(",", ".")
        match = text.split()[0] if text else ""
        try:
            return float(match)
        except ValueError:
            continue
    return None


def _require_text(confirmed: dict[str, Any], keys: tuple[str, ...], label: str) -> str:
    for key in keys:
        value = confirmed.get(key)
        if value:
            return str(value)
    raise CalcError(f"Не подтвержден параметр паспорта: {label} ({' / '.join(keys)}).")


def _lookup_band(rows: list[tuple[float, int]], volume_thousands: float) -> int | None:
    for upper, flow in rows:
        if volume_thousands <= upper:
            return flow
    return None


def _band_text(rows: list[tuple[float, int]], volume_thousands: float) -> str:
    previous = 0.0
    for upper, _flow in rows:
        if volume_thousands <= upper:
            return f"св. {_fmt(previous)} до {_fmt(upper)} тыс. м3" if previous else f"до {_fmt(upper)} тыс. м3"
        previous = upper
    return "вне диапазона"


def _fmt(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")
