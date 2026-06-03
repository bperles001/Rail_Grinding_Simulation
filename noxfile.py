"""Automation entry points for linting, typing, and tests."""

from __future__ import annotations

import os
from pathlib import Path

import nox

nox.options.sessions = ("lint", "typecheck", "tests")

REPO_ROOT = Path(__file__).parent.resolve()
IMPORT_ROOT = str(REPO_ROOT)


def _ensure_src_on_path(session: nox.Session) -> None:
    """Guarantee that the in-repo packages are importable inside sessions."""
    existing = session.env.get("PYTHONPATH", "")
    paths = [IMPORT_ROOT]
    if existing:
        paths.append(existing)
    session.env["PYTHONPATH"] = os.pathsep.join(paths)


@nox.session(reuse_venv=True)
def lint(session: nox.Session) -> None:
    """Run Ruff for formatting and static analysis."""
    _ensure_src_on_path(session)
    session.install("ruff>=0.5.5")
    session.run("ruff", "check", "src", "tests", "streamlit_app.py", *session.posargs)


@nox.session(reuse_venv=True)
def typecheck(session: nox.Session) -> None:
    """Execute mypy against the source tree."""
    _ensure_src_on_path(session)
    session.install("-e", ".[dev]")
    session.run("mypy", "src", *session.posargs)


@nox.session(reuse_venv=True)
def tests(session: nox.Session) -> None:
    """Execute the pytest suite with UI/runtime dependencies installed."""
    _ensure_src_on_path(session)
    session.install("-e", ".[dev,ui]")
    session.run("pytest", *session.posargs)
