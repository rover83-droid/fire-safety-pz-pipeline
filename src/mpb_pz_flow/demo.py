from __future__ import annotations

from pathlib import Path

from . import corpus, io
from .assembler import assemble_draft
from .models import MatrixEntry, NormEntry
from .pipeline import audit_project, init_project, run_calculations
from .sp2_matrices import lookup_compartment_limit, triggers_for_limit

SP8_EXCERPT = """# СП 8.13130.2020 (выписка для демо)

Системы противопожарной защиты. Наружное противопожарное водоснабжение.
Требования пожарной безопасности.

п. 5.2. Расход воды на наружное пожаротушение зданий принимается по таблице 2
в зависимости от назначения и строительного объема здания.

п. 5.17. Продолжительность тушения пожара для расчета расхода воды на наружное
пожаротушение следует принимать 3 часа.
"""

SP4_EXCERPT = """# СП 4.13130.2013 (выписка для демо)

Системы противопожарной защиты. Ограничение распространения пожара на объектах
защиты. Требования к объемно-планировочным и конструктивным решениям.

п. 8.1. Подъезд пожарных автомобилей должен обеспечиваться к зданиям
и сооружениям с учетом их функционального назначения и параметров.
"""

SP2_EXCERPT = """# СП 2.13130.2020 (выписка для демо)

Системы противопожарной защиты. Обеспечение огнестойкости объектов защиты.

п. 6.1. Степень огнестойкости и класс конструктивной пожарной опасности зданий
принимаются по таблице 6.11 для общественных зданий в зависимости от этажности
и площади этажа в пределах пожарного отсека.
"""


