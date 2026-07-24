"""Authentication setup for this application's separate TIDAL session."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable


def session_file_path() -> Path:
    """Return the private, app-specific location for persisted OAuth tokens."""
    state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return state_home / "tidal-dedupe" / "session.json"


def _secure_session_path(path: Path) -> None:
    """Create the token directory/file and correct their Unix permissions."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    # login_session_file creates this file itself on some tidalapi versions.
    # Pre-creating it prevents a window with default, world-readable umask mode.
    path.touch(exist_ok=True)
    path.chmod(0o600)


def _new_session() -> Any:
    try:
        import tidalapi
    except ImportError as exc:  # pragma: no cover - exercised at installation time
        raise RuntimeError("tidalapi is required; install the tidal-dedupe package") from exc
    return tidalapi.Session(tidalapi.Config(item_limit=10_000))


def load_session(
    path: Path | None = None,
    *,
    session_factory: Callable[[], Any] | None = None,
) -> Any:
    """Load or interactively create the saved PKCE session without exposing tokens."""
    target = path or session_file_path()
    _secure_session_path(target)
    session = (session_factory or _new_session)()
    session.login_session_file(target, do_pkce=True)
    # The library may replace the file while refreshing credentials.
    target.chmod(0o600)
    return session
