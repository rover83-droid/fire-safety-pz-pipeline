from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class Stage(str, Enum):
    FKP_DETECTED = "fkp_detected"
    PASSPORT_READY = "passport_ready"
    NORMS_EXTRACTED = "norms_extracted"
    MATRIX_READY = "matrix_ready"
    DRAFT_READY = "draft_ready"
    AUDIT_PASSED = "audit_passed"
    DOCX_READY = "docx_ready"


PIPELINE_ORDER: tuple[Stage, ...] = (
    Stage.FKP_DETECTED,
    Stage.PASSPORT_READY,
    Stage.NORMS_EXTRACTED,
    Stage.MATRIX_READY,
    Stage.DRAFT_READY,
    Stage.AUDIT_PASSED,
    Stage.DOCX_READY,
)


Fkp = Literal[
    "F1.1",
    "F1.2",
    "F1.3",
    "F1.4",
    "F2.1",
    "F2.2",
    "F2.3",
    "F2.4",
    "F3.1",
    "F3.2",
    "F3.3",
    "F3.4",
    "F3.5",
    "F3.6",
    "F4.1",
    "F4.2",
    "F4.3",
    "F4.4",
    "F5.1",
    "F5.2",
    "F5.3",
]
NormStatus = Literal["применимо", "неприменимо", "требует инженерной проверки"]
AuditLevel = Literal["level_1", "level_2"]


@dataclass(slots=True)
class ProjectState:
    version: int
    stage: Stage
    fkp: str
    section: str
    object_name: str
    last_updated: str
    notes: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectState":
        return cls(
            version=int(data.get("version", 1)),
            stage=Stage(data["stage"]),
            fkp=str(data["fkp"]),
            section=str(data["section"]),
            object_name=str(data["object_name"]),
            last_updated=str(data["last_updated"]),
            notes=list(data.get("notes", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "stage": self.stage.value,
            "fkp": self.fkp,
            "section": self.section,
            "object_name": self.object_name,
            "last_updated": self.last_updated,
            "notes": self.notes,
        }


@dataclass(slots=True)
class ConversationState:
    user_stage: str
    last_question: str | None = None
    expected_passport_field: str | None = None
    last_agent: str | None = None
    standards_dir: str = "standards"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConversationState":
        return cls(
            user_stage=str(data.get("user_stage", "started")),
            last_question=data.get("last_question"),
            expected_passport_field=data.get("expected_passport_field"),
            last_agent=data.get("last_agent"),
            standards_dir=str(data.get("standards_dir", "standards")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_stage": self.user_stage,
            "last_question": self.last_question,
            "expected_passport_field": self.expected_passport_field,
            "last_agent": self.last_agent,
            "standards_dir": self.standards_dir,
        }


def _as_text(value: Any) -> str:
    """Легаси-матрицы хранят списки в текстовых полях — склеиваем через точку с запятой."""
    if isinstance(value, list):
        return "; ".join(str(item) for item in value)
    return str(value)


@dataclass(slots=True)
class ValidationIssue:
    code: str
    message: str
    artifact: str
    severity: Literal["error", "warning"] = "error"
    source: Literal["validator", "agent"] = "validator"


@dataclass(slots=True)
class NormEntry:
    norm_id: str
    document: str
    edition_year: int
    point: str
    quote: str
    subject: str
    trigger_parameter: str
    source_file: str
    collision_with: str | None = None
    # Машинно-вычислимые условия применимости:
    # [{"param": "height_m", "op": ">=", "value": 10, "unit": "м"}, ...]
    triggers: list[dict[str, Any]] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NormEntry":
        # Отсутствующие поля не валят чтение: пустые значения поймает validate_norms
        # как norms.required — ошибка валидации вместо краха на легаси-данных.
        return cls(
            norm_id=str(data.get("norm_id", "")),
            document=str(data.get("document", "")),
            edition_year=int(data.get("edition_year", 0) or 0),
            point=str(data.get("point", "")),
            quote=str(data.get("quote", "")),
            subject=str(data.get("subject", "")),
            trigger_parameter=str(data.get("trigger_parameter", "")),
            source_file=str(data.get("source_file", "")),
            collision_with=data.get("collision_with"),
            triggers=data.get("triggers"),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "norm_id": self.norm_id,
            "document": self.document,
            "edition_year": self.edition_year,
            "point": self.point,
            "quote": self.quote,
            "subject": self.subject,
            "trigger_parameter": self.trigger_parameter,
            "source_file": self.source_file,
            "collision_with": self.collision_with,
        }
        if self.triggers is not None:
            result["triggers"] = self.triggers
        return result


@dataclass(slots=True)
class MatrixEntry:
    norm_id: str
    document_point: str
    status: NormStatus
    passport_basis: str
    numeric_thresholds: str
    collisions: str
    text_parameters: str
    # Непустое поле разрешает расхождение статуса с предложением триггер-движка
    # (фиксируется как warning, а не error).
    override_justification: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MatrixEntry":
        return cls(
            norm_id=str(data.get("norm_id", "")),
            document_point=str(data.get("document_point", "")),
            status=data.get("status", ""),
            passport_basis=str(data.get("passport_basis", "")),
            numeric_thresholds=_as_text(data.get("numeric_thresholds", "")),
            collisions=_as_text(data.get("collisions", "")),
            text_parameters=_as_text(data.get("text_parameters", "")),
            override_justification=str(data.get("override_justification", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        result = {
            "norm_id": self.norm_id,
            "document_point": self.document_point,
            "status": self.status,
            "passport_basis": self.passport_basis,
            "numeric_thresholds": self.numeric_thresholds,
            "collisions": self.collisions,
            "text_parameters": self.text_parameters,
        }
        if self.override_justification:
            result["override_justification"] = self.override_justification
        return result
