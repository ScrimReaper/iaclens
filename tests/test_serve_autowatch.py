from pathlib import Path

from infra_graph.watch import RebuildScheduler, should_trigger, start_watching


def test_ignores_output_and_git_and_nonparseable(tmp_path):
    root = tmp_path
    assert should_trigger(root / "roles/x/tasks/main.yml", root) is True
    assert should_trigger(root / "main.tf", root) is True
    assert should_trigger(root / "iaclens-out/graph.toon", root) is False
    assert should_trigger(root / ".git/index", root) is False
    assert should_trigger(root / "README.md", root) is False


def test_ignores_dotdirs_generally(tmp_path):
    root = tmp_path
    assert should_trigger(root / ".terraform/modules/main.tf", root) is False
    assert should_trigger(root / ".venv/lib/whatever.yaml", root) is False


def test_github_workflows_are_the_dotdir_exception(tmp_path):
    """.github/ mirrors the builder's own _collect_files exception: GitHub
    Actions workflows are parsed into the graph, so edits to them must
    trigger a rebuild too, unlike every other dot-directory."""
    root = tmp_path
    assert should_trigger(root / ".github/workflows/ci.yml", root) is True
    assert should_trigger(root / ".git/index", root) is False
    assert should_trigger(root / ".terraform/modules/main.tf", root) is False


def test_respects_infraignore(tmp_path):
    root = tmp_path
    (root / ".infraignore").write_text("dist/\n*.tfstate\n")
    assert should_trigger(root / "dist/generated.tf", root) is False
    assert should_trigger(root / "main.tf", root) is True


def test_no_watch_env_var_skips_watcher(monkeypatch):
    monkeypatch.setenv("IACLENS_NO_WATCH", "1")
    from infra_graph.cli import _maybe_start_watch

    class DummyBuilder:
        project_root = Path("/tmp/does-not-matter")

    result = _maybe_start_watch(DummyBuilder())
    assert result is None


def test_explicit_graph_path_skips_watcher(monkeypatch, tmp_path, capsys):
    """Rebuilds always write to builder.out_dir/graph.toon; an explicit
    --graph pointed elsewhere would never see live updates, so the watcher
    must not start when one is given -- regardless of IACLENS_NO_WATCH."""
    monkeypatch.delenv("IACLENS_NO_WATCH", raising=False)
    from infra_graph.cli import _maybe_start_watch

    class DummyBuilder:
        project_root = tmp_path

    other_graph = tmp_path / "federated-graph.toon"
    result = _maybe_start_watch(DummyBuilder(), explicit_graph=other_graph)
    assert result is None
    assert "Auto-watch disabled" in capsys.readouterr().err
    assert result is None


class FakeObserver:
    """Records the handler/path it was scheduled with; does not touch the FS."""

    def __init__(self):
        self.scheduled = []
        self.started = False
        self.stopped = False

    def schedule(self, handler, path, recursive=True):
        self.scheduled.append((handler, path, recursive))

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def join(self):
        pass


class FakeScheduler:
    def __init__(self):
        self.notified = []

    def notify(self, path=None):
        self.notified.append(path)


def test_watchdog_event_on_tf_file_notifies_scheduler_once(tmp_path, monkeypatch):
    import infra_graph.watch as watch_mod

    fake_observer = FakeObserver()
    monkeypatch.setattr(watch_mod, "Observer", lambda: fake_observer)

    class DummyBuilder:
        project_root = tmp_path

    scheduler = FakeScheduler()
    observer = start_watching(tmp_path, DummyBuilder(), scheduler)

    assert observer is fake_observer
    assert fake_observer.started is True
    assert len(fake_observer.scheduled) == 1
    handler, path, recursive = fake_observer.scheduled[0]
    assert path == str(tmp_path)
    assert recursive is True

    class FakeEvent:
        is_directory = False
        src_path = str(tmp_path / "main.tf")

    handler.on_modified(FakeEvent())
    assert scheduler.notified == [str(tmp_path / "main.tf")]

    # A second event on a non-triggering path must not notify again.
    class IgnoredEvent:
        is_directory = False
        src_path = str(tmp_path / "iaclens-out" / "graph.toon")

    handler.on_modified(IgnoredEvent())
    assert scheduler.notified == [str(tmp_path / "main.tf")]


def test_real_rebuild_scheduler_is_accepted_by_start_watching(tmp_path, monkeypatch):
    """Sanity check start_watching's handler wiring against the real
    RebuildScheduler (with a fake timer, no sleeps)."""
    import infra_graph.watch as watch_mod

    fake_observer = FakeObserver()
    monkeypatch.setattr(watch_mod, "Observer", lambda: fake_observer)

    class FakeTimer:
        def __init__(self, interval, fn):
            self.fn = fn

        def start(self):
            pass

        def cancel(self):
            pass

    calls = []

    class DummyBuilder:
        project_root = tmp_path

        def build(self):
            calls.append(1)

    scheduler = RebuildScheduler(
        lambda: DummyBuilder().build(), debounce_ms=800, timer_factory=FakeTimer
    )
    observer = start_watching(tmp_path, DummyBuilder(), scheduler)
    handler, _, _ = fake_observer.scheduled[0]

    class FakeEvent:
        is_directory = False
        src_path = str(tmp_path / "main.tf")

    handler.on_modified(FakeEvent())
    assert observer.started is True
