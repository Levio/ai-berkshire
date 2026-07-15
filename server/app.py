"""FastAPI app for running AI Berkshire Claude Code skills from a browser."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
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
