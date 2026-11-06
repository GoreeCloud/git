"""Minimal, trusted environment for subprocesses executing installed Git.

The forced SSH command's SSH_ORIGINAL_COMMAND is parsed by the adapter, never
forwarded to Git. No caller-supplied PATH, LD_*, PYTHON*, or Git config values
are inherited by the subprocess. Python's own startup must be protected by
OpenSSH account and environment restrictions before this module is imported.
"""
from __future__ import annotations

import os
import shutil


def git_binary() -> str | None:
    """Resolve Git only from the platform's fixed system executable search path."""
    return shutil.which("git", path=os.defpath)


def git_environment(*, allow_ssh_protocol: bool = False) -> dict[str, str]:
    """Build a clean environment rather than trying to enumerate unsafe inputs."""
    env = {
        "PATH": os.defpath,
        "LC_ALL": "C",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_PAGER": "cat",
    }
    # OpenSSH Git protocol v2 is an explicitly understood, optional wire hint.
    # Do not allow arbitrary client-supplied GIT_PROTOCOL or other GIT_* keys.
    if allow_ssh_protocol and os.environ.get("GIT_PROTOCOL") == "version=2":
        env["GIT_PROTOCOL"] = "version=2"
    return env
