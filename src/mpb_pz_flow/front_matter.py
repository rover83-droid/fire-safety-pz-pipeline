"""Автогенерация обвязки ПЗ: перечень сокращений и перечень нормативных документов.

Перечень сокращений собирается по фактическому тексту против словаря
(в перечень попадает только то, что реально употреблено). Перечень НД
строится из журнала решений (принятые редакции) с наименованиями и статусом
применения из манифеста корпуса — один источник истины, ноль рассинхронов.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import corpus, io
from .standards import ABBREVIATIONS, ABBREVIATION_SKIP

_ABBR_TOKEN_RE = re.compile(r"\b[А-ЯЁ]{2,6}\b")


def collect_abbreviations(text: str) -> list[tuple[str, str]]:
    """Употреблённые в тексте известные сокращения с расшифровками (по алфавиту)."""
    tokens = set(_ABBR_TOKEN_RE.findall(text))
    found = [(token, ABBREVIATIONS[token]) for token in tokens if token in ABBREVIATIONS]
    return sorted(found)


def unknown_abbreviations(text: str) -> list[str]:
    """Похожие на сокращения токены без расшифровки в словаре — кандидаты на дополнение."""
    tokens = set(_ABBR_TOKEN_RE.findall(text))
    unknown = {
        token
        for token in tokens
        if token not in ABBREVIATIONS and token.upper() not in ABBREVIATION_SKIP
    }
    return sorted(unknown)


def abbreviations_section(text: str) -> str:
    rows = collect_abbreviations(text)
    if not rows:
        return ""
    lines = [
        "## Перечень сокращений",
        "",
        "| Сокращение | Расшифровка |",
        "|---|---|",
    ]
    for token, meaning in rows:
        lines.append(f"| {token} | {meaning} |")
    lines.append("")
    return "\n".join(lines)


def normative_documents_section(project_dir: Path) -> str:
    paths = io.artifact_paths(project_dir)
    if not paths.decisions.exists():
        return ""
    decisions = io.read_json(paths.decisions)
    editions = decisions.get("standard_editions", [])
    if not editions:
        return ""

    manifest = {(doc.document, doc.edition_year): doc for doc in corpus.read_manifest(project_dir)}
    lines = [
        "## Перечень нормативно-правовых актов и нормативных документов",
        "",
        "| № | Обозначение | Наименование | Статус применения | Источник в корпусе |",
        "|---|---|---|---|---|",
    ]
    for index, edition in enumerate(sorted(editions, key=lambda e: str(e.get("document", ""))), start=1):
        document = str(edition.get("document", "")).strip()
        year = edition.get("edition_year", "")
        designation = f"{document}.{year}" if document and year else document
        doc = manifest.get((document, int(year))) if document and year else None
        title = doc.title if doc and doc.title else "наименование уточнить по источнику"
        status = doc.status if doc else "неизвестно"
        registered = "зарегистрирован" if doc else "не зарегистрирован"
        lines.append(f"| {index} | {designation} | {title} | {status} | {registered} |")
    lines.append("")
    return "\n".join(lines)


def build_front_matter(project_dir: Path, section: str | None = None) -> str:
    """Markdown-обвязка для секции: сокращения (по тексту final/draft) + перечень НД."""
    paths = io.artifact_paths(project_dir, section)
    source = paths.final_md if paths.final_md.exists() else paths.draft
    text = source.read_text(encoding="utf-8") if source.exists() else ""

    parts = [part for part in (abbreviations_section(text), normative_documents_section(project_dir)) if part]
    return "\n".join(parts).strip() + ("\n" if parts else "")


def write_front_matter(project_dir: Path, section: str | None = None) -> Path:
    paths = io.artifact_paths(project_dir, section)
    content = build_front_matter(project_dir, section)
    target = paths.root / "front_matter.md"
    io.write_text(target, content)
    return target
