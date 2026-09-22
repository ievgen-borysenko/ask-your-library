"""The release check of the web UI, in a browser, as a test.

Until now this path was walked by hand before every release (docs/backlog.md,
"Release status"): first start, login, the starters on the empty chat screen, a
question, the live agent steps, the quote-provenance badge, an evidence passage
readable in the browser, the catalogue answer, a reload that restores the
conversation, and a clarify nobody answers. That is what this file does, against a real
server started the way `ayl ui` starts one — `ask_your_library.ui.launcher`, which prepares a
Chainlit app root and runs `chainlit run` against the packaged app — with the model and the
index replaced by `scripted_backend.py` (see
`ask_your_library.fake_backend`). Nothing here needs Ollama, a key or an index,
and every run answers the same way.

Two viewports, because the phone rendering has traps of its own: the steps are
collapsed, the composer floats over the last ~120 px of the thread, an opened
passage is taller than the screen, and the thread history — with the address a
reload has to be a reload OF — is off-canvas behind the sidebar toggle.

Every assertion is about text on the screen and every wait carries its own
timeout; nothing here sleeps for a fixed time and hopes.

The server fixture lives in this file rather than in a `tests/ui/conftest.py`:
in a directory that is not a package, pytest imports every conftest.py under the
module name `conftest`, and a second one would take that name away from the
suite's own (`tests/conftest.py`), which the rest of the tests import by it.
"""
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

import pytest

HERE = Path(__file__).resolve().parent
SCRIPTED_BACKEND = HERE / "scripted_backend.py"

# Login of the throwaway demo server (docs/quick-start.md); the placeholder
# password needs AYL_ALLOW_DEFAULT_LOGIN=1 to be accepted at all.
USERNAME = "admin"
PASSWORD = "change-me"
# Short enough that a test can watch the ask-back expire, long enough that a
# slow CI runner does not expire it before the assertions on it have run.
CLARIFY_TIMEOUT_S = 25
SERVER_START_TIMEOUT_S = 180


