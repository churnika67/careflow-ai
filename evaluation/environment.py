"""Bounded, non-identifying reproducibility metadata. Deliberately excludes
anything that identifies the machine or its operator — username, home
directory, hostname, MAC address, serial number, absolute filesystem paths,
environment variables, API keys, tokens, credentials. Only facts relevant to
interpreting a retrieval/latency result: interpreter, OS family, CPU shape,
and the exact pinned package versions already surfaced by the embedding/
reranker providers' own .describe() methods."""

import os
import platform
import sys
from importlib.metadata import PackageNotFoundError, version


def _package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def capture_environment(git_commit: str) -> dict:
    return {
        "python_version": sys.version.split()[0],
        "platform": platform.platform(terse=True),
        "cpu_architecture": platform.machine(),
        "cpu_count": os.cpu_count(),
        "git_commit": git_commit,
        "package_versions": {
            name: _package_version(name)
            for name in (
                "sentence-transformers",
                "transformers",
                "torch",
                "numpy",
                "qdrant-client",
                "psycopg",
                "fastapi",
                "pydantic",
            )
        },
    }
