from __future__ import annotations

from pathlib import Path
from typing import Any

from . import io
from .models import ConversationState, Stage, ValidationIssue
from .pipeline import init_project, refresh_stage
from .standards import FKP_TABLE, required_fields_for_fkp
from .validators import validate_decisions, validate_draft, validate_matrix, validate_norms, validate_passport


CONVERSATION_FILE = "conversation_state.json"

FIELD_LABELS: dict[str, str] = {
    "functional_fire_hazard_class": "класс функциональной пожарной опасности",
    "functional_fire_hazard_basis": "обоснование ФКП",
    "fire_resistance_degree": "степень огнестойкости",
    "structural_fire_hazard_class": "класс конструктивной пожарной опасности",
    "floors": "этажность",
    "height_m": "высота от отметки проезда до верха парапета, м",
    "total_area_m2": "общая площадь, м2",
    "fire_compartment_area_m2": "площадь пожарного отсека, м2",
    "building_volume_m3": "строительный объем здания, м3",
    "engineering_fire_systems": "состав инженерных систем пожарной защиты",
    "sales_area_m2": "площадь торгового зала, м2",
    "occupancy_people": "расчетная вместимость, чел.",
    "technical_room_categories": "категории технических и складских помещений",
    "external_fire_water_supply": "наружное противопожарное водоснабжение",
    "production_room_categories": "категории производственных и складских помещений",
    "zone_classes": "классы взрывоопасных/пожароопасных зон",
    "lightning_protection": "решение по молниезащите",
    "internal_fire_water_supply_decision": "решение о внутреннем противопожарном водопроводе",
}

FIELD_QUESTIONS: dict[str, str] = {
    "fire_resistance_degree": "Укажите принятую степень огнестойкости здания.",
    "structural_fire_hazard_class": "Укажите класс конструктивной пожарной опасности здания.",
    "floors": "Сколько этажей у здания?",
    "height_m": "Укажите высоту от отметки проезда пожарной техники до верха парапета, м.",
    "total_area_m2": "Укажите общую площадь здания, м2.",
    "fire_compartment_area_m2": "Укажите площадь пожарного отсека, м2.",
    "building_volume_m3": "Укажите строительный объем здания, м3.",
    "engineering_fire_systems": "Какие инженерные системы пожарной защиты предусматриваются?",
    "sales_area_m2": "Укажите площадь торгового зала, м2.",
    "occupancy_people": "Укажите расчетную вместимость объекта, чел.",
    "technical_room_categories": "Укажите категории технических и складских помещений.",
    "external_fire_water_supply": "Опишите наружное противопожарное водоснабжение: ПГ, Ду, расстояние до ПЧ.",
    "production_room_categories": "Укажите категории производственных и складских помещений.",
    "zone_classes": "Укажите классы взрывоопасных/пожароопасных зон.",
    "lightning_protection": "Укажите принятое решение по молниезащите.",
    "internal_fire_water_supply_decision": "Укажите решение о внутреннем противопожарном водопроводе.",
}

COMMANDS = {
    "Начать новый проект ПЗ МПБ": "создать проект и начать мастер-вопросы",
    "Продолжить проект <имя>": "открыть существующий проект и показать следующий шаг",
    "Покажи статус": "показать карточку проекта без JSON",
    "Покажи паспорт": "кратко показать подтвержденные параметры паспорта",
    "Что не хватает для запуска агента 1?": "показать блокеры разведки",
    "Запусти агента 1": "запустить разведку через Codex subagent",
    "Запусти агента 2": "запустить квалификацию и сборку через Codex subagent",
    "Запусти аудит": "запустить аудит через Codex subagent",
    "Собери финальный DOCX": "финализировать раздел после успешного аудита",
}


def start_codex_project(
    project_dir: Path,
    object_name: str,
    fkp: str | None,
    section: str,
    standards_dir: str = "standards",
    description: str = "",
) -> dict[str, Any]:
    resolved_fkp = fkp or infer_fkp(f"{object_name} {description}")
    if not resolved_fkp:
        conversation = ConversationState(
            user_stage="needs_fkp",
            last_question="Опишите назначение объекта, чтобы определить ФКП.",
            expected_passport_field="functional_fire_hazard_class",
            standards_dir=standards_dir,
        )
        project_dir.mkdir(parents=True, exist_ok=True)
        write_conversation_state(project_dir, conversation)
        return {
            "status_card": {
                "Проект": object_name,
                "Стадия": "нужно определить ФКП",
                "Следующий вопрос": conversation.last_question,
                "Следующее действие": "Ответьте назначением объекта или укажите ФКП вручную.",
            }
        }

    init_project(project_dir, resolved_fkp, section, object_name, description)
    conversation = ConversationState(
        user_stage="collecting_passport",
        standards_dir=standards_dir,
    )
    write_conversation_state(project_dir, conversation)
    question = next_passport_question(project_dir)
    return {"status_card": status_card(project_dir), "next_question": question}


