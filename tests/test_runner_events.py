"""runner.run_question emits a partial metrics event when the graph pauses at
a clarify interrupt (the reader sees what the run has cost so far), and the
final metrics event still covers the whole run once."""
from pathlib import Path


class FakeGraph:
    """Two rounds: an interrupt, then completion after the reader's reply."""
    checkpointer = None

    def __init__(self):
        self.resumed_with = None
        self.state = {"steps_taken": 1, "answer": "", "stop_reason": ""}

    def stream(self, run_input, config):
        if self.resumed_with is None and not hasattr(run_input, "resume"):
            yield {"plan": {"mode": "identify"}}
            yield {"__interrupt__": [type("I", (), {"value": "which one?"})()]}
            return
        self.resumed_with = getattr(run_input, "resume", None)
        self.state = {"steps_taken": 2, "answer": "the answer", "stop_reason": "enough"}
        yield {"synthesize": {"answer": "the answer"}}

    def get_state(self, config):
        return type("S", (), {"values": self.state})()


def test_the_scratchpad_is_readable_only_by_its_owner(tmp_path):
    """It holds the retrieved passages as the model saw them. touch() created
    it with the process umask (0644 on a default account), so every local
    account could read a run's evidence while the run was still going."""
    import stat

    from ask_your_library import runner

    runner.run_question(FakeGraph(), "q", [], Path(tmp_path), lambda n, u: None,
                        lambda question: "the first one")
    written = list(Path(tmp_path).glob("run-*.md"))
    assert len(written) == 1
    assert stat.S_IMODE(written[0].stat().st_mode) == 0o600


def test_partial_metrics_at_the_interrupt_and_final_metrics_once(tmp_path):
    from ask_your_library import runner

    events = []
    graph = FakeGraph()
    answer = runner.run_question(graph, "q", [], Path(tmp_path), lambda n, u: events.append((n, u)),
                                 lambda question: "the first one")
    assert answer == "the answer" and graph.resumed_with == "the first one"
    metrics = [u for n, u in events if n == "metrics"]
    assert len(metrics) == 2
    assert metrics[0]["partial"] is True and metrics[0]["steps_taken"] == 1
    assert "partial" not in metrics[1] and metrics[1]["stop_reason"] == "enough" and metrics[1]["steps_taken"] == 2
    # the partial event comes before the reader is asked
    names = [n for n, _ in events]
    assert names.index("metrics") < len(names) - 1


def test_the_clarify_pause_is_reported_to_the_deadline_clock(tmp_path, monkeypatch):
    """The reader's thinking time is not the agent's: the runner measures the
    pause around on_clarify and hands it to the deadline; `seconds` in the
    metrics keeps counting wall time as before."""
    from ask_your_library import llm, runner

    class Clock:
        ticks = iter([0.0, 5.0, 10.0, 47.5, 60.0])   # started, partial metrics, pause start, pause end, final

        @staticmethod
        def monotonic():
            return next(Clock.ticks)

        time = staticmethod(__import__("time").time)  # the scratchpad name still wants wall-clock time
    monkeypatch.setattr(runner, "time", Clock)       # the runner's clock only; llm keeps the real one
    events = []
    runner.run_question(FakeGraph(), "q", [], Path(tmp_path), lambda n, u: events.append((n, u)),
                        lambda question: "yes", deadline_s=7)
    assert llm._usage().paused == 37.5              # the reader's 37.5 s do not count against the deadline
    assert llm._usage().deadline_s == 7             # the per-run override reached the accumulator
    metrics = [u for n, u in events if n == "metrics"]
    assert metrics[0]["seconds"] == 5.0 and metrics[1]["seconds"] == 60.0     # wall time still includes the pause
