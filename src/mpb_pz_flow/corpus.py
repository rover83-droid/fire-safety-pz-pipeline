"""Нормативный корпус: инжест источников, нормализация кодировок, манифест, верификация цитат.

Контракт Фазы 1: цитата нормы имеет силу только если она механически найдена
в локальном источнике. Источники регистрируются в манифесте с контрольной
суммой; повреждённые экспорты (битые кодировки) отклоняются на входе, а не
всплывают молчаливым провалом поиска.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from . import io
from .models import NormEntry, ValidationIssue

STANDARDS_DIRNAME = "standards"
MANIFEST_FILE = "manifest.json"

DOCUMENT_STATUSES = ("обязательный", "добровольный", "неизвестно")

_MIN_SEGMENT_CHARS = 12
_FUZZY_RATIO = 0.9
_CYRILLIC_RE = re.compile(r"[а-яё]", re.IGNORECASE)
_LATIN_RE = re.compile(r"[a-z]", re.IGNORECASE)
_ELLIPSIS_RE = re.compile(r"\.{3}|…|<\.\.\.>")

_TEXT_CACHE: dict[tuple[str, int, int], tuple[str, str]] = {}


class CorpusError(RuntimeError):
    """Источник не может быть принят в корпус или прочитан из него."""


@dataclass(slots=True)
class CorpusDocument:
    doc_id: str
    document: str
    edition_year: int
    title: str
    file: str
    sha256: str
    status: str = "неизвестно"
    in_force: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "CorpusDocument":
        return cls(
            doc_id=str(data["doc_id"]),
            document=str(data["document"]),
            edition_year=int(data["edition_year"]),
            title=str(data.get("title", "")),
            file=str(data["file"]),
            sha256=str(data["sha256"]),
            status=str(data.get("status", "неизвестно")),
            in_force=bool(data.get("in_force", True)),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "doc_id": self.doc_id,
            "document": self.document,
            "edition_year": self.edition_year,
            "title": self.title,
            "file": self.file,
            "sha256": self.sha256,
            "status": self.status,
            "in_force": self.in_force,
        }


def standards_dir(project_dir: Path) -> Path:
    return project_dir / STANDARDS_DIRNAME


def manifest_path(project_dir: Path) -> Path:
    return standards_dir(project_dir) / MANIFEST_FILE


def read_manifest(project_dir: Path) -> list[CorpusDocument]:
    path = manifest_path(project_dir)
    if not path.exists():
        return []
    data = io.read_json(path)
    return [CorpusDocument.from_dict(entry) for entry in data.get("documents", [])]


def write_manifest(project_dir: Path, documents: list[CorpusDocument]) -> None:
    io.write_json(
        manifest_path(project_dir),
        {"documents": [doc.to_dict() for doc in sorted(documents, key=lambda d: d.doc_id)]},
    )


def find_document(project_dir: Path, document: str, edition_year: int) -> CorpusDocument | None:
    for doc in read_manifest(project_dir):
        if doc.document == document and doc.edition_year == edition_year:
            return doc
    return None


def default_doc_id(document: str, edition_year: int) -> str:
    base = io.slugify_section(document)
    return f"{base}-{edition_year}"


# --- Кодировки и санитарная проверка -----------------------------------------


def decode_bytes(data: bytes) -> tuple[str, str]:
    """Декодирует байты источника: BOM UTF-8/UTF-16, затем UTF-8, затем cp1251."""
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig"), "utf-8-sig"
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16"), "utf-16"
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("cp1251"), "cp1251"


def cyrillic_share(text: str) -> float:
    cyr = len(_CYRILLIC_RE.findall(text))
    lat = len(_LATIN_RE.findall(text))
    if cyr + lat == 0:
        return 0.0
    return cyr / (cyr + lat)


def ensure_sane_russian_source(text: str, origin: str) -> None:
    """Российский нормативный документ обязан состоять преимущественно из кириллицы.

    Битые экспорты (UTF-16 с потерянными байтами, двойная перекодировка) дают
    низкую долю кириллицы — такие файлы непригодны для верификации цитат.
    """
    letters = len(_CYRILLIC_RE.findall(text)) + len(_LATIN_RE.findall(text))
    if letters < 200:
        raise CorpusError(
            f"Источник {origin} почти не содержит текста ({letters} букв); проверьте файл."
        )
    share = cyrillic_share(text)
    if share < 0.5:
        raise CorpusError(
            f"Источник {origin} повреждён: доля кириллицы {share:.0%} — похоже на битую кодировку. "
            "Переэкспортируйте документ (UTF-8, обычный текст/Markdown) и добавьте заново."
        )


def read_source_text(path: Path) -> str:
    """Текст источника с детекцией кодировки и кэшем; CorpusError для битых файлов."""
    return _cached_text(path)[0]


def read_source_normalized(path: Path) -> str:
    return _cached_text(path)[1]


def _cached_text(path: Path) -> tuple[str, str]:
    stat = path.stat()
    key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
    cached = _TEXT_CACHE.get(key)
    if cached is not None:
        return cached
    text, _encoding = decode_bytes(path.read_bytes())
    ensure_sane_russian_source(text, path.name)
    value = (text, normalize_for_match(text))
    _TEXT_CACHE[key] = value
    return value


# --- Верификация цитат --------------------------------------------------------


def normalize_for_match(text: str) -> str:
    text = text.lower().replace("ё", "е")
    text = re.sub(r"[^a-zа-я0-9]+", " ", text)
    return text.strip()


def quote_matches(source_normalized: str, quote: str) -> bool:
    """Цитата найдена в источнике. Многоточие в цитате — допустимый пропуск текста.

    Сегменты цитаты должны встречаться в источнике в исходном порядке.
    """
    position = 0
    matched_any = False
    for segment in _ELLIPSIS_RE.split(quote):
        normalized = normalize_for_match(segment)
        if len(normalized) < _MIN_SEGMENT_CHARS:
            continue
        index = source_normalized.find(normalized, position)
        if index == -1:
            index = _fuzzy_find(source_normalized, normalized, position)
        if index == -1:
            return False
        position = index + len(normalized)
        matched_any = True
    return matched_any


def _fuzzy_find(source: str, segment: str, position: int) -> int:
    words = segment.split()
    if len(words) < 4:
        return -1
    anchor = " ".join(words[:4])
    start = source.find(anchor, position)
    window_len = int(len(segment) * 1.2) + 20
    while start != -1:
        window = source[start : start + window_len]
        ratio = difflib.SequenceMatcher(None, window[: len(segment) + 20], segment).ratio()
        if ratio >= _FUZZY_RATIO:
            return start
        start = source.find(anchor, start + 1)
    return -1


def resolve_source(project_dir: Path, norm: NormEntry) -> Path | None:
    """Файл источника нормы: сперва манифест корпуса, затем source_file записи."""
    doc = find_document(project_dir, norm.document, norm.edition_year)
    if doc is not None:
        candidate = standards_dir(project_dir) / doc.file
        if candidate.exists():
            return candidate
    if norm.source_file.strip():
        project_candidate = project_dir / norm.source_file
        if project_candidate.exists():
            return project_candidate
        direct = Path(norm.source_file)
        if direct.exists():
            return direct
    return None


# --- Инжест -------------------------------------------------------------------


def ingest_text(
    project_dir: Path,
    text: str,
    filename: str,
    document: str,
    edition_year: int,
    title: str = "",
    status: str = "неизвестно",
    doc_id: str | None = None,
) -> CorpusDocument:
    if status not in DOCUMENT_STATUSES:
        raise CorpusError(f"Недопустимый статус документа: {status}. Ожидается: {', '.join(DOCUMENT_STATUSES)}.")
    ensure_sane_russian_source(text, filename)
    target = standards_dir(project_dir) / filename
    io.write_text(target, text)

    entry = CorpusDocument(
        doc_id=doc_id or default_doc_id(document, edition_year),
        document=document,
        edition_year=edition_year,
        title=title,
        file=filename,
        sha256=io.sha256_path(target) or "",
        status=status,
    )
    documents = [
        doc
        for doc in read_manifest(project_dir)
        if doc.doc_id != entry.doc_id and not (doc.document == document and doc.edition_year == edition_year)
    ]
    documents.append(entry)
    write_manifest(project_dir, documents)
    return entry


def ingest_file(
    project_dir: Path,
    source_path: Path,
    document: str,
    edition_year: int,
    title: str = "",
    status: str = "неизвестно",
    doc_id: str | None = None,
    filename: str | None = None,
) -> CorpusDocument:
    if not source_path.exists():
        raise CorpusError(f"Файл не найден: {source_path}")
    text, _encoding = decode_bytes(source_path.read_bytes())
    target_name = filename or f"{doc_id or default_doc_id(document, edition_year)}.md"
    return ingest_text(project_dir, text, target_name, document, edition_year, title, status, doc_id)


# --- Проверка корпуса ----------------------------------------------------------


def verify_corpus(project_dir: Path) -> list[ValidationIssue]:
    """Каждый документ манифеста существует, не изменён и читается."""
    label = f"{STANDARDS_DIRNAME}/{MANIFEST_FILE}"
    issues: list[ValidationIssue] = []
    seen: dict[tuple[str, int], str] = {}
    for doc in read_manifest(project_dir):
        key = (doc.document, doc.edition_year)
        if key in seen:
            issues.append(
                ValidationIssue(
                    "corpus.duplicate_document",
                    f"Документ {doc.document} ({doc.edition_year}) зарегистрирован дважды: {seen[key]} и {doc.doc_id}.",
                    label,
                )
            )
        seen[key] = doc.doc_id
        path = standards_dir(project_dir) / doc.file
        if not path.exists():
            issues.append(
                ValidationIssue(
                    "corpus.file_missing",
                    f"Файл корпуса отсутствует: {doc.file} ({doc.document}, {doc.edition_year}).",
                    label,
                )
            )
            continue
        actual = io.sha256_path(path)
        if actual != doc.sha256:
            issues.append(
                ValidationIssue(
                    "corpus.hash_mismatch",
                    f"Файл корпуса изменён после регистрации: {doc.file} ({doc.document}, {doc.edition_year}). Переподтвердите источник через corpus-add.",
                    label,
                )
            )
            continue
        try:
            read_source_text(path)
        except CorpusError as exc:
            issues.append(ValidationIssue("corpus.unreadable", str(exc), label))
    return issues