def infer_fkp(text: str) -> str | None:
    lowered = text.lower()
    if any(word in lowered for word in ("магазин", "торгов", "тц", "маркет")):
        return "F3.1"
    if any(word in lowered for word in ("детский сад", "садик", "больниц", "дом престарел")):
        return "F1.1"
    if any(word in lowered for word in ("гостиниц", "отель", "общежит", "санатор")):
        return "F1.2"
    if any(word in lowered for word in ("многоквартир", "жилой дом", "мкд")):
        return "F1.3"
    if any(word in lowered for word in ("коттедж", "индивидуальный жилой", "одноквартир")):
        return "F1.4"
    if any(word in lowered for word in ("кинотеатр", "театр", "концерт", "клуб")):
        return "F2.1"
    if any(word in lowered for word in ("музей", "выстав", "танцев")):
        return "F2.2"
    if any(word in lowered for word in ("спорт", "фитнес", "трениров")):
        return "F2.3"
    if any(word in lowered for word in ("общепит", "кафе", "ресторан", "столов")):
        return "F3.2"
    if any(word in lowered for word in ("вокзал", "аэропорт")):
        return "F3.3"
    if any(word in lowered for word in ("поликлиник", "амбулатор")):
        return "F3.4"
    if any(word in lowered for word in ("бытов", "коммунальн")):
        return "F3.5"
    if any(word in lowered for word in ("школ", "учеб", "образователь")):
        return "F4.1"
    if any(word in lowered for word in ("офис", "административ", "проектн", "научн")):
        return "F4.4"
    if any(word in lowered for word in ("производ", "цех", "мастерск")):
        return "F5.1"
    if any(word in lowered for word in ("склад", "хранен", "логист")):
        return "F5.2"
    if any(word in lowered for word in ("паркинг", "стоянк", "гараж")):
        return "F5.3"
    return None


def read_conversation_state(project_dir: Path) -> ConversationState:
    path = project_dir / CONVERSATION_FILE
    if not path.exists():
        return ConversationState(user_stage="started")
    return ConversationState.from_dict(io.read_json(path))


def write_conversation_state(project_dir: Path, state: ConversationState) -> None:
    io.write_json(project_dir / CONVERSATION_FILE, state.to_dict())


def next_passport_question(project_dir: Path) -> str | None:
    state = refresh_stage(project_dir)
    passport = io.read_json(io.artifact_dir(project_dir) / "passport.json")
    confirmed = passport.get("confirmed", {})
    missing = passport.get("missing", {})
    for field in required_fields_for_fkp(state.fkp):
        if field in confirmed:
            continue
        missing_info = missing.get(field)
        if isinstance(missing_info, dict) and missing_info.get("criticality") == "noncritical":
            continue
        question = FIELD_QUESTIONS.get(field, f"Уточните параметр: {FIELD_LABELS.get(field, field)}.")
        conversation = read_conversation_state(project_dir)
        conversation.user_stage = "collecting_passport"
        conversation.last_question = question
        conversation.expected_passport_field = field
        write_conversation_state(project_dir, conversation)
        return question

    conversation = read_conversation_state(project_dir)
    conversation.user_stage = "passport_collected"
    conversation.last_question = None
    conversation.expected_passport_field = None
    write_conversation_state(project_dir, conversation)
    return None


def record_passport_answer(project_dir: Path, value: Any, field: str | None = None) -> dict[str, Any]:
    conversation = read_conversation_state(project_dir)
    target_field = field or conversation.expected_passport_field
    if not target_field:
        raise ValueError("Нет ожидаемого параметра паспорта. Сначала запросите следующий вопрос.")

    passport_path = io.artifact_dir(project_dir) / "passport.json"
    passport = io.read_json(passport_path)
    passport.setdefault("confirmed", {})[target_field] = _normalize_answer(value)
    passport.setdefault("clarifying", {}).pop(target_field, None)
    passport.setdefault("missing", {}).pop(target_field, None)
    io.write_json(passport_path, passport)

    conversation.expected_passport_field = None
    conversation.last_question = None
    conversation.user_stage = "collecting_passport"
    write_conversation_state(project_dir, conversation)
    question = next_passport_question(project_dir)
    return {"saved_field": target_field, "status_card": status_card(project_dir), "next_question": question}


