"""Who said it, and what kind of text it is (#100).

On a real library an audiobook episode in which an actor reads the opening of
a novel (a father's letter to his son) produced an answer that gave the letter
to the episode's host, and a quote from a book card was answered as if the book
had said it. Four things are checked here: an evidence line from a card carries
a label code puts there, `reflect` is shown the searches the run already made,
and the rules of `observe` and `synthesize` say how speech is quoted and to whom
it is given.

No LLM, no network, no index: `llm.ask_json` and `llm.llm_invoke` are fakes.
"""
import re

from ask_your_library import llm, nodes, prompts

MOBY = "Moby Dick — Herman Melville"
CARD_LINE_QUOTE = "Ahab lost his leg to the white whale."
TEXT_LINE_QUOTE = "Call me Ishmael."

EVIDENCE = [{"hit_id": "s1h1", "book": MOBY, "section": "Key Characters",
             "quote": CARD_LINE_QUOTE, "why": "the card"},
            {"hit_id": "s1h2", "book": MOBY, "section": "Chapter 1",
             "quote": TEXT_LINE_QUOTE, "why": "the text"}]
HITS_LOG = [{"hit_id": "s1h1", "step": 1, "book": MOBY, "section": "Key Characters",
             "corpus": "cards", "text": f"## Key Characters\n{CARD_LINE_QUOTE}"},
            {"hit_id": "s1h2", "step": 1, "book": MOBY, "section": "Chapter 1",
             "corpus": "transcripts", "text": TEXT_LINE_QUOTE}]


def reflect_state(**over) -> dict:
    state = {"question": "q", "mode": "answer", "steps_taken": 1, "empty_streak": 0,
             "evidence": [dict(e) for e in EVIDENCE], "queries": [], "read_chapters": [],
             "clarification": "", "clarify_asked": False, "clarify_chosen": "",
             "book_filter": "", "coverage_probed": True, "hits_log": [dict(h) for h in HITS_LOG],
             "searches_run": []}
    state.update(over)
    return state


def reflect_prompt(monkeypatch, **over) -> dict:
    seen = {}

    def ask_json(system, user, role):
        seen.update(system=system, user=user, role=role)
        return {"decision": "enough"}

    monkeypatch.setattr(llm, "ask_json", ask_json)
    nodes.reflect(reflect_state(**over))
    return seen


def synthesize_prompt(monkeypatch, **over) -> dict:
    seen = {}

    def llm_invoke(system, user, role):
        seen.update(system=system, user=user, role=role)
        return type("R", (), {"content": "An answer."})

    monkeypatch.setattr(llm, "llm_invoke", llm_invoke)
    state = {"question": "q", "evidence": [dict(e) for e in EVIDENCE],
             "hits_log": [dict(h) for h in HITS_LOG]}
    state.update(over)
    nodes.synthesize(state)
    return seen


def block(user: str, tag: str) -> str:
    """The body of the one <tag> block of a user message."""
    found = re.findall(rf"^<{tag}(?:\s[^>]*)?>\n(.*?)\n</{tag}>$", user, re.M | re.S)
    assert len(found) == 1, f"expected one <{tag}> block, found {len(found)}"
    return found[0]


# ---------------------------------------------------------------- (a) the card label
def test_reflect_labels_a_card_line_and_leaves_a_book_text_line_as_it_was(monkeypatch):
    body = block(reflect_prompt(monkeypatch)["user"], "evidence_so_far")
    assert body.splitlines() == [
        f'- {MOBY} (Key Characters) (book card): "{CARD_LINE_QUOTE}"',
        # byte for byte the line #93 measured
        f'- {MOBY} (Chapter 1): "{TEXT_LINE_QUOTE}"']


def test_synthesize_labels_a_card_line_after_the_citation_it_copies(monkeypatch):
    seen = synthesize_prompt(monkeypatch)
    body = block(seen["user"], "evidence")
    assert body.splitlines() == [
        f'- [{MOBY}, Key Characters] (book card) "{CARD_LINE_QUOTE}"',
        f'- [{MOBY}, Chapter 1] "{TEXT_LINE_QUOTE}"']
    # the citation label the answer copies is still the book and the section alone
    assert re.findall(r"^- (\[[^\]]*\])", body, re.M) == [f"[{MOBY}, Key Characters]",
                                                         f"[{MOBY}, Chapter 1]"]


