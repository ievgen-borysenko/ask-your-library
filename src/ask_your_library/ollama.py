"""Pulling a model into Ollama over its HTTP API, with the progress streamed.

`ayl init` is the only caller. The question "is Ollama there and what has it
pulled" is `preflight.ollama_tags`, the same function the preflight asks it
with; this module only adds the one write: `POST /api/pull`, which streams one
JSON object per line until `{"status": "success"}` — or an `{"error": ...}`
line, which arrives with status 200 once the stream has started, and is the
only way a missing model name is reported.

Which models are pulled is never decided here: `preflight.pull_models` names
them from the configuration.
"""
import json
from collections.abc import Callable

import requests
from requests import RequestException

from .config import OLLAMA_URL

# A pull of a 9 GB model streams for minutes; what is bounded is the wait for
# the NEXT line, not the whole download. Ollama sends a progress line every
# fraction of a second while bytes move, so two minutes of silence is a stall.
CONNECT_TIMEOUT_S = 5
READ_TIMEOUT_S = 120

Progress = Callable[[str, int | None, int | None], None]


class PullError(RuntimeError):
    """The pull did not end in `success`: Ollama said why, or the connection
    went away. The message is the sentence to print."""


def pull(model: str, on_progress: Progress | None = None, url: str | None = None) -> None:
    """Pull `model`, calling `on_progress(status, completed, total)` for every
    line Ollama streams (`completed`/`total` are bytes, or None on the lines
    that are not a download: "pulling manifest", "verifying sha256 digest").

    Returns when Ollama says `success`; raises PullError otherwise, including
    a stream that ends without saying either."""
    base = (OLLAMA_URL if url is None else url).rstrip("/")
    # `model` is the current field name and `name` the older spelling of it;
    # a server ignores the one it does not know.
    body = {"model": model, "name": model, "stream": True}
    try:
        with requests.post(f"{base}/api/pull", json=body, stream=True,
                           timeout=(CONNECT_TIMEOUT_S, READ_TIMEOUT_S)) as response:
            if response.status_code >= 400:
                raise PullError(f"Ollama at {base} refused to pull {model}: HTTP "
                                f"{response.status_code} {_error_of(response.text)}".rstrip())
            for raw in response.iter_lines():
                if not raw:
                    continue
                try:
                    line = json.loads(raw)
                except ValueError:
                    raise PullError(f"Ollama at {base} sent something that is not a pull "
                                    f"progress line while pulling {model}") from None
                if not isinstance(line, dict):
                    raise PullError(f"Ollama at {base} sent something that is not a pull "
                                    f"progress line while pulling {model}")
                if line.get("error"):
                    raise PullError(f"Ollama could not pull {model}: {line['error']}")
                status = str(line.get("status", ""))
                if on_progress is not None:
                    on_progress(status, line.get("completed"), line.get("total"))
                if status == "success":
                    return
    except RequestException as error:
        raise PullError(f"the connection to Ollama at {base} failed while pulling {model}: "
                        f"{type(error).__name__}") from None
    raise PullError(f"Ollama at {base} ended the pull of {model} without saying it succeeded")


def _error_of(text: str) -> str:
    """The `error` field of a JSON error body, or nothing: a body that is not
    Ollama's is not repeated to the reader."""
    try:
        value = json.loads(text)
    except ValueError:
        return ""
    return f"— {value['error']}" if isinstance(value, dict) and value.get("error") else ""
