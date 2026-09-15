"""The script the UI smoke test starts its Chainlit server with.

Loaded by `ask_your_library.fake_backend.install_fake_backend()` inside the
server process (AYL_UI_FAKE_BACKEND points at this file), which calls
`install()` below before `ui.py` binds anything. From then on the server has:

  * a model that answers from a table instead of a provider — patched at
    `llm.llm`, the ChatOpenAI factory, so `llm_invoke` itself still runs: the
    system/user split, the data rule, the usage accounting per role, the JSON
    parse and its one retry. Only the network hop is gone;
  * the two retrieval functions and the catalogue reader `nodes` imported, over
    a five-book library that lives in this file;
  * a preflight that reports a healthy environment, because the real one would
    (correctly) report no Ollama and no index.

Everything else in the run is the shipped code: the compiled graph, the
clarify interrupt, the coverage gate, the quote-provenance check, and every
line the browser renders.

Three questions are scripted, recognised by a word in the `<question>` block
that every node's prompt carries:

  "narrates"    the research path: one search, two evidence items, a green
                quote-provenance badge with an openable passage under it
  "my library"  the catalogue path (ADR-016): no model call after plan, the
                count answered by code from the (fake) index tables
  "gothic"      the clarify path: the agent asks back with the numbered
                candidates and — when nobody answers — carries on once the
                ask-back times out (AYL_CLARIFY_TIMEOUT_S)

A model call this file did not plan for is an error, not a shrug: the smoke
test asserts on what the page says, and a silently improvised reply would turn
a changed graph into a passing run.
"""
import json
import re

from ask_your_library import llm, nodes, preflight
from ask_your_library.library import TITLE_SEPARATOR, BookEntry, author_of, title_of
from ask_your_library.prompts import OBSERVE_RULES, PLAN_RULES, REFLECT_RULES, SYNTHESIZE_RULES

# --- the library this server holds -----------------------------------------
MOBY = f"Moby Dick{TITLE_SEPARATOR}Herman Melville"
DRACULA = f"Dracula{TITLE_SEPARATOR}Bram Stoker"
FRANKENSTEIN = f"Frankenstein{TITLE_SEPARATOR}Mary Shelley"
GULLIVER = f"Gulliver's Travels{TITLE_SEPARATOR}Jonathan Swift"
# Catalogue only, no text: the listing is index metadata, and one book without
# a passage keeps the count honest about what search can and cannot reach.
WILD = f"Where the Wild Things Are{TITLE_SEPARATOR}Maurice Sendak"

PASSAGES = {
    MOBY: {
        "cards": ("Summary",
                  "A sailor named Ishmael joins the whaling ship Pequod. Captain Ahab hunts the "
                  "white whale that took his leg. The voyage ends in ruin, and Ishmael alone "
                  "survives to tell it."),
        "transcripts": ("Chapter 1",
                        "Call me Ishmael. Some years ago, never mind how long precisely, having "
                        "little or no money in my purse, and nothing particular to interest me on "
                        "shore, I thought I would sail about a little and see the watery part of "
                        "the world."),
    },
    DRACULA: {
        "cards": ("Key Takeaways",
                  "A solicitor travels east and finds that his host is no man at all. The hunters "
                  "chase the count back across Europe to his own castle, and reach him at sunset "
                  "on the last day."),
        "transcripts": ("Chapter 27",
                        "The Count's body sprang from the box, and as it fell it crumbled into "
                        "dust and passed from our sight."),
    },
    FRANKENSTEIN: {
        "cards": ("Key Takeaways",
                  "Victor Frankenstein makes a living creature and abandons it. The creature "
                  "turns on him, and Victor pursues it north over the ice until his strength "
                  "gives out."),
        "transcripts": ("Chapter 24",
                        "My present situation was one in which all voluntary thought was "
                        "swallowed up and lost. I was hurried away by fury; revenge alone "
                        "endowed me with strength and composure."),
    },
    GULLIVER: {
        "cards": ("Summary",
                  "A ship's surgeon is stranded among tiny people, then among giants, and learns "
                  "to see his own society from outside."),
        "transcripts": ("Chapter 1",
                        "I felt something alive moving on my left leg, which advancing gently "
                        "forward over my breast, came almost up to my chin."),
    },
}
CATALOGUE = sorted(list(PASSAGES) + [WILD], key=lambda key: title_of(key).casefold())