def _browser_problem() -> str:
    """Why this file cannot run, or "" when it can.

    The browser is not a Python package and `uv sync` does not install it, so
    the whole module skips itself with the command to fix that in the reason —
    `uv run pytest -q` on a clone that never ran it stays green and fast, and
    CI's `ui-smoke` job is the one place these tests actually run.

    Cheap, but not free: `sync_playwright()` starts the node driver, which the
    `with` block then stops; the browser itself is never launched, and the
    executable path is a lookup on an already-running driver.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "playwright is not installed: uv sync --group dev"
    try:
        with sync_playwright() as play:
            executable = play.chromium.executable_path
    except Exception as error:      # a driver that cannot start at all
        return f"playwright could not start its driver ({type(error).__name__}: {error})"
    if not Path(executable).exists():
        return "chromium is not installed: uv run playwright install chromium"
    return ""


# CI sets this in the ui-smoke job and nowhere else. A skip is the right answer
# on a developer's machine that never ran `playwright install`; in the job whose
# whole purpose is this file, it is the wrong answer twice over — a green run
# that checked nothing, and a release check that quietly stopped running. There
# the missing browser is a collection ERROR, which no summary can be mistaken for
# a pass.
REQUIRED_VAR = "AYL_UI_SMOKE_REQUIRED"

_PROBLEM = _browser_problem()
if _PROBLEM:
    if os.environ.get(REQUIRED_VAR) == "1":
        raise RuntimeError(
            f"{REQUIRED_VAR}=1, so this file must RUN, and it cannot: {_PROBLEM}")
    pytest.skip(_PROBLEM, allow_module_level=True)

from playwright.sync_api import Error as PlaywrightError, expect, sync_playwright  # noqa: E402


@pytest.fixture
def browser():
    """A chromium for ONE test, and its lifetime is the point.

    Playwright's sync API drives its driver with greenlets over an asyncio
    loop that RUNS in this thread for as long as the driver is open, so a
    session-scoped browser (pytest-playwright's own `browser` fixture, which
    this shadows) leaves that loop running for every test that comes after
    it — and `asyncio.run(...)`, which tests/test_ui.py uses throughout,
    then raises "cannot be called from a running event loop". The default
    collection order hides it (this directory sorts last); naming a file
    after tests/ui on the command line does not.
    """
    with sync_playwright() as play:
        instance = play.chromium.launch()
        try:
            yield instance
        finally:
            instance.close()

DESKTOP = (1280, 800)
PHONE = (390, 844)

# One budget per kind of wait, in milliseconds. Generous for a CI runner, and
# still a bound: a hang fails the test instead of holding the job open.
LOAD_MS = 60_000          # first paint of the SPA, and the login round trip
RENDER_MS = 30_000        # an element that is already decided appearing
ANSWER_MS = 60_000        # a whole question: scripted, so this is slack, not the answer's speed

RESEARCH_QUESTION = "Who narrates Moby Dick?"
CATALOGUE_QUESTION = "Which books are in my library?"
CLARIFY_QUESTION = ("which gothic novel was it where a monster gets hunted across europe "
                    "right up to the end of the book?")

BADGE = "Quote provenance"
CATALOGUE_BADGE = "Catalogue answer"
CANDIDATES = "Candidates in the library"
# The metrics footer's own <details>, sent after everything else a question
# produces: on the page it means "this run is over", and it is the one
# <details> that is never an evidence passage.
METRICS_SUMMARY = "run details"

COMPOSER = "textarea#chat-input"
# The thread list inside the sidebar. Its presence is how the test knows the
# drawer is open at phone width, where the sidebar is a modal.
THREAD_HISTORY = "#thread-history"


# --- the server under test ---------------------------------------------------
def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_http(url: str, timeout: float, process: subprocess.Popen) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"the Chainlit server exited with {process.returncode} before it served")
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.5)
    raise RuntimeError(f"{url} did not answer within {timeout:.0f}s")


class Server:
    """A running server and what the test has to know about how it was started."""

    def __init__(self, url: str, log_path: Path, started_in: Path):
        self.url = url
        self.log_path = log_path
        self.started_in = started_in
        self.username = USERNAME
        self.password = PASSWORD
        self.clarify_timeout_s = CLARIFY_TIMEOUT_S

    def log(self) -> str:
        return self.log_path.read_text(encoding="utf-8", errors="replace")


@pytest.fixture
def chainlit_server(tmp_path_factory) -> Server:
    """The web chat on a free loopback port, started through
    `ask_your_library.ui.launcher` with the scripted backend and its own state
    directory as the Chainlit app root.

    One server PER TEST, not per session, and the extra start is the point: the
    chat db IS the thread history, and a second test sharing it would find the
    first one's finished conversation in the sidebar — which is how the phone leg
    once passed its clarify assertions against text the desktop leg had left on
    the screen.

    The environment is the one the suite already pinned (tests/conftest.py runs
    before anything here), plus what this server needs. The two fake-backend
    variables are set together on purpose: either alone is a no-op or a refusal,
    which is what the pair is for.
    """
    chainlit = Path(sys.executable).parent / "chainlit"
    if not chainlit.exists():
        pytest.skip("the ui extra is not installed: uv sync --group dev --extra ui")

    state = tmp_path_factory.mktemp("chainlit-server")
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    environment = {
        **os.environ,
        # A throwaway demo login, and its state well away from the checkout
        # (the import writes an auth secret and a chat db).
        "AYL_ALLOW_DEFAULT_LOGIN": "1",
        "CHAINLIT_USERNAME": USERNAME,
        "CHAINLIT_PASSWORD": PASSWORD,
        # The app root is the directory ABOVE this one (launcher.app_root), so
        # the config the launcher writes, the translations, the chat db and the
        # auth secret all land under `state` and nothing is read from — or
        # written into — the checkout.
        "AYL_CHAINLIT_DIR": str(state / ".chainlit"),
        "ASK_SCRATCH_DIR": str(state / "scratch"),
        # Pinned, not inherited: with a hosted backend app.py refuses to start
        # without a key, and this server has no backend at all.
        "LLM_BACKEND": "ollama",
        "EMBED_BACKEND": "ollama",
        "ASK_LANG": "en",
        "AYL_STRICT_HIT_ID": "1",
        "AYL_UI_FAKE_BACKEND": str(SCRIPTED_BACKEND),
        "AYL_UI_FAKE_BACKEND_CONFIRM": "this-server-answers-from-a-script",
        "AYL_CLARIFY_TIMEOUT_S": str(CLARIFY_TIMEOUT_S),
        # The one name in chainlit's tree that would send this conversation off
        # the machine: its data layer uploads threads to Literal AI when it is
        # set. A developer's shell may well have it; the questions typed below
        # are not theirs to upload. Blank, not removed — dotenv fills a free name.
        "LITERAL_API_KEY": "",
    }
    # Started through the launcher, not with a `chainlit run` of our own: the
    # thing under test is the server a reader gets from `ayl ui`, configuration
    # included. `launcher.run` blocks (it is a subprocess.call), so the child is
    # a small python parent with chainlit under it — and the process group below
    # covers both.
    #
    # It runs in an empty directory, which is the assertion after the wait: the
    # app root Chainlit reads is `CHAINLIT_APP_ROOT or os.getcwd()`, so a
    # `.chainlit/` appearing HERE is a server that was configured by whatever
    # was (or was not) in the working directory. The empty directory also keeps
    # a developer's `.env` out of it — chainlit's own import calls
    # `load_dotenv(<cwd>/.env)`, and this server's environment is the pinned
    # one below.
    elsewhere = state / "elsewhere"
    elsewhere.mkdir()
    launch = (f"from ask_your_library.ui import launcher\n"
              f"raise SystemExit(launcher.run('127.0.0.1', {port}, ['--headless']))\n")
    log_path = state / "chainlit-server.log"
    with log_path.open("w") as log:
        process = subprocess.Popen(
            [sys.executable, "-c", launch],
            cwd=str(elsewhere), env=environment, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True)      # its own process group: uvicorn's children die with it
    try:
        try:
            _wait_for_http(url + "/", SERVER_START_TIMEOUT_S, process)
        except RuntimeError as error:
            raise RuntimeError(f"{error}\n--- server log ---\n"
                               f"{log_path.read_text(errors='replace')}") from None
        # A running server, and the directory it was started in is still empty.
        # Chainlit writes a default config.toml, a .files/ and a chainlit.md
        # into its app root when it finds none there, so these appearing in the
        # working directory is exactly what an app root the launcher did NOT
        # prepare looks like — and a config Chainlit wrote is one with
        # `allow_origins = ["*"]`, without `unsafe_allow_html` and without
        # `auto_tag_thread = false`.
        stray = sorted(path.name for path in elsewhere.iterdir())
        assert not stray, f"the server was configured from its working directory: {stray}"
        assert (state / ".chainlit" / "config.toml").is_file()
        yield Server(url, log_path, elsewhere)
    finally:
        if process.poll() is None:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)


def open_page(browser, width: int, height: int):
    """A fresh context at one viewport. Below 768 px it is a phone: touch, a
    mobile user agent and DPR 2, so the page takes the code path a phone takes."""
    phone = width < 768
    context = browser.new_context(viewport={"width": width, "height": height},
                                  device_scale_factor=2 if phone else 1,
                                  is_mobile=phone, has_touch=phone)
    return context.new_page()


# --- the page, in the words of the release check ------------------------------
def body(page):
    return page.locator("body")


def step(page, name: str):
    """One agent step's collapse trigger. Chainlit ids them `step-<name>`, and
    the name is the label app.py writes, so the second step is
    `step-searched the library #1` — spaces and a hash in an id, hence the
    attribute selector."""
    return page.locator(f'[id="step-{name}"]')


def log_in(page, server) -> None:
    page.goto(server.url, wait_until="load", timeout=LOAD_MS)  # "networkidle" never fires: the socket stays open
    expect(page.locator("input#password")).to_be_visible(timeout=LOAD_MS)
    page.fill("input#email", server.username)            # the first field is labelled "Email address"
    page.fill("input#password", server.password)
    page.click("button[type=submit]")
    expect(page.locator(COMPOSER)).to_be_visible(timeout=LOAD_MS)


def ask(page, question: str) -> None:
    """Type a question and send it — and prove it was sent, not merely typed.

    The wait in the middle is load-bearing. Chainlit keeps the composer's submit
    disabled until the session is ready, and `fill` writes into the textarea
    anyway, so an Enter pressed a moment too early is swallowed and the question
    sits in the box. This file used to have an accidental barrier against that:
    `on_chat_start` sent a welcome message and the first assertion waited for it,
    which meant the socket was up before anything was typed. Nothing is sent into
    an empty chat any more (the welcome screen and its starters need the thread
    empty), so the barrier is explicit — with text in the composer, `#chat-submit`
    is disabled for exactly one remaining reason.

    The assertion afterwards is the composer going empty, then the text on the
    page. "The question is somewhere on the page" alone is true of a question
    still sitting in the textarea, which is how a swallowed Enter passed this
    line and failed sixty seconds later on a step that never ran."""
    page.click(COMPOSER)
    page.fill(COMPOSER, question)
    expect(page.locator("#chat-submit")).to_be_enabled(timeout=RENDER_MS)
    page.keyboard.press("Enter")
    expect(page.locator(COMPOSER)).to_have_value("", timeout=RENDER_MS)
    expect(body(page)).to_contain_text(question, timeout=RENDER_MS)


def thread_link_in_the_drawer(page) -> str:
    """The href of this conversation's entry in the thread list, or "" while
    there is not one to read.

    At 390 px the thread history is a modal drawer: `#thread-history` is not in
    the DOM at all until the sidebar toggle is pressed, and a re-render can take
    it away again. That is how a link `count()` had just seen timed out thirty
    seconds later inside `get_attribute` — three times on this branch, phone leg
    only, never on the desktop one.

    So: the toggle is pressed only when the list is absent, because it is a
    TOGGLE and a second press closes the drawer the first one opened; and the
    read is allowed to fail, because a detached link is something to look up
    again on the next poll, not something to wait thirty seconds for. Nothing
    here waits: the caller owns the deadline.
    """
    if not page.locator(THREAD_HISTORY).count():
        toggle = page.locator("#sidebar-trigger-button")
        if not toggle.count() or not toggle.is_visible():
            return ""
        toggle.click(timeout=RENDER_MS)
        page.wait_for_timeout(250)          # the drawer animates in
        return ""                           # read it on the next poll, once it has settled
    link = page.locator("a[href*='/thread/']").first
    if not link.count():
        return ""                           # the drawer is open and the thread is not in it yet
    try:
        return link.get_attribute("href", timeout=2_000) or ""
    except PlaywrightError:
        return ""                           # the list re-rendered under the read; try again


def thread_address(page, timeout_ms: int) -> str:
    """The address this conversation lives at — what a reload has to be a
    reload OF, since reloading "/" opens a new chat instead of restoring it.

    Two shapes, and the difference is the phone trap: in a wide window Chainlit
    moves the browser onto /thread/<id> itself, a beat after the answer renders
    (a history push inside the running app, polled rather than awaited as a
    navigation). At 390 px it never does, and the address is only ever a link
    inside the off-canvas drawer — see thread_link_in_the_drawer.
    """
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if "/thread/" in page.url:
            return page.url
        href = thread_link_in_the_drawer(page)
        if href:
            return urljoin(page.url, href)
        page.wait_for_timeout(250)
    raise AssertionError(f"the conversation never got an address of its own: {page.url}")


def wait_for_the_run_to_finish(page, timeout_ms: int) -> None:
    """The metrics footer is the last message of a question, so its presence is
    "this run has stopped adding messages". Waited for before anything is
    clicked in the thread: a message list still growing re-renders under the
    click, and a locator resolved a moment earlier is then attached to nothing
    (seen once, as `Element is not attached to the DOM`, under full-suite load)."""
    expect(body(page)).to_contain_text(METRICS_SUMMARY, timeout=timeout_ms)


def open_details(page, summary_text: str):
    """Open the <details> whose summary carries `summary_text` and return it.
    The metrics footer is a <details> too; naming the summary keeps them apart."""
    summary = page.locator("details summary").filter(has_text=summary_text).first
    expect(summary).to_be_visible(timeout=RENDER_MS)
    # Centred, not merely in view: the composer floats over the last ~120 px of
    # the thread on a phone, and the minimal scroll a click does for itself
    # leaves an element at the bottom edge underneath it. `click` then retries
    # through a re-render on its own, which is why nothing here holds a handle.
    summary.evaluate("element => element.scrollIntoView({block: 'center'})")
    summary.click(timeout=RENDER_MS)
    return page.locator("details").filter(has_text=summary_text).first


@pytest.mark.parametrize(("width", "height"), [DESKTOP, PHONE], ids=["desktop", "phone"])
def test_the_release_walkthrough_of_the_web_ui(browser, chainlit_server, tmp_path, width, height):
    page = open_page(browser, width, height)
    try:
        walk_through_the_release_check(page, chainlit_server)
        # Still empty AFTER the questions, not only after the start. A start
        # writes `.chainlit/`, a `.files/` and a `chainlit.md` where the app
        # root is; an ANSWERED question writes the retrieved passages, and
        # `ASK_SCRATCH_DIR` used to default to a relative `.scratch` — which is
        # the working directory of whoever typed the command.
        left = sorted(path.name for path in chainlit_server.started_in.iterdir())
        assert not left, f"the server wrote {left} into the directory it was started in"
    except Exception:
        # A browser test that fails without a picture of the screen is a bug
        # report with the evidence missing. tmp_path is under --basetemp, which
        # is what CI uploads.
        shot = tmp_path / f"failure-{width}x{height}.png"
        page.screenshot(path=str(shot), full_page=True)
        print(f"\nscreenshot of the failing page: {shot}")
        raise
    finally:
        page.context.close()


def walk_through_the_release_check(page, chainlit_server) -> None:
    """The walk itself, in the order the manual pass went in."""
    # --- first start: the server came up with the scripted backend, and the
    # first thing a browser gets is the login form, not the chat.
    assert "FAKE BACKEND" in chainlit_server.log(), (
        "the server did not report the scripted backend: it may have started with a real one")
    page.goto(chainlit_server.url, wait_until="load", timeout=LOAD_MS)
    expect(page.locator("input#email")).to_be_visible(timeout=LOAD_MS)
    expect(page.locator(COMPOSER)).to_have_count(0)        # no chat before a login

    # --- login, and the first screen: four starters built from the scripted
    # backend's own five-book catalogue, not from a hardcoded shelf. They are
    # Chainlit's welcome screen, which it draws only while the thread holds no
    # message — so this also asserts that nothing is sent into an empty chat.
    log_in(page, chainlit_server)
    starters = page.locator("#starters")
    expect(starters).to_be_visible(timeout=RENDER_MS)
    expect(starters).to_contain_text("Count my library", timeout=RENDER_MS)
    expect(starters).to_contain_text("A question between two books", timeout=RENDER_MS)
    expect(starters).to_contain_text("Ask what the shelf cannot answer", timeout=RENDER_MS)
    # chainlit.md is NOT on this screen: Chainlit 2.12 puts it behind the header's
    # "Readme" button, so the starters are the whole of what a first-time reader
    # sees without clicking. This asserts that, because it is the thing that
    # decides how much the four labels have to carry.
    expect(page.get_by_role("button", name="Readme")).to_be_visible(timeout=RENDER_MS)
    expect(body(page)).not_to_contain_text("counts the quotes traced", timeout=RENDER_MS)

    # --- a research question: the live steps, then the answer. The step labels
    # are the product's own words, not "Used act #1": the name app.py writes is
    # the whole label, because the project's en-US.json empties Chainlit's
    # prefix (design critique 16.09 §1.6).
    ask(page, RESEARCH_QUESTION)
    for name in ("planned the search", "searched the library #1", "picked out the quotes"):
        expect(step(page, name)).to_be_visible(timeout=ANSWER_MS)
    expect(body(page)).not_to_contain_text("Used planned the search", timeout=RENDER_MS)
    # `plan` opens by itself; the rest stay one click away.
    expect(body(page)).to_contain_text("mode: answer", timeout=RENDER_MS)
    expect(body(page)).to_contain_text("who narrates the Pequod voyage", timeout=RENDER_MS)
    expect(body(page)).to_contain_text("retrieval limited to it", timeout=RENDER_MS)
    expect(body(page)).to_contain_text("Ishmael narrates Moby Dick", timeout=ANSWER_MS)

    # --- the badge, with its numbers. Two quotes, and only ONE of them is a
    # quote from the book: the other is verbatim inside the book card, which a
    # model wrote. The headline counts the book text alone and the card says so
    # under it (design critique 16.09 §1.1).
    expect(body(page)).to_contain_text(BADGE, timeout=ANSWER_MS)
    expect(body(page)).to_contain_text("evidence passages 1/1 traced to their source",
                                       timeout=RENDER_MS)
    expect(body(page)).to_contain_text("+1 matched only a book card", timeout=RENDER_MS)
    expect(body(page)).to_contain_text("Evidence items (2, in 2 passage(s))", timeout=RENDER_MS)

    # --- an evidence passage: OPENED and readable, not merely sent. (2.12
    # rendered these as code snippets and dropped the text inside them.)
    wait_for_the_run_to_finish(page, ANSWER_MS)
    passage = open_details(page, "s1h1")
    expect(passage).to_contain_text("Moby Dick — Herman Melville — Summary", timeout=RENDER_MS)
    # and the reader can see WHAT they opened: this one is the card
    expect(passage).to_contain_text("book card (a model-written summary)", timeout=RENDER_MS)
    expect(passage).to_contain_text("from a book card, not a quote from the book",
                                    timeout=RENDER_MS)
    # A sentence that is only in the passage, never in the answer or the quote:
    # seeing it proves the passage body itself is on the screen.
    expect(passage.get_by_text("The voyage ends in ruin", exact=False)).to_be_visible(
        timeout=RENDER_MS)

    # --- the catalogue path: a count computed by code, no quotes to trace
    ask(page, CATALOGUE_QUESTION)
    expect(body(page)).to_contain_text("5 books in your library (by the index tables)",
                                       timeout=ANSWER_MS)
    expect(body(page)).to_contain_text("Where the Wild Things Are — Maurice Sendak",
                                       timeout=RENDER_MS)
    expect(body(page)).to_contain_text(CATALOGUE_BADGE, timeout=RENDER_MS)
    expect(body(page)).to_contain_text("exhaustive: 5 of 5 books listed by code", timeout=RENDER_MS)

    # --- a reload: the conversation is restored, both questions still there.
    # Chainlit moves the browser onto /thread/<id> once the conversation is
    # persisted; that address is what a reload resumes, and reloading "/" before
    # it appears opens a new chat instead — so the move is waited for, not
    # assumed.
    thread_url = thread_address(page, RENDER_MS)
    page.goto(thread_url, wait_until="load", timeout=LOAD_MS)   # already there in a wide window
    page.reload(wait_until="load", timeout=LOAD_MS)
    expect(page.locator(COMPOSER)).to_be_visible(timeout=LOAD_MS)
    expect(body(page)).to_contain_text(RESEARCH_QUESTION, timeout=RENDER_MS)
    expect(body(page)).to_contain_text(CATALOGUE_QUESTION, timeout=RENDER_MS)
    expect(body(page)).to_contain_text("Ishmael narrates Moby Dick", timeout=RENDER_MS)
    expect(body(page)).to_contain_text("5 books in your library", timeout=RENDER_MS)
    assert page.url == thread_url, f"the reload left the thread: {page.url}"

    # --- a clarify nobody answers: the ask-back names its candidates, the run
    # waits AYL_CLARIFY_TIMEOUT_S for a reply it never gets, and then finishes
    # anyway. The UI must not be left holding the question.
    # Nothing of this leg may be on the screen yet: every assertion below is
    # "this text is somewhere on the page", which a conversation that already
    # contains the answer would satisfy without anything happening.
    expect(body(page)).not_to_contain_text(CANDIDATES, timeout=RENDER_MS)
    expect(body(page)).not_to_contain_text("The one hunted across Europe is Dracula",
                                           timeout=RENDER_MS)
    ask(page, CLARIFY_QUESTION)
    expect(body(page)).to_contain_text("Are you thinking of Dracula or of Frankenstein?",
                                       timeout=ANSWER_MS)
    # The numbered list is built by code, never by the model (nodes._clarify_candidates),
    # so it is the one part of an ask-back that is always there. Its "1)" and "2)"
    # become an ordered list's markers in the rendered markdown and are not text on
    # the page; the candidate keys are.
    ask_back = page.locator("div.ai-message").filter(has_text=CANDIDATES).last
    expect(ask_back).to_contain_text(CANDIDATES, timeout=RENDER_MS)
    expect(ask_back).to_contain_text("Dracula — Bram Stoker", timeout=RENDER_MS)
    expect(ask_back).to_contain_text("Frankenstein — Mary Shelley", timeout=RENDER_MS)

    # The ask-back expiring, plus the run that follows it.
    expect(body(page)).to_contain_text("The one hunted across Europe is Dracula",
                                       timeout=chainlit_server.clarify_timeout_s * 1000 + ANSWER_MS)
    # Three quotes, two of them off book cards: one quote from a book.
    expect(body(page)).to_contain_text("evidence passages 1/1 traced to their source",
                                       timeout=RENDER_MS)
    expect(body(page)).to_contain_text("+2 matched only a book card", timeout=RENDER_MS)
    # Still a working chat: the composer takes the next question.
    expect(page.locator(COMPOSER)).to_be_editable(timeout=RENDER_MS)
    page.fill(COMPOSER, "and who wrote it?")
    expect(page.locator(COMPOSER)).to_have_value("and who wrote it?", timeout=RENDER_MS)
