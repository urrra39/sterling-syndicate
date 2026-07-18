from __future__ import annotations

"""Ephemeral Docker sandbox with dynamic RAM/timeout by language weight.

No network. Pure Python → 512MB/60s. Node/Rust/heavy → 2–4GB / 5 min.
"""

import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from app.core.config import settings

DEFAULT_IMAGE = "python:3.11-slim"

# Unprivileged uid/gid the sandbox container runs as (mirrors --user below).
SANDBOX_UID = 65532
SANDBOX_GID = 65532


@dataclass(frozen=True)
class SandboxProfile:
    language: str
    memory: str
    timeout_sec: int
    image: str
    entry: Tuple[str, ...]  # command after image
    filename: str


@dataclass(frozen=True)
class SandboxResult:
    ok: bool
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    engine: str  # docker | subprocess | unavailable
    duration_ms: int
    memory: str = "512m"
    language: str = "python"
    timeout_sec: int = 60

    @property
    def memory_mb(self) -> int:
        m = (self.memory or "512m").lower().strip()
        if m.endswith("g"):
            return int(float(m[:-1]) * 1024)
        if m.endswith("m"):
            return int(float(m[:-1]))
        return 512


def detect_language(code: str, *, hint: str = "") -> str:
    """AST/heuristic language detection for resource profiling."""
    h = (hint or "").lower().strip()
    if h in {"python", "node", "javascript", "typescript", "rust", "go"}:
        return "javascript" if h in {"node", "typescript"} else h

    t = code or ""
    # Explicit markers from Execution_Agent drafts
    if re.search(r"```(?:tsx?|jsx?|javascript|typescript)", t, re.I) or re.search(
        r"\b(?:require\(|from ['\"]react|next\.config|package\.json)\b", t
    ):
        return "javascript"
    if re.search(r"```rust|\bfn\s+main\s*\(|\bcargo\b|\buse\s+std::", t, re.I):
        return "rust"
    if re.search(r"```go|\bpackage\s+main\b|\bfunc\s+main\s*\(", t):
        return "go"
    if re.search(r"\bdef\s+\w+\s*\(|\bimport\s+\w+|\bprint\s*\(", t):
        return "python"
    return "python"


def is_heavy_framework(code: str, language: str) -> bool:
    t = (code or "").lower()
    if language in {"rust", "go"}:
        return True
    if language == "javascript":
        return any(
            k in t
            for k in (
                "next",
                "npm install",
                "yarn",
                "webpack",
                "vite",
                "react",
                "nestjs",
                "prisma",
            )
        )
    # Python heavy: compilers / native builds
    return any(k in t for k in ("cython", "pybind", "torch", "tensorflow", "cargo", "cmake"))


def profile_for_code(code: str, *, language_hint: str = "") -> SandboxProfile:
    lang = detect_language(code, hint=language_hint)
    heavy = is_heavy_framework(code, lang)

    if lang == "rust":
        return SandboxProfile(
            language="rust",
            memory="4g" if heavy else "2g",
            timeout_sec=300,
            image=settings.sandbox_rust_image or "rust:1.83-slim",
            entry=("sh", "-c", "rustc main.rs -o main && ./main"),
            filename="main.rs",
        )
    if lang in {"javascript", "typescript", "node"}:
        return SandboxProfile(
            language="javascript",
            memory="4g" if heavy else "2g",
            timeout_sec=300,
            image=settings.sandbox_node_image or "node:20-slim",
            entry=("node", "main.js"),
            filename="main.js",
        )
    # Pure / simple Python
    return SandboxProfile(
        language="python",
        memory="512m",
        timeout_sec=60,
        image=settings.sandbox_image or DEFAULT_IMAGE,
        entry=("python", "-u", "main.py"),
        filename="main.py",
    )


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        r = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=8,
            env=_docker_env(),
        )
        return r.returncode == 0
    except Exception:
        return False


def _docker_env() -> dict:
    env = os.environ.copy()
    host = settings.docker_host or os.environ.get("DOCKER_HOST", "")
    if host:
        env["DOCKER_HOST"] = host
    if host.startswith("tcp://") and "DOCKER_TLS_VERIFY" not in env:
        env.pop("DOCKER_TLS_VERIFY", None)
        env.pop("DOCKER_CERT_PATH", None)
    return env


def run_in_sandbox(
    code: str,
    *,
    language: str = "",
    timeout_sec: Optional[int] = None,
    memory: Optional[str] = None,
    image: Optional[str] = None,
) -> SandboxResult:
    """Execute untrusted code with dynamic resources. Never grants network."""
    code = (code or "")[:200_000]
    profile = profile_for_code(code, language_hint=language)
    mem = memory or profile.memory
    to = timeout_sec or profile.timeout_sec
    img = image or profile.image

    if docker_available():
        return _run_docker(code, profile=profile, timeout_sec=to, memory=mem, image=img)
    if settings.sandbox_allow_subprocess_fallback and profile.language == "python":
        r = _run_subprocess(code, timeout_sec=to)
        return SandboxResult(
            ok=r.ok,
            exit_code=r.exit_code,
            stdout=r.stdout,
            stderr=r.stderr,
            timed_out=r.timed_out,
            engine=r.engine,
            duration_ms=r.duration_ms,
            memory=mem,
            language=profile.language,
            timeout_sec=to,
        )
    return SandboxResult(
        ok=False,
        exit_code=-1,
        stdout="",
        stderr="Docker unavailable (or non-Python fallback disabled)",
        timed_out=False,
        engine="unavailable",
        duration_ms=0,
        memory=mem,
        language=profile.language,
        timeout_sec=to,
    )


