"""Адресная маршрутизация находок аудита.

Замечания не идут все скопом одному агенту: дефекты норм, паспорта, редакций
и корпуса возвращаются Агенту 1 (разведка); дефекты матрицы, текста и структуры
— Агенту 2 (сборка). Случаи, где причина неоднозначна, решает оркестратор.
"""

from __future__ import annotations

AGENT_1 = "agent_1"
AGENT_2 = "agent_2"
ORCHESTRATOR = "orchestrator"

ROUTE_LABELS = {
    AGENT_1: "Агент 1 (разведка: паспорт, нормы, редакции, корпус)",
    AGENT_2: "Агент 2 (сборка: матрица, текст, структура)",
    ORCHESTRATOR: "Оркестратор (причина неоднозначна — решить вручную)",
}

# Маршрут по префиксу кода находки.
_PREFIX_ROUTES = {
    "passport.": AGENT_1,
    "norms.": AGENT_1,
    "decisions.": AGENT_1,
    "corpus.": AGENT_1,
    "matrix.": AGENT_2,
    "draft.": AGENT_2,
    "volume_structure.": AGENT_2,
    "agent_findings.": ORCHESTRATOR,
}

# Точечные исключения из префиксного правила.
_OVERRIDES = {
    # Число без провенанса: либо дефект паспорта (Агент 1), либо переноса (Агент 2).
    "draft.number_unverified": ORCHESTRATOR,
}


def route_code(code: str) -> str:
    if code in _OVERRIDES:
        return _OVERRIDES[code]
    for prefix, route in _PREFIX_ROUTES.items():
        if code.startswith(prefix):
            return route
    return ORCHESTRATOR


def routing_summary(codes: list[str]) -> dict[str, int]:
    summary = {AGENT_1: 0, AGENT_2: 0, ORCHESTRATOR: 0}
    for code in codes:
        summary[route_code(code)] += 1
    return summary