# Which books a query reaches. The queries are this file's own (the scripted
# planner writes them), so the mapping is a lookup, not a retriever.
TOPICS = ((("gothic", "monster", "creature", "count", "hunted", "pursued", "dust"),
           (DRACULA, FRANKENSTEIN)),)
DEFAULT_BOOKS = (MOBY,)


def _books_for(query: str) -> tuple[str, ...]:
    lowered = query.lower()
    for words, books in TOPICS:
        if any(word in lowered for word in words):
            return books
    return DEFAULT_BOOKS


def _hit(book: str, corpus: str) -> dict:
    section, text = PASSAGES[book][corpus]
    return {"corpus": corpus, "book": book, "section": section, "text": text, "score": 0.03}


def search_both(query: str, k: int = 4, book: str | None = None) -> list[dict]:
    """The retrieval window `act` searches with, in hit order: cards before
    text, book after book. `book` is the filter a resolved title or a chosen
    clarify candidate sets."""
    books = [book] if book else list(_books_for(query))
    return [_hit(b, corpus) for b in books if b in PASSAGES
            for corpus in ("cards", "transcripts")][:max(k, 4)]


def read_chapter(book: str, section: str, max_chars: int = 12000):
    """(text, resolved index key, resolution) — the chapter drill-down. No
    scripted question asks for one; it is here so a graph change that starts
    reading chapters fails on an unscripted model call, not on a missing name."""
    for key, corpora in PASSAGES.items():
        if key == book or key.startswith(book + TITLE_SEPARATOR):
            if corpora["transcripts"][0] == section:
                return corpora["transcripts"][1][:max_chars], key, "found"
    return "", "", "missing"


def list_books() -> list[BookEntry]:
    return [BookEntry(key, title_of(key), author_of(key), key in PASSAGES, key in PASSAGES)
            for key in CATALOGUE]


# --- the scripted model ----------------------------------------------------
# The role of a call is read off the rules in its system message, exactly as
# tests/test_graph_e2e.py reads it: the model is never told a role name.
ROLE_BY_RULES = [("plan", PLAN_RULES[:40]), ("observe", OBSERVE_RULES[:40]),
                 ("reflect", REFLECT_RULES[:40]), ("synthesize", SYNTHESIZE_RULES[:40])]
assert len({head for _, head in ROLE_BY_RULES}) == 4, "two node rule sets share their first 40 chars"

QUESTION_RE = re.compile(r"<question[^>]*>\n(.*?)\n</question>", re.S)
# Recognised in the reader's own question, which every node's prompt carries.
SCENARIOS = (("gothic", "clarify"), ("my library", "catalog"), ("narrates", "research"))

RESEARCH_ANSWER = (
    "Ishmael narrates Moby Dick. He introduces himself in the book's first line — "
    "\"Call me Ishmael.\" [Moby Dick, Chapter 1] — and then sails on the Pequod under "
    "Captain Ahab [Moby Dick, Summary].")
CLARIFY_ANSWER = (
    "You did not pick one, so here is what the library has for both. In Dracula the "
    "hunters chase the count back across Europe and reach him at his own castle "
    "[Dracula, Key Takeaways]; the pursuit ends with his body crumbling into dust "
    "[Dracula, Chapter 27]. In Frankenstein the chase runs the other way: Victor "
    "pursues his creature north over the ice [Frankenstein, Key Takeaways]. The one "
    "hunted across Europe is Dracula.")

