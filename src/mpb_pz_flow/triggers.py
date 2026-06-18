"""Машинно-вычислимые триггеры применимости норм.

Норма может нести структурные условия:

    "triggers": [{"param": "height_m", "op": ">=", "value": 10, "unit": "м"}]

Движок вычисляет их против подтверждённых параметров паспорта и предлагает
статус матрицы. Агент вправе не согласиться, но только с записанным
обоснованием (MatrixEntry.override_justification) — расхождение без
обоснования блокируется валидатором.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .models import NormEntry, NormStatus

VALID_OPS = (">=", ">", "<=", "<", "==", "!=", "in", "contains", "exists")

TriggerState = Literal["true", "false", "unknown"]


@dataclass(slots=True)
class TriggerOutcome:
    state: TriggerState
    explanation: str


def validate_trigger_spec(trigger: object) -> str | None:
    """Сообщение об ошибке формата триггера или None."""
    if not isinstance(trigger, dict):
        return "триггер должен быть объектом {param, op, value}"
    param = str(trigger.get("param", "")).strip()
    if not param:
        return "у триггера отсутствует param"
    op = trigger.get("op")
    if op not in VALID_OPS:
        return f"недопустимый op '{op}'; ожидается один из: {', '.join(VALID_OPS)}"
    if op != "exists" and "value" not in trigger:
        return f"у триггера {param} {op} отсутствует value"
    return None


def evaluate_trigger(trigger: dict[str, Any], confirmed: dict[str, Any]) -> TriggerOutcome:
    param = str(trigger["param"])
    op = str(trigger["op"])
    unit = str(trigger.get("unit", "")).strip()
    expected = trigger.get("value")

    if param not in confirmed:
        return TriggerOutcome("unknown", f"отсутствует подтвержденный параметр паспорта '{param}'")
    actual = confirmed[param]

    if op == "exists":
        return TriggerOutcome("true", f"{param} подтвержден в паспорте")

    if op in (">=", ">", "<=", "<"):
        actual_num = _as_number(actual)
        expected_num = _as_number(expected)
        if actual_num is None or expected_num is None:
            return TriggerOutcome(
                "unknown",
                f"параметр '{param}' не приводится к числу для сравнения {op} (значение: {actual!r})",
            )
        result = {
            ">=": actual_num >= expected_num,
            ">": actual_num > expected_num,
            "<=": actual_num <= expected_num,
            "<": actual_num < expected_num,
        }[op]
        suffix = f" {unit}" if unit else ""
        return TriggerOutcome(
            "true" if result else "false",
            f"{param} = {_fmt(actual_num)}{suffix} {op} {_fmt(expected_num)}{suffix}: {'выполнено' if result else 'не выполнено'}",
        )

    if op in ("==", "!="):
        equal = _values_equal(actual, expected)
        result = equal if op == "==" else not equal
        return TriggerOutcome(
            "true" if result else "false",
            f"{param} = {actual!r} {op} {expected!r}: {'выполнено' if result else 'не выполнено'}",
        )

    if op == "in":
        options = expected if isinstance(expected, list) else [expected]
        result = any(_values_equal(actual, option) for option in options)
        return TriggerOutcome(
            "true" if result else "false",
            f"{param} = {actual!r} {'входит' if result else 'не входит'} в {options!r}",
        )

    # op == "contains"
    if isinstance(actual, list):
        result = any(_values_equal(item, expected) for item in actual)
    else:
        result = str(expected).strip().lower() in str(actual).strip().lower()
    return TriggerOutcome(
        "true" if result else "false",
        f"{param} = {actual!r} {'содержит' if result else 'не содержит'} {expected!r}",
    )


def propose_status(norm: NormEntry, passport: dict[str, Any]) -> tuple[NormStatus, str] | None:
    """Предложение движка: (статус, обоснование) или None, если триггеров нет."""
    if not norm.triggers:
        return None
    confirmed = passport.get("confirmed", {})
    if not isinstance(confirmed, dict):
        confirmed = {}

    outcomes = [evaluate_trigger(trigger, confirmed) for trigger in norm.triggers]
    explanations = "; ".join(outcome.explanation for outcome in outcomes)

    if any(outcome.state == "false" for outcome in outcomes):
        return "неприменимо", explanations
    if any(outcome.state == "unknown" for outcome in outcomes):
        return "требует инженерной проверки", explanations
    return "применимо", explanations


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        normalized = value.strip().replace(",", ".").replace(" ", "")
        try:
            return float(normalized)
        except ValueError:
            return None
    return None


def _values_equal(left: Any, right: Any) -> bool:
    left_num = _as_number(left)
    right_num = _as_number(right)
    if left_num is not None and right_num is not None:
        return left_num == right_num
    return str(left).strip().lower() == str(right).strip().lower()


def _fmt(value: float) -> str:
    return str(int(value)) if value == int(value) else str(value)