def create_demo(project_dir: Path) -> None:
    init_project(
        project_dir=project_dir,
        fkp="F3.1",
        section="Наружное ВПС и проезды",
        object_name="Демонстрационный магазин",
        description="Одноэтажный торговый объект для проверки конвейера.",
        force=True,
    )
    artifacts = io.artifact_dir(project_dir)
    passport = {
        "object_name": "Демонстрационный магазин",
        "description": "Одноэтажный торговый объект для проверки конвейера.",
        "confirmed": {
            "functional_fire_hazard_class": "F3.1",
            "functional_fire_hazard_basis": "ст. 32 Федерального закона N 123-ФЗ",
            "fire_resistance_degree": "III",
            "structural_fire_hazard_class": "С0",
            "floors": 1,
            "height_m": 6.8,
            "total_area_m2": 980,
            "sales_area_m2": 620,
            "fire_compartment_area_m2": 980,
            "building_volume_m3": 5400,
            "occupancy_people": 124,
            "technical_room_categories": [{"name": "Электрощитовая", "category": "В4"}],
            "engineering_fire_systems": ["СПС", "СОУЭ", "наружное противопожарное водоснабжение"],
            "external_fire_water_supply": {"hydrants": 2, "diameter_mm": 125, "fire_station_distance_km": 3.2},
        },
        "clarifying": {},
        "missing": {},
    }
    io.write_json(artifacts / "passport.json", passport)
    io.write_json(
        artifacts / "decisions.json",
        {
            "standard_editions": [
                {"document": "СП 8.13130", "edition_year": 2020},
                {"document": "СП 4.13130", "edition_year": 2013},
                {"document": "СП 2.13130", "edition_year": 2020},
            ],
            "collisions": [],
            "assumptions": ["Демо-данные не являются проектным решением для реального объекта."],
            "system_algorithms": [],
        },
    )

    corpus.ingest_text(
        project_dir,
        SP8_EXCERPT,
        "demo/SP_8_13130_2020_excerpt.md",
        document="СП 8.13130",
        edition_year=2020,
        title="Наружное противопожарное водоснабжение (демо-выписка)",
        status="добровольный",
    )
    corpus.ingest_text(
        project_dir,
        SP4_EXCERPT,
        "demo/SP_4_13130_2013_excerpt.md",
        document="СП 4.13130",
        edition_year=2013,
        title="Ограничение распространения пожара (демо-выписка)",
        status="добровольный",
    )
    corpus.ingest_text(
        project_dir,
        SP2_EXCERPT,
        "demo/SP_2_13130_2020_excerpt.md",
        document="СП 2.13130",
        edition_year=2020,
        title="Обеспечение огнестойкости объектов защиты (демо-выписка)",
        status="добровольный",
    )

    sp2_limit = lookup_compartment_limit("F3.1", "III", "С0")
    assert sp2_limit is not None
    norms = [
        NormEntry(
            norm_id="sp8-5-2-tab2",
            document="СП 8.13130",
            edition_year=2020,
            point="п. 5.2, табл. 2",
            quote="Расход воды на наружное пожаротушение зданий принимается по таблице 2 в зависимости от назначения и строительного объема здания.",
            subject="расход воды на наружное пожаротушение",
            trigger_parameter="building_volume_m3",
            source_file="standards/demo/SP_8_13130_2020_excerpt.md",
            composition_layer="general",
            fkp_scope=["*"],
            source_section="5",
        ),
        NormEntry(
            norm_id="sp8-6-3",
            document="СП 8.13130",
            edition_year=2020,
            point="п. 5.17",
            quote="Продолжительность тушения пожара для расчета расхода воды на наружное пожаротушение следует принимать 3 часа.",
            subject="продолжительность тушения",
            trigger_parameter="external_fire_water_supply",
            source_file="standards/demo/SP_8_13130_2020_excerpt.md",
            composition_layer="general",
            fkp_scope=["*"],
            source_section="5",
        ),
        NormEntry(
            norm_id="sp2-6-11-f3",
            document="СП 2.13130",
            edition_year=2020,
            point="п. 6.1, табл. 6.11",
            quote="Степень огнестойкости и класс конструктивной пожарной опасности зданий принимаются по таблице 6.11 для общественных зданий в зависимости от этажности и площади этажа в пределах пожарного отсека.",
            subject="степень огнестойкости и класс конструктивной пожарной опасности общественных зданий",
            trigger_parameter="fire_resistance_degree,structural_fire_hazard_class,floors,fire_compartment_area_m2",
            source_file="standards/demo/SP_2_13130_2020_excerpt.md",
            composition_layer="fkp_specific",
            fkp_scope=["F3"],
            source_section="6",
            triggers=triggers_for_limit(sp2_limit),
        ),
        NormEntry(
            norm_id="sp4-driveways",
            document="СП 4.13130",
            edition_year=2013,
            point="п. 8.1",
            quote="Подъезд пожарных автомобилей должен обеспечиваться к зданиям и сооружениям с учетом их функционального назначения и параметров.",
            subject="подъезды пожарных автомобилей",
            trigger_parameter="floors,height_m",
            source_file="standards/demo/SP_4_13130_2013_excerpt.md",
            composition_layer="special",
            fkp_scope=["*"],
            source_section="8",
            triggers=[
                {"param": "floors", "op": "<=", "value": 2},
                {"param": "height_m", "op": "<", "value": 18, "unit": "м"},
            ],
        ),
    ]
    io.write_norms(project_dir, norms)
    run_calculations(project_dir)
    io.write_matrix(
        project_dir,
        [
            MatrixEntry(
                norm_id="sp8-5-2-tab2",
                document_point="СП 8.13130.2020, п. 5.2, табл. 2",
                status="применимо",
                passport_basis="строительный объем здания 5400 м3",
                numeric_thresholds="объем 5-25 тыс. м3",
                collisions="",
                text_parameters="нормативный расход воды для наружного пожаротушения принят 15 л/с при строительном объеме 5400 м3",
            ),
            MatrixEntry(
                norm_id="sp8-6-3",
                document_point="СП 8.13130.2020, п. 5.17",
                status="применимо",
                passport_basis="для объекта предусмотрено наружное противопожарное водоснабжение",
                numeric_thresholds="3 часа",
                collisions="",
                text_parameters="нормативная продолжительность тушения пожара составляет 3 часа",
            ),
            MatrixEntry(
                norm_id="sp2-6-11-f3",
                document_point="СП 2.13130.2020, п. 6.1, табл. 6.11",
                status="применимо",
                passport_basis="степень огнестойкости III, класс С0, 1 этаж, площадь отсека 980 м2",
                numeric_thresholds="III/С0: этажность ≤ 5; площадь отсека ≤ 3000 м2",
                collisions="",
                text_parameters="приняты степень огнестойкости III и класс конструктивной пожарной опасности С0",
            ),
            MatrixEntry(
                norm_id="sp4-driveways",
                document_point="СП 4.13130.2013, п. 8.1",
                status="применимо",
                passport_basis="одноэтажное здание высотой 6.8 м",
                numeric_thresholds="этажность 1; высота менее 18 м",
                collisions="",
                text_parameters="подъезд пожарных автомобилей предусмотрен с одной продольной стороны здания",
            ),
        ],
    )
    assemble_draft(project_dir)
    audit_project(project_dir)
