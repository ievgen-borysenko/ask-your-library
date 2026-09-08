# Security

## Scope

Ask Your Library is a local, single-user tool. The CLI runs on your machine. The web UI is meant
to run on loopback: every launch command in the README and in `ui.py` passes `--host 127.0.0.1`,
because Chainlit's own default binds to all interfaces and the UI does not override it; it asks for
a password and is not designed to be exposed to a network or run for several users. Prompts,
retrieved passages and answers leave the machine only as calls to the providers you configure:
the answering model (`LLM_BACKEND`), the embedding model (`EMBED_BACKEND`, local Ollama by
default) and, if a LangSmith key and tracing flag are in the environment (either the `LANGCHAIN_`
or the `LANGSMITH_` prefix), tracing. With `LLM_BACKEND=ollama`, `EMBED_BACKEND=ollama`, an
`OLLAMA_URL` on this machine, and `LANGSMITH_TRACING_V2=false` plus `LANGCHAIN_TRACING_V2=false`
nothing leaves the machine; see "Privacy and data flow" and "Threat model" in the README for what
is protected and what is not.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting for this repository (the **Security** tab,
"Report a vulnerability") rather than a public issue. Expect an acknowledgement within a week.
Out of scope: findings that require exposing the UI to a network, running it for untrusted users,
or enabling features the shipped configuration keeps off (MCP, file uploads, sharing, audio).

## Automated checks

`.github/workflows/security.yml` runs two scanners on every pull request, on every push to `main`
and once a week: gitleaks over the commits a change adds, and over the whole history reachable
from the ref on the scheduled run; OSV-Scanner over `uv.lock`, the resolved dependency set CI
installs from. A secret, or an advisory without a recorded exception, fails the job and blocks the
merge — and so does a scanner that cannot run, which is why neither job is marked
`continue-on-error`. An exception is an `[[IgnoredVulns]]` entry in `osv-scanner.toml` naming the
advisory, the mitigation that keeps it out of this repository, an owner and a review date after
which the scanner reports it again. Both workflows pin every third-party action to a commit SHA
with its version in a comment, and `.github/dependabot.yml` proposes those bumps weekly, one
grouped pull request per ecosystem. CI holds no credentials — no API key, no provider account, and
the tests never make a paid call — so a pull request from a fork has nothing to steal: it runs
with the same read-only token as any other.

## Known dependency advisories

Chainlit 2.11.1 (the web UI) has two published advisories about its MCP transports (command
injection over stdio, SSRF over HTTP/SSE). This repository ships with MCP and every MCP transport
disabled in `.chainlit/config.toml`, which is the mitigation the Chainlit maintainers name; the
upgrade to a fixed release is planned as a separate maintenance change and is required before MCP
is enabled or the UI is deployed anywhere but locally. Both are recorded in `osv-scanner.toml`
with that mitigation, an owner and a review date.
