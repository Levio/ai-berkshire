"""FastAPI app for running AI Berkshire Claude Code skills from a browser."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import settings
from .runner import JobManager
from .skills import SkillRegistry

app = FastAPI(title="AI Berkshire Skill Runner")
registry = SkillRegistry(settings.skills_dir)
manager = JobManager(settings, registry)
static_dir = Path(__file__).resolve().parent / "static"


class CreateJobRequest(BaseModel):
    skill_name: str = Field(..., min_length=1, max_length=80, pattern=r"^[a-z0-9-]+$")
    arguments: str = Field(default="", max_length=settings.max_argument_length)


def _report_metadata(path: Path) -> dict[str, object]:
    stat = path.stat()
    rel_path = path.relative_to(settings.reports_dir).as_posix()
    parts = Path(rel_path).parts
    return {
        "id": rel_path,
        "name": path.name,
        "path": rel_path,
        "group": parts[0] if len(parts) > 1 else "根目录",
        "title": _extract_title(path) or path.stem,
        "size": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


def _extract_title(path: Path) -> str | None:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for index, line in enumerate(fh):
                if index >= 80:
                    break
                title = line.strip()
                if title.startswith("# "):
                    return title[2:].strip() or None
    except OSError:
        return None
    return None


def _list_report_entries(query: str | None = None) -> list[dict[str, object]]:
    reports_dir = settings.reports_dir.resolve()
    if not reports_dir.exists():
        return []

    entries: list[dict[str, object]] = []
    needle = query.casefold().strip() if query else ""
    for path in reports_dir.rglob("*.md"):
        if not path.is_file():
            continue
        metadata = _report_metadata(path)
        if needle:
            haystack = " ".join(str(metadata[key]) for key in ("path", "name", "group", "title")).casefold()
            if needle not in haystack:
                continue
        entries.append(metadata)
    entries.sort(key=lambda item: str(item["modified_at"]), reverse=True)
    entries.sort(key=lambda item: (0 if item["group"] == "AI产业研究" else 1, str(item["group"])))
    return entries


def _resolve_report_path(report_path: str) -> Path | None:
    if not report_path or "\x00" in report_path:
        return None
    candidate = Path(report_path)
    if candidate.is_absolute() or ".." in candidate.parts or candidate.suffix.lower() != ".md":
        return None

    reports_dir = settings.reports_dir.resolve()
    path = (reports_dir / candidate).resolve()
    try:
        path.relative_to(reports_dir)
    except ValueError:
        return None
    if not path.is_file():
        return None
    return path


@app.on_event("startup")
async def startup() -> None:
    settings.ensure_runtime_dirs()
    manager.start()


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/skills")
async def list_skills() -> dict[str, object]:
    return {"skills": [skill.__dict__ for skill in registry.list_skills()]}


@app.get("/api/skills/{name}")
async def get_skill(name: str) -> dict[str, object]:
    skill = registry.get(name)
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill.__dict__


@app.get("/api/reports")
async def list_reports(q: Optional[str] = Query(default=None, max_length=120)) -> dict[str, object]:
    return {"reports": _list_report_entries(q)}


@app.get("/api/reports/content")
async def get_report_content(path: str = Query(..., min_length=1, max_length=400)) -> dict[str, object]:
    report_path = _resolve_report_path(path)
    if report_path is None:
        raise HTTPException(status_code=404, detail="Report not found")
    try:
        content = report_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise HTTPException(status_code=404, detail="Report not found") from exc
    return {"report": _report_metadata(report_path), "content": content}


@app.get("/api/reports/raw")
async def get_report_raw(path: str = Query(..., min_length=1, max_length=400)) -> FileResponse:
    report_path = _resolve_report_path(path)
    if report_path is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return FileResponse(report_path, media_type="text/markdown; charset=utf-8", filename=report_path.name)


@app.post("/api/jobs")
async def create_job(request: CreateJobRequest) -> dict[str, object]:
    try:
        job = await manager.create_job(request.skill_name, request.arguments)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job.to_dict()


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> dict[str, object]:
    job = manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str) -> StreamingResponse:
    if manager.get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return StreamingResponse(manager.events(job_id), media_type="text/event-stream")


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str) -> dict[str, object]:
    job = await manager.cancel_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()


@app.get("/api/jobs/{job_id}/artifacts/{artifact_id}")
async def download_artifact(job_id: str, artifact_id: str) -> FileResponse:
    path = manager.resolve_artifact(job_id, artifact_id)
    if path is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return FileResponse(path, media_type="text/markdown; charset=utf-8", filename=path.name)


app.mount("/static", StaticFiles(directory=static_dir), name="static")