def status_card(project_dir: Path) -> dict[str, str]:
    state = refresh_stage(project_dir)
    passport = io.read_json(io.artifact_dir(project_dir) / "passport.json")
    confirmed = passport.get("confirmed", {})
    required = required_fields_for_fkp(state.fkp)
    confirmed_required = [field for field in required if field in confirmed]
    norms = io.read_norms(project_dir)
    matrix = io.read_matrix(project_dir)
    applicable = [row for row in matrix if row.status == "применимо"]
    question = read_conversation_state(project_dir).last_question or next_passport_question(project_dir)
    next_action = _next_action(project_dir)
    return {
        "Проект": state.object_name,
        "Стадия": state.stage.value,
        "Паспорт": f"{len(confirmed_required)}/{len(required)} обязательных параметров заполнено",
        "Нормы": f"{len(norms)} проверенных записей",
        "Матрица": f"{len(matrix)} строк, применимо: {len(applicable)}",
        "Следующий вопрос": question or "нет",
        "Следующее действие": next_action,
    }


def passport_brief(project_dir: Path) -> list[str]:
    passport = io.read_json(io.artifact_dir(project_dir) / "passport.json")
    confirmed = passport.get("confirmed", {})
    rows = []
    for field, value in confirmed.items():
        label = FIELD_LABELS.get(field, field)
        rows.append(f"{label}: {value}")
    return rows


def missing_for_agent(project_dir: Path, agent: int) -> list[str]:
    if agent == 1:
        issues = validate_passport(project_dir) + validate_decisions(project_dir)
        if not has_local_standard_sources(project_dir):
            issues.append(ValidationIssue("standards.missing", "Нет локальных нормативных файлов в папке standards.", "standards"))
        return [_human_issue(issue) for issue in issues]
    if agent == 2:
        issues = validate_passport(project_dir) + validate_decisions(project_dir) + validate_norms(project_dir)
        return [_human_issue(issue) for issue in issues]
    if agent == 3:
        issues = validate_passport(project_dir) + validate_decisions(project_dir) + validate_norms(project_dir) + validate_matrix(project_dir)
        draft_issues = validate_draft(project_dir)
        if any(issue.code == "draft.missing" for issue in draft_issues):
            issues.extend(draft_issues)
        return [_human_issue(issue) for issue in issues]
    raise ValueError("Agent must be 1, 2 or 3.")


def can_run_agent(project_dir: Path, agent: int) -> bool:
    return not missing_for_agent(project_dir, agent)


def has_local_standard_sources(project_dir: Path) -> bool:
    conversation = read_conversation_state(project_dir)
    standards = (project_dir / conversation.standards_dir).resolve()
    if not standards.exists() or not standards.is_dir():
        return False
    return any(path.is_file() for path in standards.rglob("*"))


def format_status_card(card: dict[str, str]) -> str:
    return "\n".join(f"**{key}:** {value}" for key, value in card.items())


def _next_action(project_dir: Path) -> str:
    state = refresh_stage(project_dir)
    if state.stage == Stage.DOCX_READY:
        return "Финальный DOCX готов."
    if state.stage == Stage.AUDIT_PASSED:
        return "Можно собрать финальный DOCX."
    if state.stage == Stage.DRAFT_READY:
        return "Запустить аудит."
    if state.stage == Stage.MATRIX_READY:
        return "Собрать черновик раздела."
    if state.stage == Stage.NORMS_EXTRACTED:
        return "Запустить Агента 2: матрица и сборка раздела."
    if missing_for_agent(project_dir, 1):
        passport_issues = validate_passport(project_dir)
        missing_fields = [_missing_field_from_issue(issue.message) for issue in passport_issues]
        missing_labels = [FIELD_LABELS.get(field, field) for field in missing_fields if field]
        if missing_labels:
            return "Уточнить для запуска Агента 1: " + "; ".join(missing_labels) + "."
        return "Заполнить паспорт, решения и добавить локальные нормативные файлы."
    if missing_for_agent(project_dir, 2):
        return "Запустить Агента 1: разведка и извлечение норм."
    if missing_for_agent(project_dir, 3):
        return "Запустить Агента 2: матрица и сборка раздела."
    if validate_draft(project_dir):
        return "Доработать черновик перед аудитом."
    return "Запустить аудит или собрать финальный DOCX после успешного аудита."


def _normalize_answer(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.lower() in ("true", "false"):
            return stripped.lower() == "true"
        normalized = stripped.replace(",", ".")
        if normalized and normalized.replace(".", "", 1).isdigit():
            number = float(normalized)
            return int(number) if number.is_integer() else number
        if ";" in stripped:
            return [item.strip() for item in stripped.split(";") if item.strip()]
        return stripped
    return value


def _human_issue(issue: Any) -> str:
    if issue.code == "passport.required":
        field = _missing_field_from_issue(issue.message)
        if field:
            return f"{issue.artifact}: требуется подтвердить параметр «{FIELD_LABELS.get(field, field)}»."
    return f"{issue.artifact}: {issue.message}"


def _missing_field_from_issue(message: str) -> str | None:
    marker = "Required passport field is not confirmed or marked noncritical: "
    if marker not in message:
        return None
    return message.split(marker, 1)[1].rstrip(".")

