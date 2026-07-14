"""Сборка сводного тома 9 «Мероприятия по обеспечению пожарной безопасности»
из уже прошедших аудит разделов проекта (ПП РФ №87).

Это компилятор, а не конвейер: содержательные разделы берутся из проверенных
section/final.md (хэш-привязка обеспечивается выше — на уровне каждого раздела),
а обвязка (сокращения, перечень НД) и характеристика объекта строятся из паспорта.
"""

from __future__ import annotations

from pathlib import Path

from . import io
from .front_matter import abbreviations_section, normative_documents_section

# Порядок текстовых разделов тома 9 по ПП РФ №87.
# generated=True -> раздел строится из паспорта/шаблона, а не из набора секции.
PP87_ORDER: list[tuple[str, bool]] = [
    ("Общие положения", True),
    ("Характеристика объекта", True),
    ("Категорирование", False),
    ("ОПР / степень ОО / КПО", False),
    ("Противопожарные расстояния", False),
    ("Наружное ВПС и проезды", False),
    ("Безопасность людей (эвакуация)", False),
    ("Безопасность пожарных", False),
    ("Противопожарная защита", False),
    ("Перечень помещений под АУПТ/СПС", False),
    ("Организационные мероприятия", False),
    ("Расчёт пожарных рисков", False),
]

TITLE = "Раздел 9. Мероприятия по обеспечению пожарной безопасности"


def _fmt(value: object) -> str:
    return str(value).replace(".", ",")


def _strip_section(md: str) -> str:
    """Убирает H1-заголовок секции и дублирующую ТЭП-таблицу."""
    out: list[str] = []
    skipping = False
    for line in md.splitlines():
        if not out and line.startswith("# "):
            continue
        if line.strip().startswith("## Технико-экономические показатели"):
            skipping = True
            continue
        if skipping:
            if line.strip() == "" or line.lstrip().startswith("|"):
                continue
            skipping = False
        out.append(line)
    return "\n".join(out).strip()


def _general(object_name: str) -> str:
    return (
        f"Настоящий раздел разработан для объекта: {object_name}. Раздел выполнен "
        "в составе проектной документации в соответствии с требованиями "
        "Постановления Правительства РФ от 16.02.2008 №87 и Федерального закона "
        "от 22.07.2008 №123-ФЗ «Технический регламент о требованиях пожарной "
        "безопасности». Нормативная база приведена в перечне нормативных "
        "документов настоящего тома."
    )


def _characteristics(passport: dict) -> str:
    c = passport.get("confirmed", {})
    rows = [
        ("Класс функциональной пожарной опасности", c.get("functional_fire_hazard_class", "")),
        ("Степень огнестойкости", c.get("fire_resistance_degree", "")),
        ("Класс конструктивной пожарной опасности", c.get("structural_fire_hazard_class", "")),
        ("Категория по взрывопожарной и пожарной опасности", c.get("building_category", "")),
        ("Этажность", c.get("floors", "")),
        ("Высота здания, м", _fmt(c.get("height_m", ""))),
        ("Строительный объём, м3", _fmt(c.get("building_volume_m3", ""))),
        ("Общая площадь здания, м2", _fmt(c.get("total_area_m2", ""))),
        ("Площадь застройки, м2", _fmt(c.get("footprint_area_m2", ""))),
    ]
    body = ["| Показатель | Значение |", "|---|---|"]
    for label, value in rows:
        if str(value).strip():
            body.append(f"| {label} | {value} |")
    return "\n".join(body)


def build_consolidated_markdown(project_dir: Path) -> tuple[str, list[str], list[str]]:
    """Собрать Markdown сводного тома. Возвращает (текст, включённые, плейсхолдеры)."""
    passport = io.read_json(project_dir / "artifacts" / "passport.json")
    object_name = passport.get("object_name", "Объект")
    registered = set(io.read_section_index(project_dir).values())
    # Активная секция живёт в legacy-корне artifacts/ (не в индексе секций) — учитываем её.
    try:
        registered.add(io.read_state(project_dir).section)
    except Exception:
        pass

    parts: list[str] = []
    included: list[str] = []
    placeholders: list[str] = []

    for number, (name, generated) in enumerate(PP87_ORDER, start=1):
        heading = f"## {number}. {name}"
        if generated:
            if name == "Характеристика объекта":
                parts.append(f"{heading}\n\n{_characteristics(passport)}")
            else:
                parts.append(f"{heading}\n\n{_general(object_name)}")
            included.append(name)
            continue

        if name in registered:
            paths = io.artifact_paths(project_dir, name)
            if paths.final_md.exists():
                body = _strip_section(paths.final_md.read_text(encoding="utf-8"))
                parts.append(f"{heading}\n\n{body}")
                included.append(name)
                continue

        parts.append(
            f"{heading}\n\n_Раздел не разрабатывался в текущем прогоне; "
            "заполняется проектной организацией по получении исходных данных._"
        )
        placeholders.append(name)

    combined = "\n\n".join(parts)
    document = "\n\n".join(
        [
            f"# {TITLE}",
            f"**Объект:** {object_name}",
            abbreviations_section(combined),
            normative_documents_section(project_dir),
            combined,
        ]
    )
    return document, included, placeholders


def consolidate(project_dir: Path, output_stem: str = "tom9_svod", docx: bool = True) -> dict:
    """Записать сводный том 9 в Markdown и (опционально) DOCX по ГОСТ."""
    document, included, placeholders = build_consolidated_markdown(project_dir)
    passport = io.read_json(project_dir / "artifacts" / "passport.json")
    object_name = passport.get("object_name", "Объект")

    out_md = project_dir / "artifacts" / f"{output_stem}.md"
    io.write_text(out_md, document)
    result: dict = {"md": out_md, "docx": None, "included": included, "placeholders": placeholders}

    if docx:
        try:
            from .docx_export import render_markdown_to_docx

            out_docx = project_dir / "artifacts" / f"{output_stem}.docx"
            render_markdown_to_docx(document, out_docx, object_name, TITLE, title_page=True)
            result["docx"] = out_docx
        except RuntimeError:
            result["docx"] = None  # python-docx не установлен — только Markdown
    return result
