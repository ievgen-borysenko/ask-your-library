"""runner.run_question emits a partial metrics event when the graph pauses at
a clarify interrupt (the reader sees what the run has cost so far), and the
final metrics event still covers the whole run once — a run that FAILED
included, which is the only account of what that question spent.

The run comes back as a RunResult: the answer and the end state as fields,
so no interface reads the graph's state.
"""
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
    result = runner.run_question(graph, "q", [], Path(tmp_path), lambda n, u: events.append((n, u)),
                                 lambda question: "the first one")
    assert result.answer == "the answer" and graph.resumed_with == "the first one"
    assert result.failure is None and result.ok
    assert result.stop_reason == "enough" and result.steps_taken == 2
    assert result.clarify_asked is True          # the runner knows; the resumed state does not say it
    assert result.question == "q" and result.scratchpad.name.startswith("run-")
    metrics = [u for n, u in events if n == "metrics"]
    assert len(metrics) == 2
    assert metrics[0]["partial"] is True and metrics[0]["steps_taken"] == 1
    assert "partial" not in metrics[1] and metrics[1]["stop_reason"] == "enough" and metrics[1]["steps_taken"] == 2
    # the partial event comes before the reader is asked
    names = [n for n, _ in events]
    assert names.index("metrics") < len(names) - 1


class BrokenGraph:
    """Answers the first node, then raises — a question that dies mid-run."""
    checkpointer = None

    def __init__(self, error=None):
        self.error = error or RuntimeError("the index is gone")

    def stream(self, run_input, config):
        from ask_your_library import llm
        yield {"plan": {"mode": "answer"}}
        spent = llm._usage()                       # a model call was made and billed
        spent.llm_calls += 1
        spent.input_tokens += 120
        llm._by_role(spent, "plan")["calls"] += 1
        raise self.error

    def get_state(self, config):
        raise RuntimeError("no state for a thread that never finished")


def test_a_question_that_fails_mid_run_still_reports_its_metrics(tmp_path):
    """Before, the metrics event was emitted after the `try`, so a question
    that raised reported nothing at all — the calls it had already paid for
    were invisible to every interface and to the eval report. The event is the
    run's account, and a failed run has one too."""
    from ask_your_library import runner

    events = []
    result = runner.run_question(BrokenGraph(), "q", [], Path(tmp_path),
                                 lambda n, u: events.append((n, u)), lambda question: "")

    metrics = [u for n, u in events if n == "metrics"]
    assert len(metrics) == 1 and "partial" not in metrics[0]
    assert metrics[0]["llm_calls"] == 1 and metrics[0]["input_tokens"] == 120
    assert metrics[0]["by_role"]["plan"]["calls"] == 1
    # the failure is the result's, not an exception: the answer is empty, the
    # partial usage is there, and the caller decides what to say about it
    assert result.failure is not None and not result.ok
    assert result.failure.type == "RuntimeError" and result.failure.message == "the index is gone"
    assert str(result.failure) == "RuntimeError: the index is gone"
    assert result.answer == "" and result.steps_taken == 0
    assert result.usage["llm_calls"] == 1 and result.usage["input_tokens"] == 120


def test_exactly_one_metrics_event_on_a_run_that_answers(tmp_path):
    """The other half of the count: the event that reports the whole run is
    emitted once, never twice, when nothing goes wrong."""
    from ask_your_library import runner

    class PlainGraph:
        checkpointer = None

        def stream(self, run_input, config):
            yield {"synthesize": {"answer": "the answer"}}

        def get_state(self, config):
            return type("S", (), {"values": {"answer": "the answer", "steps_taken": 1,
                                             "stop_reason": "enough"}})()

    events = []
    result = runner.run_question(PlainGraph(), "q", [], Path(tmp_path),
                                 lambda n, u: events.append((n, u)), lambda question: "")
    assert [n for n, _ in events] == ["synthesize", "metrics"]
    assert result.answer == "the answer" and result.failure is None


def test_a_failure_message_names_no_machine(tmp_path):
    """The message travels into a chat, a report and a committed summary: a
    FileNotFoundError names the file it could not open, and under a home
    directory that file name is the reader's login."""
    from ask_your_library import runner

    secret = Path.home() / "books" / "private.md"
    result = runner.run_question(BrokenGraph(FileNotFoundError(f"cannot open {secret}")),
                                 "q", [], Path(tmp_path), lambda n, u: None, lambda question: "")
    assert result.failure.message == "cannot open ~/books/private.md"
    assert str(Path.home()) not in result.failure.message


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


def test_history_keeps_only_the_shape_of_a_catalogue_answer():
    """The conversation memory goes into the next planner prompt: a catalogue
    answer's list of titles must not travel with it (ADR-016)."""
    from ask_your_library.runner import history_entry

    listing = {"op": "list", "count": 2, "total": 2, "books": ["Private Book — Someone", "Other — Else"],
               "query": "", "resolved": True, "suggestions": []}
    entry = history_entry("what are my books called?", "2 books:\n- Private Book — Someone\n- Other — Else", listing)
    assert entry.startswith("Q: what are my books called?\nA: (catalogue answer: list, 2 of 2 books")
    assert "Private Book" not in entry and "Other — Else" not in entry
    asked = history_entry("do I have Dracula?", "Yes:\n- Dracula — Bram Stoker",
                          {**listing, "op": "has", "count": 1, "query": "Dracula"})
    assert "asked about: Dracula, found: yes" in asked and "Bram Stoker" not in asked
    assert history_entry("q", "a" * 600) == "Q: q\nA: " + "a" * 500        # every other answer: truncated, as before

