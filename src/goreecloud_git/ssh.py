"""Restricted OpenSSH forced-command transport for a single private repository.

This module intentionally does not create an SSH daemon, manage keys, or grant
OS permissions. The server administrator must separately configure each key
with a forced command and OpenSSH's restrict option.
"""
from __future__ import annotations

import os
from pathlib import Path
import shlex
import subprocess

from .core import GitError, Store, check_name


def parse_request(
    store: Store, original: str | None, allowed_repo: str, allow_push: bool = False
) -> tuple[str, Path]:
    """Resolve exactly one Git upload/receive-pack request; reject other commands."""
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
    # Git sends either the configured absolute remote path or a repository
    # basename. Never accept .., foreign repos, alternate spellings or flags.
    if parts[1] not in (str(path), f"{allowed_repo}.git"):
        raise GitError("SSH key cannot access the requested repository.")
    return parts[0], path


def serve_ssh(store: Store, allowed_repo: str, allow_push: bool = False) -> int:
    operation, path = parse_request(
        store, os.environ.get("SSH_ORIGINAL_COMMAND"), allowed_repo, allow_push
    )
    # Execute Git directly with inherited SSH stdin/stdout, never through a shell.
    # Git config and the environment must not override the server process.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_TERMINAL_PROMPT="0",
        GIT_NO_REPLACE_OBJECTS="1",
        GIT_OPTIONAL_LOCKS="0",
    )
    try:
        return subprocess.call(["git", operation.removeprefix("git-"), str(path)], env=env)
    except FileNotFoundError as exc:
        raise GitError("Git executable not found.") from exc
