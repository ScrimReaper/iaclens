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
    FakeTimer.fire_latest()  # quiet window elapses once
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


def test_stop_cancels_pending_timer():
    FakeTimer.pending = []
    calls = []
    s = RebuildScheduler(lambda: calls.append(1), debounce_ms=800, timer_factory=FakeTimer)
    s.notify("a.tf")
    s.stop()
    assert FakeTimer.pending[-1].cancelled is True
