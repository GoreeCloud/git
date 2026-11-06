"""Restricted OpenSSH forced-command transport for a single private repository.

This module does not create an SSH daemon, authenticate users, or manage keys.
OpenSSH's authorized_keys forced command and restrict option are prerequisites.
"""
from __future__ import annotations

import os
from pathlib import Path
import resource
import shlex
import signal
import subprocess

from .core import GitError, Store, check_name
from .git_environment import git_binary, git_environment

DEFAULT_WALL_SECONDS = 600
DEFAULT_CPU_SECONDS = 300
DEFAULT_MEMORY_MIB = 2048


def parse_request(
    store: Store, original: str | None, allowed_repo: str, allow_push: bool = False
) -> tuple[str, Path]:
    """Resolve one Git transport request, refusing every other command and path."""
    check_name(allowed_repo)
    if not original or len(original) > 2048 or "\x00" in original or any(c in original for c in "\r\n"):
        raise GitError("SSH request is missing or invalid.")
    try:
        parts = shlex.split(original, posix=True)
    except ValueError as exc:
        raise GitError("Malformed Git SSH request.") from exc
    if len(parts) != 2 or parts[0] not in ("git-upload-pack", "git-receive-pack"):
        raise GitError("SSH command is not permitted.")
    if parts[0] == "git-receive-pack" and not allow_push:
        raise GitError("SSH key is read-only.")
    path = store.existing(allowed_repo)
    if parts[1] not in (str(path), f"{allowed_repo}.git"):
        raise GitError("SSH key cannot access the requested repository.")
    return parts[0], path


def validate_limits(wall_seconds: int, cpu_seconds: int, memory_mib: int) -> None:
    """Require bounded, positive resource budgets, not unbounded CLI overrides."""
    for value, minimum, maximum, label in (
        (wall_seconds, 1, 7200, "wall time"),
        (cpu_seconds, 1, 3600, "CPU time"),
        (memory_mib, 128, 16384, "memory"),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ValueError(f"Invalid SSH {label} limit ({minimum}-{maximum}).")


def _child_limits(cpu_seconds: int, memory_mib: int) -> None:
    """Only the child receives these POSIX limits; the CLI parent is unchanged."""
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
    address_space = memory_mib * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (address_space, address_space))


def _run_transport(
    argv: list[str], env: dict[str, str], wall_seconds: int,
    cpu_seconds: int, memory_mib: int
) -> int:
    """Stream the Git wire protocol directly, killing its process group on timeout."""
    validate_limits(wall_seconds, cpu_seconds, memory_mib)
    if os.name != "posix":
        raise GitError("Restricted SSH resource limits require a POSIX host.")
    try:
        proc = subprocess.Popen(
            argv, env=env, start_new_session=True,
            preexec_fn=lambda: _child_limits(cpu_seconds, memory_mib)
        )
    except FileNotFoundError as exc:
        raise GitError("Git executable not found.") from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitError("Cannot start bounded SSH Git subprocess.") from exc
    try:
        return proc.wait(timeout=wall_seconds)
    except subprocess.TimeoutExpired as exc:
        raise GitError("SSH Git operation timed out.") from exc
    finally:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        proc.wait()


def serve_ssh(
    store: Store, allowed_repo: str, allow_push: bool = False,
    wall_seconds: int = DEFAULT_WALL_SECONDS,
    cpu_seconds: int = DEFAULT_CPU_SECONDS,
    memory_mib: int = DEFAULT_MEMORY_MIB,
) -> int:
    # Validate before accepting an untrusted SSH command.
    validate_limits(wall_seconds, cpu_seconds, memory_mib)
    operation, path = parse_request(
        store, os.environ.get("SSH_ORIGINAL_COMMAND"), allowed_repo, allow_push
    )
    # Git never runs inside an interpolated shell. Its trusted executable
    # path and minimal child environment exclude client-influenced PATH,
    # dynamic linker, Python, and Git configuration overrides. The SSH
    # protocol v2 hint is forwarded only if it is exactly understood.
    executable = git_binary()
    if executable is None:
        raise GitError("Git is not installed in the trusted system path.")
    return _run_transport(
        [executable, operation.removeprefix("git-"), str(path)],
        git_environment(allow_ssh_protocol=True),
        wall_seconds, cpu_seconds, memory_mib,
    )