def _run_docker(
    code: str,
    *,
    profile: SandboxProfile,
    timeout_sec: int,
    memory: str,
    image: str,
) -> SandboxResult:
    cpus = "1.0" if memory in {"2g", "4g"} else "0.5"
    pids = "256" if memory in {"2g", "4g"} else "64"
    tmpfs_size = "512m" if memory in {"2g", "4g"} else "64m"

    with tempfile.TemporaryDirectory(prefix="pp-sandbox-") as tmp:
        script = Path(tmp) / profile.filename
        # Strip markdown fences for execution
        body = re.sub(r"^```(?:\w+)?\s*", "", code.strip())
        body = re.sub(r"\s*```$", "", body)
        script.write_text(body, encoding="utf-8")

        # Host perms for the read-only bind mount. Preferred: chown to the
        # sandbox uid (65532) and keep owner-only 0o700/0o600. If the host
        # process is not root, chown raises EPERM — in that case fall back to
        # world-READABLE 0o755/0o644 so the unprivileged container uid can read
        # /work/main.py. Never 0o777: the mount is ro and nothing needs write.
        try:
            os.chown(tmp, SANDBOX_UID, SANDBOX_GID)
            os.chown(script, SANDBOX_UID, SANDBOX_GID)
            os.chmod(tmp, 0o0700)
            os.chmod(script, 0o0600)
        except (PermissionError, OSError):
            # Non-root host (local dev / CI runner): container uid 65532 is
            # "other", so grant read+execute on dir, read on file.
            os.chmod(tmp, 0o0755)
            os.chmod(script, 0o0644)

        container_name = f"pp-sandbox-{os.getpid()}-{int(time.monotonic() * 1000)}"
        cmd = [
            "docker",
            "run",
            "--name",
            container_name,
            "--network",
            "none",
            "--user",
            "65532:65532",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--memory",
            memory,
            "--memory-swap",
            memory,
            "--cpus",
            cpus,
            "--pids-limit",
            pids,
            "--read-only",
            "--tmpfs",
            f"/tmp:rw,noexec,nosuid,size={tmpfs_size}",
            "-v",
            f"{tmp}:/work:ro",
            "-w",
            "/work",
            image,
            *profile.entry,
        ]
        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                timeout=timeout_sec,
                env=_docker_env(),
                text=True,
            )
            ms = int((time.monotonic() - t0) * 1000)
            return SandboxResult(
                ok=proc.returncode == 0,
                exit_code=proc.returncode,
                stdout=(proc.stdout or "")[:50_000],
                stderr=(proc.stderr or "")[:20_000],
                timed_out=False,
                engine="docker",
                duration_ms=ms,
                memory=memory,
                language=profile.language,
                timeout_sec=timeout_sec,
            )
        except subprocess.TimeoutExpired as exc:
            ms = int((time.monotonic() - t0) * 1000)
            return SandboxResult(
                ok=False,
                exit_code=-1,
                stdout=(exc.stdout or "")[:50_000] if isinstance(exc.stdout, str) else "",
                stderr=f"Sandbox hard timeout after {timeout_sec}s ({memory})",
                timed_out=True,
                engine="docker",
                duration_ms=ms,
                memory=memory,
                language=profile.language,
                timeout_sec=timeout_sec,
            )
        finally:
            # Deterministic cleanup: remove the container even on timeout/exception
            # to prevent orphan containers from accumulating.
            try:
                subprocess.run(
                    ["docker", "rm", "-f", container_name],
                    capture_output=True,
                    timeout=10,
                    env=_docker_env(),
                )
            except Exception:
                pass


def _run_subprocess(code: str, *, timeout_sec: int) -> SandboxResult:
    """Dev/test fallback — still hard-timeout; NOT a security boundary."""
    with tempfile.TemporaryDirectory(prefix="pp-local-") as tmp:
        script = Path(tmp) / "main.py"
        script.write_text(code, encoding="utf-8")
        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                ["python", "-u", str(script)],
                capture_output=True,
                timeout=timeout_sec,
                text=True,
                cwd=tmp,
            )
            ms = int((time.monotonic() - t0) * 1000)
            return SandboxResult(
                ok=proc.returncode == 0,
                exit_code=proc.returncode,
                stdout=(proc.stdout or "")[:50_000],
                stderr=(proc.stderr or "")[:20_000],
                timed_out=False,
                engine="subprocess",
                duration_ms=ms,
                timeout_sec=timeout_sec,
            )
        except subprocess.TimeoutExpired:
            ms = int((time.monotonic() - t0) * 1000)
            return SandboxResult(
                ok=False,
                exit_code=-1,
                stdout="",
                stderr=f"Subprocess hard timeout after {timeout_sec}s",
                timed_out=True,
                engine="subprocess",
                duration_ms=ms,
                timeout_sec=timeout_sec,
            )
