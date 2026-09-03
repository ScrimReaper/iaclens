"""Debounced, burst-collapsing rebuild scheduler for `iaclens serve` auto-watch.

Trailing-edge debounce: a burst of `.notify()` calls within the debounce
window collapses to exactly one `rebuild_fn()` call. Only one rebuild runs
at a time; a `.notify()` that arrives while a rebuild is in flight schedules
exactly one follow-up rebuild (not one per notify).
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

MIN_DEBOUNCE_MS = 100
MAX_DEBOUNCE_MS = 60000
DEFAULT_DEBOUNCE_MS = 800
DEBOUNCE_ENV_VAR = "IACLENS_WATCH_DEBOUNCE_MS"
NO_WATCH_ENV_VAR = "IACLENS_NO_WATCH"

# Extensions the builder's parsers actually consume (see graph/builder.py).
PARSEABLE_EXTENSIONS = {".tf", ".yml", ".yaml"}


def clamp_debounce_ms(raw: int) -> int:
    """Clamp a debounce value (ms) to [MIN_DEBOUNCE_MS, MAX_DEBOUNCE_MS]."""
    return max(MIN_DEBOUNCE_MS, min(MAX_DEBOUNCE_MS, raw))


def debounce_ms_from_env() -> int:
    """Read IACLENS_WATCH_DEBOUNCE_MS (default 800), clamped to range."""
    raw = os.environ.get(DEBOUNCE_ENV_VAR)
    if raw is None:
        return DEFAULT_DEBOUNCE_MS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_DEBOUNCE_MS
    return clamp_debounce_ms(value)


class RebuildScheduler:
    """Debounces `.notify()` bursts into a single `rebuild_fn()` call.

    - `.notify(path)`: cancels any pending timer and arms a new one. A burst
      of notifies within `debounce_ms` collapses to one rebuild.
    - Only one rebuild runs at a time. A notify that arrives while a rebuild
      is running is recorded and triggers exactly one follow-up rebuild once
      the current one finishes.
    - `.stop()`: cancels any pending timer and makes the scheduler
      permanently inert -- a subsequent `.notify()` cannot re-arm a timer
      or schedule a rebuild.
    """

    def __init__(
        self,
        rebuild_fn: Callable[[], None],
        debounce_ms: int = DEFAULT_DEBOUNCE_MS,
        timer_factory: Callable = threading.Timer,
    ) -> None:
        self._rebuild_fn = rebuild_fn
        self._debounce_seconds = clamp_debounce_ms(debounce_ms) / 1000.0
        self._timer_factory = timer_factory

        self._lock = threading.Lock()
        self._timer = None
        self._rebuilding = False
        self._pending_during_rebuild = False
        self._stopped = False

    def notify(self, path: str | None = None) -> None:
        """Cancel any pending timer and arm a new debounce window.

        A no-op once `.stop()` has been called -- a straggling filesystem
        event after shutdown must not re-arm a timer or schedule a rebuild.
        """
        with self._lock:
            if self._stopped:
                return
            if self._rebuilding:
                # A rebuild is in flight; remember to run exactly one more
                # once it finishes, rather than arming a timer now (the
                # follow-up is armed by _run when the rebuild completes).
                self._pending_during_rebuild = True
                return
            self._arm_locked()

    def _arm_locked(self) -> None:
        """Cancel any existing timer and start a fresh one. Caller holds lock."""
        if self._timer is not None:
            self._timer.cancel()
        timer = self._timer_factory(self._debounce_seconds, self._run)
        self._timer = timer
        timer.start()

    def _run(self) -> None:
        with self._lock:
            self._timer = None
            if self._rebuilding:
                # A rebuild is already in flight (e.g. a notify() re-armed a
                # second timer before this one's .cancel() could take
                # effect). Do NOT start a second concurrent rebuild; just
                # record that one more run is owed once the current one
                # finishes.
                self._pending_during_rebuild = True
                return
            self._rebuilding = True
            self._pending_during_rebuild = False

        try:
            self._rebuild_fn()
        finally:
            with self._lock:
                self._rebuilding = False
                if self._pending_during_rebuild and not self._stopped:
                    self._pending_during_rebuild = False
                    self._arm_locked()

    def stop(self) -> None:
        """Cancel any pending timer and make the scheduler permanently inert.

        After `.stop()`, `.notify()` is a no-op: it cannot re-arm a timer or
        schedule a follow-up rebuild, even one already pending from a notify
        that arrived while a rebuild was in flight.
        """
        with self._lock:
            self._stopped = True
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None


def _load_infraignore_spec(root: Path) -> Any:
    """Load `.infraignore` from `root`, mirroring GraphBuilder's own logic."""
    ignore_file = root / ".infraignore"
    if not ignore_file.exists():
        return None
    try:
        import pathspec

        return pathspec.PathSpec.from_lines(
            "gitwildmatch", ignore_file.read_text().splitlines()
        )
    except Exception:
        return None


def should_trigger(path: Path, root: Path) -> bool:
    """True if a change to `path` (under `root`) should trigger a rebuild.

    A file triggers a rebuild only if it is one the builder would actually
    parse (`.tf`/`.yml`/`.yaml`), it is not under `iaclens-out/`, `.git/`,
    or any dot-directory, and it is not excluded by the repo's
    `.infraignore`. This keeps the watcher from ever rebuilding in a loop
    off its own output.
    """
    path = Path(path)
    if path.suffix not in PARSEABLE_EXTENSIONS:
        return False

    try:
        rel = path.relative_to(root)
    except ValueError:
        return False

    for part in rel.parts[:-1]:
        if part == "iaclens-out" or part.startswith("."):
            return False

    spec = _load_infraignore_spec(Path(root))
    if spec is not None:
        try:
            if spec.match_file(str(rel)):
                return False
        except Exception:
            pass

    return True


def start_watching(project_root: Path, builder: Any, scheduler: Any) -> Observer:
    """Watch `project_root` for changes, notifying `scheduler` on each one.

    Wires a `watchdog` handler that calls `scheduler.notify(path)` only for
    files `should_trigger` accepts. Returns a started `Observer`; the
    caller owns its lifecycle (`.stop()` + `.join()` on shutdown).
    """
    project_root = Path(project_root)

    class _RebuildHandler(FileSystemEventHandler):
        def _maybe_notify(self, src_path: str) -> None:
            if should_trigger(Path(src_path), project_root):
                scheduler.notify(src_path)

        def on_modified(self, event) -> None:  # type: ignore[override]
            if event.is_directory:
                return
            self._maybe_notify(event.src_path)

        def on_created(self, event) -> None:  # type: ignore[override]
            if event.is_directory:
                return
            self._maybe_notify(event.src_path)

        def on_moved(self, event) -> None:  # type: ignore[override]
            if event.is_directory:
                return
            self._maybe_notify(event.dest_path)

    observer = Observer()
    observer.schedule(_RebuildHandler(), str(project_root), recursive=True)
    observer.start()
    return observer