SCRIPT = {
    "research": {
        # "book" is the planner repeating a name the question uses; code resolves it
        # against the catalogue and limits retrieval to it (ADR-016).
        "plan": [{"mode": "answer", "book": "Moby Dick",
                  "queries": ["who narrates the Pequod voyage", "opening line of the novel"]}],
        "observe": [{"evidence": [
            {"hit_id": "s1h1", "book": MOBY, "section": "Summary",
             "quote": "A sailor named Ishmael joins the whaling ship Pequod.",
             "why": "names the narrator and the ship"},
            {"hit_id": "s1h2", "book": MOBY, "section": "Chapter 1",
             "quote": "Call me Ishmael.", "why": "the narrator introduces himself"}]}],
        "reflect": [{"decision": "enough"}],
        "synthesize": [RESEARCH_ANSWER],
    },
    "catalog": {
        # The catalogue path stops here: code runs the operation over the index
        # tables and no second model call is made.
        "plan": [{"mode": "catalog", "catalog": {"op": "list", "title": "", "author": ""}}],
    },
    "clarify": {
        "plan": [
            {"mode": "identify",
             "queries": ["a monster hunted across Europe", "the creature pursued to the end"]},
            # Second plan: the ask-back timed out, the reply came back empty, and
            # the loop goes on with what it has.
            {"mode": "answer", "queries": ["the count crumbles into dust"]},
        ],
        "observe": [
            {"evidence": [
                {"hit_id": "s1h1", "book": DRACULA, "section": "Key Takeaways",
                 "quote": "The hunters chase the count back across Europe to his own castle,",
                 "why": "a hunt across Europe"},
                {"hit_id": "s1h3", "book": FRANKENSTEIN, "section": "Key Takeaways",
                 "quote": "Victor pursues it north over the ice until his strength gives out.",
                 "why": "also a hunt, but northward"}]},
            {"evidence": [
                {"hit_id": "s2h2", "book": DRACULA, "section": "Chapter 27",
                 "quote": "it crumbled into dust and passed from our sight.",
                 "why": "the end of the pursuit"}]},
        ],
        "reflect": [
            {"decision": "clarify",
             "clarify_question": "Are you thinking of Dracula or of Frankenstein?"},
            {"decision": "enough"},
        ],
        "synthesize": [CLARIFY_ANSWER],
    },
}

# Typos in a quote would show up as an amber badge in a browser, three minutes
# into a run; here they stop the server from starting at all.
for _scenario, _roles in SCRIPT.items():
    for _step in _roles.get("observe", []):
        for _item in _step["evidence"]:
            assert _item["quote"] in PASSAGES[_item["book"]][
                "cards" if _item["section"] in ("Summary", "Key Takeaways") else "transcripts"][1], \
                f"{_scenario}: quote not verbatim in its passage: {_item['quote']!r}"


class Reply:
    """What langchain hands back: content plus the usage the accounting reads."""

    def __init__(self, content: str):
        self.content = content
        self.usage_metadata = {"input_tokens": 420, "output_tokens": 64}
        self.response_metadata = {"model_name": "scripted-backend"}


class ScriptedModel:
    """One server answers many questions, and a script is per QUESTION: the
    second reader to ask "who narrates Moby Dick?" must get the first reply
    again, not the end of the script.

    So the call counters hang off the run, not off the process. `llm._usage()`
    is the run's accumulator — a fresh object per `reset_usage()`, i.e. per
    `run_question`, and the same object across a clarify pause — which makes its
    identity exactly the run's identity. The object is kept alongside its
    counters so its id cannot be recycled onto a later run.
    """

    def __init__(self):
        self.runs: dict[int, tuple[object, dict[tuple[str, str], int]]] = {}

    def _counters(self) -> dict[tuple[str, str], int]:
        usage = llm._usage()
        return self.runs.setdefault(id(usage), (usage, {}))[1]

    def invoke(self, messages):
        system, user = messages[0].content, messages[1].content
        role = next((r for r, head in ROLE_BY_RULES if system.startswith(head)), None)
        assert role is not None, f"system message matches no node's rules: {system[:60]!r}"
        found = QUESTION_RE.search(user)
        question = (found.group(1) if found else user).lower()
        scenario = next((name for word, name in SCENARIOS if word in question), None)
        assert scenario is not None, f"no scripted scenario for the question: {question[:80]!r}"
        replies = SCRIPT[scenario].get(role) or []
        counters = self._counters()
        nth = counters.get((scenario, role), 0)
        counters[(scenario, role)] = nth + 1
        assert nth < len(replies), (
            f"unscripted call {nth + 1} of role {role!r} in scenario {scenario!r}: the graph "
            f"made a call this script does not plan for")
        reply = replies[nth]
        return Reply(reply if isinstance(reply, str) else json.dumps(reply))


MODEL = ScriptedModel()


def healthy_environment() -> preflight.PreflightResult:
    """What the preflight would say about a server whose model and index are in
    this file: nothing to report. The real check contacts Ollama and opens
    LanceDB, and neither exists here."""
    return preflight.PreflightResult([], [], [])


def install() -> None:
    """Replace the backend in THIS process. Called by fake_backend.py before
    ui.py binds these names, so the module-level `from ... import` lines there
    pick up what is set here."""
    llm.llm = lambda role="", capped=None: MODEL
    nodes.search_both = search_both
    nodes.read_chapter = read_chapter
    nodes.list_books = list_books
    preflight.check_environment = healthy_environment