def test_the_label_is_read_off_the_hit_record_never_off_model_text(monkeypatch):
    """The corpus of the cited hit decides, and nothing else: not the section
    title, not observe's note, not a quote that spells the label itself. A hit
    the run never logged, or one logged without a corpus (an index from before
    cards), is book text — the reading that cannot invent a card."""
    evidence = [{"hit_id": "s1h2", "book": MOBY, "section": "card (book card)",
                 "quote": "it says (book card) here", "why": "this is a book card"},
                {"hit_id": "s9h9", "book": MOBY, "section": "Chapter 2", "quote": "Unlogged.",
                 "why": "card"},
                {"hit_id": "s1h3", "book": MOBY, "section": "Chapter 3", "quote": "No corpus.",
                 "why": "card"}]
    hits_log = HITS_LOG + [{"hit_id": "s1h3", "step": 1, "book": MOBY, "section": "Chapter 3",
                            "text": "No corpus."}]
    reflect_body = block(reflect_prompt(monkeypatch, evidence=evidence, hits_log=hits_log)["user"],
                         "evidence_so_far")
    synth_body = block(synthesize_prompt(monkeypatch, evidence=evidence, hits_log=hits_log)["user"],
                       "evidence")
    assert reflect_body.splitlines() == [
        f'- {MOBY} (card (book card)): "it says (book card) here"',
        f'- {MOBY} (Chapter 2): "Unlogged."',
        f'- {MOBY} (Chapter 3): "No corpus."']
    assert synth_body.splitlines() == [
        f'- [{MOBY}, card (book card)] "it says (book card) here"',
        f'- [{MOBY}, Chapter 2] "Unlogged."',
        f'- [{MOBY}, Chapter 3] "No corpus."']
    # and a state with no hits_log at all labels nothing
    no_log = block(synthesize_prompt(monkeypatch, hits_log=None)["user"], "evidence")
    assert "(book card)" not in no_log


def test_a_quote_repinned_to_a_card_is_labelled_by_the_hit_it_now_cites(monkeypatch):
    """The gate pins an item to the hit that holds its quote, so the hit_id on
    the evidence is the source the label must describe."""
    llm.reset_usage()
    monkeypatch.setattr(llm, "ask_json", lambda system, user, role: {"evidence": [
        {"hit_id": "s1h2", "book": MOBY, "quote": "Ahab lost his leg to the white whale",
         "why": "w"}]})
    hits = [{"hit_id": "s1h1", "corpus": "cards", "book": MOBY, "section": "Key Characters",
             "text": f"## Key Characters\n{CARD_LINE_QUOTE}"},
            {"hit_id": "s1h2", "corpus": "transcripts", "book": MOBY, "section": "Chapter 1",
             "text": TEXT_LINE_QUOTE}]
    update = nodes.observe({"question": "q", "current_query": "cq", "empty_streak": 0,
                            "evidence": [], "hits": hits})
    assert [e["hit_id"] for e in update["evidence"]] == ["s1h1"]
    body = block(synthesize_prompt(monkeypatch, evidence=update["evidence"])["user"], "evidence")
    assert "(book card)" in body


def flat(rules: str) -> str:
    """The rules as one line: what the model is told, not how it is wrapped."""
    return " ".join(rules.split())


def test_both_rules_say_what_a_card_is():
    for rules in (flat(prompts.REFLECT_RULES), flat(prompts.SYNTHESIZE_RULES)):
        assert nodes.CARD_LABEL in rules
        assert "summary written about the book, not the book's own words" in rules
    # synthesize draws the consequence: a card is never the book's or a character's words
    assert "never present it as a quotation from the book" in flat(prompts.SYNTHESIZE_RULES)
    # both templates still format (no stray brace)
    prompts.REFLECT_RULES.format(clarify_lang="in English")
    prompts.SYNTHESIZE_RULES.format(lang="Answer in English.")
