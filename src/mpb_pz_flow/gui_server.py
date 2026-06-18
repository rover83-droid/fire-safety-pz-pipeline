from __future__ import annotations

import argparse
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import io
from .assembler import assemble_draft, finalize_markdown
from .demo import create_demo
from .docx_export import export_docx
from .models import MatrixEntry, NormEntry
from .pipeline import audit_project, build_initial_matrix, init_project, refresh_stage
from .validators import validate_all


ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = ROOT / "web"
PROJECTS_ROOT = ROOT / "projects"

ARTIFACT_ATTRS = {
    "passport": "passport",
    "decisions": "decisions",
    "norms": "norms",
    "matrix": "matrix",
    "draft": "draft",
    "agent_findings": "agent_findings",
    "audit": "audit_report",
    "final": "final_md",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run MPB PZ local GUI server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    PROJECTS_ROOT.mkdir(exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), GuiHandler)
    print(f"MPB PZ GUI: http://{args.host}:{args.port}")
    server.serve_forever()
    return 0


class GuiHandler(BaseHTTPRequestHandler):
    server_version = "MpbPzGui/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path.startswith("/api/"):
                self._handle_api_get(parsed.path, parse_qs(parsed.query))
            else:
                self._serve_static(parsed.path)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=500)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            payload = self._read_json()
            self._handle_api_post(parsed.path, payload)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=500)

    def log_message(self, format: str, *args: object) -> None:
        return

    def _handle_api_get(self, path: str, query: dict[str, list[str]]) -> None:
        if path == "/api/projects":
            self._send_json({"projects": list_projects()})
            return
        if path == "/api/project":
            project = _project_from_query(query)
            self._send_json(project_snapshot(project))
            return
        if path == "/api/artifact":
            project = _project_from_query(query)
            name = _one(query, "name")
            self._send_json(read_artifact(project, name))
            return
        self._send_json({"error": "Unknown API endpoint."}, status=404)

    def _handle_api_post(self, path: str, payload: dict[str, Any]) -> None:
        if path == "/api/project":
            name = _clean_project_name(str(payload["name"]))
            project = PROJECTS_ROOT / name
            init_project(
                project,
                str(payload["fkp"]),
                str(payload["section"]),
                str(payload["object_name"]),
                str(payload.get("description", "")),
                force=bool(payload.get("force", False)),
            )
            self._send_json(project_snapshot(project))
            return
        if path == "/api/demo":
            name = _clean_project_name(str(payload.get("name", "demo")))
            project = PROJECTS_ROOT / name
            create_demo(project)
            self._send_json(project_snapshot(project))
            return
        if path == "/api/artifact":
            project = _project_from_payload(payload)
            write_artifact(project, str(payload["name"]), payload["content"])
            self._send_json(project_snapshot(project))
            return
        if path == "/api/action":
            project = _project_from_payload(payload)
            action = str(payload["action"])
            result = run_action(project, action)
            self._send_json({"result": result, "project": project_snapshot(project)})
            return
        self._send_json({"error": "Unknown API endpoint."}, status=404)

    def _serve_static(self, path: str) -> None:
        if path in ("", "/"):
            path = "/index.html"
        file_path = (WEB_ROOT / path.lstrip("/")).resolve()
        if not _is_inside(file_path, WEB_ROOT) or not file_path.exists() or not file_path.is_file():
            self.send_error(404)
            return
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        data = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _send_json(self, data: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def list_projects() -> list[dict[str, Any]]:
    PROJECTS_ROOT.mkdir(exist_ok=True)
    projects: list[dict[str, Any]] = []
    for path in sorted(PROJECTS_ROOT.iterdir()):
        if path.is_dir() and (path / io.STATE_FILE).exists():
            state = refresh_stage(path)
            projects.append(
                {
                    "name": path.name,
                    "object_name": state.object_name,
                    "fkp": state.fkp,
                    "section": state.section,
                    "stage": state.stage.value,
                }
            )
    return projects


def project_snapshot(project: Path) -> dict[str, Any]:
    state = refresh_stage(project)
    issues = validate_all(project)
    paths = io.artifact_paths(project)
    artifacts = {
        key: getattr(paths, attr).exists()
        for key, attr in ARTIFACT_ATTRS.items()
    }
    return {
        "name": project.name,
        "state": state.to_dict(),
        "issues": [_issue_to_dict(issue) for issue in issues],
        "artifacts": artifacts,
        "sections": io.read_section_index(project),
        "active_section": state.section,
    }


def read_artifact(project: Path, name: str) -> dict[str, Any]:
    path = _artifact_path(project, name)
    if not path.exists():
        return {"name": name, "content": None}
    if path.suffix == ".json":
        return {"name": name, "content": io.read_json(path)}
    if path.suffix == ".jsonl":
        return {"name": name, "content": io.read_jsonl(path)}
    return {"name": name, "content": path.read_text(encoding="utf-8")}


def write_artifact(project: Path, name: str, content: Any) -> None:
    if name == "audit":
        raise ValueError("audit_report.json создаётся только командой аудита; находки агента пишите в agent_findings.json.")
    path = _artifact_path(project, name)
    if name == "norms":
        rows = [NormEntry.from_dict(row).to_dict() for row in content]
        io.write_jsonl(path, rows)
        return
    if name == "matrix":
        rows = [MatrixEntry.from_dict(row).to_dict() for row in content]
        io.write_jsonl(path, rows)
        return
    if path.suffix == ".json":
        if not isinstance(content, dict):
            raise ValueError(f"{name} content must be a JSON object.")
        io.write_json(path, content)
        return
    if not isinstance(content, str):
        raise ValueError(f"{name} content must be text.")
    path.write_text(content, encoding="utf-8")


def run_action(project: Path, action: str) -> dict[str, Any]:
    if action == "build_matrix":
        rows = build_initial_matrix(project)
        return {"message": f"Создано строк матрицы: {len(rows)}"}
    if action == "assemble":
        draft = assemble_draft(project)
        return {"message": f"Черновик собран. Абзацев: {draft.count('[Тип ')}"}
    if action == "audit":
        report = audit_project(project)
        return {"message": str(report["verdict"]), "report": report}
    if action == "finalize":
        finalize_markdown(project)
        return {"message": "final.md создан"}
    if action == "export_docx":
        path = export_docx(project)
        return {"message": f"DOCX создан: {path}"}
    if action == "refresh":
        state = refresh_stage(project)
        return {"message": f"Стадия: {state.stage.value}"}
    raise ValueError(f"Unknown action: {action}")


def _project_from_query(query: dict[str, list[str]]) -> Path:
    return _project_path(_one(query, "project"))


def _project_from_payload(payload: dict[str, Any]) -> Path:
    return _project_path(str(payload["project"]))


def _project_path(name: str) -> Path:
    project = (PROJECTS_ROOT / _clean_project_name(name)).resolve()
    if not _is_inside(project, PROJECTS_ROOT):
        raise ValueError("Project path is outside projects directory.")
    if not project.exists():
        raise ValueError(f"Project does not exist: {name}")
    return project


def _artifact_path(project: Path, name: str) -> Path:
    if name not in ARTIFACT_ATTRS:
        raise ValueError(f"Unknown artifact: {name}")
    paths = io.artifact_paths(project)
    path = Path(getattr(paths, ARTIFACT_ATTRS[name])).resolve()
    if not _is_inside(path, io.artifact_dir(project)):
        raise ValueError("Artifact path is outside project artifacts directory.")
    return path


def _clean_project_name(name: str) -> str:
    cleaned = "".join(ch for ch in name.strip() if ch.isalnum() or ch in ("-", "_"))
    if not cleaned:
        raise ValueError("Project name is empty.")
    return cleaned


def _one(query: dict[str, list[str]], key: str) -> str:
    values = query.get(key)
    if not values:
        raise ValueError(f"Missing query parameter: {key}")
    return values[0]


def _is_inside(path: Path, root: Path) -> bool:
    path = path.resolve()
    root = root.resolve()
    return path == root or root in path.parents


def _issue_to_dict(issue: Any) -> dict[str, str]:
    return {
        "code": issue.code,
        "message": issue.message,
        "artifact": issue.artifact,
        "severity": issue.severity,
    }


if __name__ == "__main__":
    raise SystemExit(main())
