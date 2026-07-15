"""Background job runner for Claude Code skill invocations."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Literal

from .config import Settings
from .skills import SkillRegistry

JobStatus = Literal["queued", "running", "succeeded", "failed", "canceled"]


@dataclass(frozen=True)
class Artifact:
    id: str
    name: str
    path: str
    size: int
    modified_at: str


@dataclass
class Job:
    id: str
    skill_name: str
    arguments: str
    status: JobStatus
    created_at: str
    updated_at: str
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    error: str | None = None
    log_path: str | None = None
    artifacts: list[Artifact] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["artifacts"] = [asdict(artifact) for artifact in self.artifacts]
        return data


class JobManager:
    """Serial queue that runs one Claude Code skill at a time."""

    def __init__(self, settings: Settings, registry: SkillRegistry):
        self.settings = settings
        self.registry = registry
        self.settings.ensure_runtime_dirs()
        self._jobs: dict[str, Job] = {}
        self._queues: dict[str, asyncio.Queue[str | None]] = {}
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._worker_task: asyncio.Task[None] | None = None
        self._queue: asyncio.Queue[str] = asyncio.Queue()

    def start(self) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker())

    async def create_job(self, skill_name: str, arguments: str) -> Job:
        self.registry.require(skill_name)
        self._validate_arguments(arguments)

        now = _now()
        job_id = uuid.uuid4().hex[:12]
        job_dir = self.settings.jobs_dir / job_id
        job_dir.mkdir(parents=True, exist_ok=False)
        log_path = job_dir / "run.log"

        job = Job(
            id=job_id,
            skill_name=skill_name,
            arguments=arguments.strip(),
            status="queued",
            created_at=now,
            updated_at=now,
            log_path=str(log_path),
        )
        self._jobs[job_id] = job
        self._queues[job_id] = asyncio.Queue()
        await self._append_event(job_id, "status", {"status": "queued"})
        await self._queue.put(job_id)
        return job

    def get_job(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    async def cancel_job(self, job_id: str) -> Job | None:
        job = self._jobs.get(job_id)
        if job is None:
            return None
        process = self._processes.get(job_id)
        if process and process.returncode is None:
            process.terminate()
            job.status = "canceled"
            job.updated_at = _now()
            await self._append_event(job_id, "status", {"status": "canceled"})
        elif job.status == "queued":
            job.status = "canceled"
            job.finished_at = _now()
            job.updated_at = job.finished_at
            await self._append_event(job_id, "status", {"status": "canceled"})
            await self._close_events(job_id)
        return job

    async def events(self, job_id: str) -> AsyncIterator[str]:
        job = self._jobs.get(job_id)
        if job is None:
            return
        queue = self._queues.setdefault(job_id, asyncio.Queue())

        yield _sse("job", job.to_dict())
        log_path = Path(job.log_path) if job.log_path else None
        if log_path and log_path.exists():
            for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
                yield _sse("log", {"line": line})

        while True:
            event = await queue.get()
            if event is None:
                break
            yield event

    async def _worker(self) -> None:
        while True:
            job_id = await self._queue.get()
            job = self._jobs.get(job_id)
            if job is None or job.status == "canceled":
                continue
            await self._run_job(job)

    async def _run_job(self, job: Job) -> None:
        before = self._snapshot_reports()
        job.status = "running"
        job.started_at = _now()
        job.updated_at = job.started_at
        await self._append_event(job.id, "status", {"status": "running"})

        command = self._build_command(job.skill_name, job.arguments)
        await self._append_log(job.id, f"$ {' '.join(command)}")

        env = self._build_env()
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(self.settings.repo_root),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._processes[job.id] = process
            await asyncio.wait_for(self._stream_process(job.id, process), timeout=self.settings.job_timeout_seconds)
            job.exit_code = process.returncode
            if job.status != "canceled":
                job.status = "succeeded" if process.returncode == 0 else "failed"
        except TimeoutError:
            job.status = "failed"
            job.error = f"Job timed out after {self.settings.job_timeout_seconds} seconds"
            process = self._processes.get(job.id)
            if process and process.returncode is None:
                process.kill()
            await self._append_log(job.id, job.error)
        except FileNotFoundError:
            job.status = "failed"
            job.error = f"Claude CLI not found: {self.settings.claude_cli}"
            await self._append_log(job.id, job.error)
        except Exception as exc:  # noqa: BLE001 - preserve error in job log/API
            job.status = "failed"
            job.error = str(exc)
            await self._append_log(job.id, f"ERROR: {exc}")
        finally:
            self._processes.pop(job.id, None)
            job.finished_at = _now()
            job.updated_at = job.finished_at
            job.artifacts = self._collect_artifacts(before)
            await self._append_event(job.id, "status", job.to_dict())
            await self._close_events(job.id)

    async def _stream_process(self, job_id: str, process: asyncio.subprocess.Process) -> None:
        assert process.stdout is not None
        assert process.stderr is not None

        async def read_stream(stream: asyncio.StreamReader, prefix: str) -> None:
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip("\n")
                await self._append_log(job_id, f"{prefix}{text}")

        await asyncio.gather(read_stream(process.stdout, ""), read_stream(process.stderr, "[stderr] "))
        await process.wait()

    def _build_command(self, skill_name: str, arguments: str) -> list[str]:
        prompt = f"/{skill_name} {arguments}".strip()
        command = [self.settings.claude_cli, "--print"]
        if self.settings.claude_model:
            command.extend(["--model", self.settings.claude_model])
        if self.settings.permission_mode != "default":
            command.extend(["--permission-mode", self.settings.permission_mode])
        if self.settings.skip_permissions:
            command.append("--dangerously-skip-permissions")
        command.append(prompt)
        return command

    def _build_env(self) -> dict[str, str]:
        allowed = {
            "HOME",
            "PATH",
            "SHELL",
            "TERM",
            "LANG",
            "LC_ALL",
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_AUTH_TOKEN",
            "ANTHROPIC_BASE_URL",
            "ANTHROPIC_PROFILE",
            "ANTHROPIC_CONFIG_DIR",
            "CLAUDE_CODE_USE_BEDROCK",
            "CLAUDE_CODE_USE_VERTEX",
        }
        env = {key: value for key, value in os.environ.items() if key in allowed}
        env.setdefault("PATH", os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"))
        return env

    def _validate_arguments(self, arguments: str) -> None:
        if len(arguments) > self.settings.max_argument_length:
            raise ValueError(f"Arguments exceed {self.settings.max_argument_length} characters")
        if "\x00" in arguments:
            raise ValueError("Arguments contain null byte")

    def _snapshot_reports(self) -> dict[Path, float]:
        if not self.settings.reports_dir.exists():
            return {}
        return {path: path.stat().st_mtime for path in self.settings.reports_dir.rglob("*.md") if path.is_file()}

    def _collect_artifacts(self, before: dict[Path, float]) -> list[Artifact]:
        artifacts: list[Artifact] = []
        if not self.settings.reports_dir.exists():
            return artifacts
        for path in sorted(self.settings.reports_dir.rglob("*.md")):
            if not path.is_file():
                continue
            stat = path.stat()
            if path not in before or stat.st_mtime > before[path]:
                rel = path.relative_to(self.settings.repo_root)
                artifacts.append(
                    Artifact(
                        id=uuid.uuid4().hex[:12],
                        name=str(rel),
                        path=str(path.resolve()),
                        size=stat.st_size,
                        modified_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                    )
                )
        return artifacts

    def resolve_artifact(self, job_id: str, artifact_id: str) -> Path | None:
        job = self._jobs.get(job_id)
        if job is None:
            return None
        for artifact in job.artifacts:
            if artifact.id != artifact_id:
                continue
            path = Path(artifact.path).resolve()
            try:
                path.relative_to(self.settings.reports_dir)
            except ValueError:
                return None
            if path.is_file():
                return path
        return None

    async def _append_log(self, job_id: str, line: str) -> None:
        job = self._jobs[job_id]
        log_path = Path(job.log_path or self.settings.jobs_dir / job_id / "run.log")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        await self._append_event(job_id, "log", {"line": line})

    async def _append_event(self, job_id: str, event: str, payload: dict[str, object]) -> None:
        queue = self._queues.get(job_id)
        if queue is not None:
            await queue.put(_sse(event, payload))

    async def _close_events(self, job_id: str) -> None:
        queue = self._queues.get(job_id)
        if queue is not None:
            await queue.put(None)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sse(event: str, payload: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
