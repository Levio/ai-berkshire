"""Configuration for the AI Berkshire web skill runner."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    repo_root: Path
    skills_dir: Path
    reports_dir: Path
    var_dir: Path
    jobs_dir: Path
    claude_cli: str
    claude_model: str | None
    job_timeout_seconds: int
    max_argument_length: int
    permission_mode: str
    skip_permissions: bool

    @classmethod
    def from_env(cls) -> "Settings":
        repo_root = Path(os.getenv("AI_BERKSHIRE_ROOT", Path(__file__).resolve().parents[1])).resolve()
        var_dir = Path(os.getenv("AI_BERKSHIRE_VAR_DIR", repo_root / "server" / "var")).resolve()
        claude_cli = os.getenv("CLAUDE_CLI", shutil.which("claude") or "claude")
        claude_model = os.getenv("CLAUDE_MODEL")
        timeout = int(os.getenv("AI_BERKSHIRE_JOB_TIMEOUT", "3600"))
        max_argument_length = int(os.getenv("AI_BERKSHIRE_MAX_ARGUMENT_LENGTH", "4000"))
        permission_mode = os.getenv("AI_BERKSHIRE_PERMISSION_MODE", "default")
        skip_permissions = os.getenv("AI_BERKSHIRE_SKIP_PERMISSIONS", "0").lower() in {"1", "true", "yes"}

        return cls(
            repo_root=repo_root,
            skills_dir=(repo_root / "skills").resolve(),
            reports_dir=(repo_root / "reports").resolve(),
            var_dir=var_dir,
            jobs_dir=(var_dir / "jobs").resolve(),
            claude_cli=claude_cli,
            claude_model=claude_model,
            job_timeout_seconds=timeout,
            max_argument_length=max_argument_length,
            permission_mode=permission_mode,
            skip_permissions=skip_permissions,
        )

    def ensure_runtime_dirs(self) -> None:
        self.var_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)


settings = Settings.from_env()
