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

MIN_DEBOUNCE_MS = 100
MAX_DEBOUNCE_MS = 60000
DEFAULT_DEBOUNCE_MS = 800
DEBOUNCE_ENV_VAR = "IACLENS_WATCH_DEBOUNCE_MS"


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
    - `.stop()`: cancels any pending timer.
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

    def notify(self, path: str | None = None) -> None:
        """Cancel any pending timer and arm a new debounce window."""
        with self._lock:
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
            self._rebuilding = True
            self._pending_during_rebuild = False

        try:
            self._rebuild_fn()
        finally:
            with self._lock:
                self._rebuilding = False
                if self._pending_during_rebuild:
                    self._pending_during_rebuild = False
                    self._arm_locked()

    def stop(self) -> None:
        """Cancel any pending timer."""
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
