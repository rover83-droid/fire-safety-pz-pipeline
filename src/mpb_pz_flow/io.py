from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .models import MatrixEntry, NormEntry, ProjectState


ARTIFACT_DIR = "artifacts"
STATE_FILE = "state.json"
SECTIONS_DIRNAME = "sections"
SECTIONS_INDEX_FILE = "index.json"

NORMS_FILE = "norms.jsonl"
MATRIX_FILE = "applicability_matrix.jsonl"
DRAFT_FILE = "draft.md"
AGENT_FINDINGS_FILE = "agent_findings.json"
AUDIT_REPORT_FILE = "audit_report.json"
FINAL_MD_FILE = "final.md"
FINAL_DOCX_FILE = "final.docx"


def artifact_dir(project_dir: Path) -> Path:
    return project_dir / ARTIFACT_DIR


@dataclass(slots=True)
class ArtifactPaths:
    """Resolved file locations for one section's artifact set.

    Passport and decisions are project-level (one object, one decision journal);
    norms, matrix, draft, findings, audit and final outputs are per-section.
    """

    project_dir: Path
    section: str
    slug: str
    root: Path
    passport: Path
    decisions: Path
    calculations: Path
    norms: Path
    matrix: Path
    draft: Path
    agent_findings: Path
    audit_report: Path
    final_md: Path
    final_docx: Path

    @property
    def audit_history(self) -> Path:
        return self.root / "audit_history"

    def rel(self, path: Path) -> str:
        try:
            return path.relative_to(artifact_dir(self.project_dir)).as_posix()
        except ValueError:
            return path.name


def slugify_section(name: str) -> str:
    text = name.lower().replace("ё", "е")
    text = re.sub(r"[^a-zа-я0-9]+", "-", text).strip("-")
    text = re.sub(r"-{2,}", "-", text)
    return text[:60].strip("-") or "section"


def sections_index_path(project_dir: Path) -> Path:
    return artifact_dir(project_dir) / SECTIONS_DIRNAME / SECTIONS_INDEX_FILE


def read_section_index(project_dir: Path) -> dict[str, str]:
    path = sections_index_path(project_dir)
    if not path.exists():
        return {}
    data = read_json(path)
    return {str(slug): str(section) for slug, section in data.items()}


def register_section(project_dir: Path, section: str, slug: str | None = None) -> str:
    index = read_section_index(project_dir)
    for existing_slug, existing_section in index.items():
        if existing_section == section:
            return existing_slug
    resolved = slug or slugify_section(section)
    if resolved in index:
        raise ValueError(f"Section slug already registered for another section: {resolved}")
    index[resolved] = section
    write_json(sections_index_path(project_dir), index)
    return resolved


def section_slug(project_dir: Path, section: str) -> str:
    for slug, name in read_section_index(project_dir).items():
        if name == section:
            return slug
    return slugify_section(section)


def artifact_paths(project_dir: Path, section: str | None = None) -> ArtifactPaths:
    state = read_state(project_dir)
    target = section or state.section
    artifacts = artifact_dir(project_dir)
    slug = section_slug(project_dir, target)
    set_dir = artifacts / SECTIONS_DIRNAME / slug
    if not set_dir.exists() and target == state.section:
        # Legacy single-section layout: the artifacts root serves the active section.
        set_dir = artifacts
    return ArtifactPaths(
        project_dir=project_dir,
        section=target,
        slug=slug,
        root=set_dir,
        passport=artifacts / "passport.json",
        decisions=artifacts / "decisions.json",
        calculations=artifacts / "calculations.json",
        norms=set_dir / NORMS_FILE,
        matrix=set_dir / MATRIX_FILE,
        draft=set_dir / DRAFT_FILE,
        agent_findings=set_dir / AGENT_FINDINGS_FILE,
        audit_report=set_dir / AUDIT_REPORT_FILE,
        final_md=set_dir / FINAL_MD_FILE,
        final_docx=set_dir / FINAL_DOCX_FILE,
    )


def sha256_path(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def read_state(project_dir: Path) -> ProjectState:
    return ProjectState.from_dict(read_json(project_dir / STATE_FILE))


def write_state(project_dir: Path, state: ProjectState) -> None:
    write_json(project_dir / STATE_FILE, state.to_dict())


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped:
            rows.append(json.loads(stripped))
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    _atomic_write_text(path, text)


def read_norms(project_dir: Path, section: str | None = None) -> list[NormEntry]:
    path = artifact_paths(project_dir, section).norms
    return [NormEntry.from_dict(row) for row in read_jsonl(path)]


def write_norms(project_dir: Path, norms: Iterable[NormEntry], section: str | None = None) -> None:
    path = artifact_paths(project_dir, section).norms
    write_jsonl(path, (norm.to_dict() for norm in norms))


def read_matrix(project_dir: Path, section: str | None = None) -> list[MatrixEntry]:
    path = artifact_paths(project_dir, section).matrix
    return [MatrixEntry.from_dict(row) for row in read_jsonl(path)]


def write_matrix(project_dir: Path, rows: Iterable[MatrixEntry], section: str | None = None) -> None:
    path = artifact_paths(project_dir, section).matrix
    write_jsonl(path, (row.to_dict() for row in rows))


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(path, text)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        finally:
            raise
