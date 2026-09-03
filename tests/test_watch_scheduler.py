from infra_graph.watch import RebuildScheduler, clamp_debounce_ms


class FakeTimer:
    """Records the callback; fire() runs it. Mimics threading.Timer API."""

    pending = []

    def __init__(self, interval, fn):
        self.fn = fn
        self.cancelled = False
        FakeTimer.pending.append(self)

    def start(self):
        pass

    def cancel(self):
        self.cancelled = True

    @classmethod
    def fire_latest(cls):
        t = cls.pending[-1]
        if not t.cancelled:
            t.fn()


def test_burst_collapses_to_one_rebuild():
    FakeTimer.pending = []
    calls = []
    s = RebuildScheduler(lambda: calls.append(1), debounce_ms=800, timer_factory=FakeTimer)
    for _ in range(5):
        s.notify("a.tf")  # burst: 5 notifies re-arm the single timer
    assert len(FakeTimer.pending) == 5
    # every superseded timer must actually have been cancelled by the burst;
    # only the last one (the one that will really fire) survives uncancelled
    for t in FakeTimer.pending[:-1]:
        assert t.cancelled is True
    assert FakeTimer.pending[-1].cancelled is False
    # firing every pending timer (each respecting its own cancellation, like
    # real threading.Timer instances would) must still yield exactly one
    # rebuild call -- this goes red if the .cancel() call were ever removed
    for t in FakeTimer.pending:
        if not t.cancelled:
            t.fn()
    assert calls == [1]  # exactly one rebuild


def test_clamp_debounce():
    assert clamp_debounce_ms(10) == 100
    assert clamp_debounce_ms(99999) == 60000
    assert clamp_debounce_ms(800) == 800


def test_notify_during_rebuild_schedules_one_followup():
    FakeTimer.pending = []
    calls = []

    def rebuild():
        calls.append(1)
        if len(calls) == 1:
            # simulate a notify arriving while the rebuild is in flight
            s.notify("b.tf")

    s = RebuildScheduler(rebuild, debounce_ms=800, timer_factory=FakeTimer)
    s.notify("a.tf")
    FakeTimer.fire_latest()  # runs rebuild(), which notifies again mid-run
    assert calls == [1]
    # exactly one follow-up timer should now be pending
    FakeTimer.fire_latest()
    assert calls == [1, 1]


def test_run_guards_against_concurrent_second_timer_firing():
    """Reproduces the documented race: threading.Timer.cancel() is a no-op
    once the timer has already committed to firing, so notify() can end up
    having armed a second timer that fires while the first rebuild is still
    running. _run() must treat that as "one more rebuild owed", not start a
    second concurrent rebuild.
    """
    FakeTimer.pending = []
    calls = []
    second_timer = None

    def rebuild():
        calls.append(1)
        if len(calls) == 1:
            # Simulate the second timer's callback firing (e.g. on its own
            # thread) while this first rebuild is still in flight.
            second_timer.fn()

    s = RebuildScheduler(rebuild, debounce_ms=800, timer_factory=FakeTimer)
    s.notify("a.tf")
    first_timer = FakeTimer.pending[-1]
    # Simulate notify()'s cancel() being a no-op: a second timer still gets
    # armed even though the first "should" have been superseded.
    second_timer = FakeTimer(0.8, s._run)

    first_timer.fn()  # starts the rebuild; rebuild() fires second_timer mid-run
    assert calls == [1]  # NOT [1, 1] -- no concurrent second rebuild call

    # exactly one follow-up rebuild should now be queued
    FakeTimer.fire_latest()
    assert calls == [1, 1]


def test_stop_cancels_pending_timer():
    FakeTimer.pending = []
    calls = []
    s = RebuildScheduler(lambda: calls.append(1), debounce_ms=800, timer_factory=FakeTimer)
    s.notify("a.tf")
    s.stop()
    assert FakeTimer.pending[-1].cancelled is True


def test_notify_after_stop_does_not_rearm():
    """A .notify() after .stop() must be fully inert -- no new timer, no
    rebuild -- so serve's shutdown path can't be re-armed by a straggling
    filesystem event.
    """
    FakeTimer.pending = []
    calls = []
    s = RebuildScheduler(lambda: calls.append(1), debounce_ms=800, timer_factory=FakeTimer)
    s.notify("a.tf")
    s.stop()
    timers_before = len(FakeTimer.pending)

    s.notify("b.tf")
    assert len(FakeTimer.pending) == timers_before  # no new timer armed

    # even if a stray timer somehow fired, no rebuild should have run
    assert calls == []


def test_notify_after_stop_during_rebuild_does_not_schedule_followup():
    """.stop() called while a rebuild is in flight must prevent the
    in-flight rebuild's completion from arming a follow-up timer, even
    though a notify() arrived mid-rebuild.
    """
    FakeTimer.pending = []
    calls = []

    def rebuild():
        calls.append(1)
        if len(calls) == 1:
            s.notify("b.tf")  # arrives mid-rebuild
            s.stop()  # shutdown races in before the rebuild finishes

    s = RebuildScheduler(rebuild, debounce_ms=800, timer_factory=FakeTimer)
    s.notify("a.tf")
    FakeTimer.fire_latest()  # runs rebuild(); notify()+stop() happen inside
    assert calls == [1]
    # no follow-up timer should have been armed once stopped
    assert len(FakeTimer.pending) == 1
