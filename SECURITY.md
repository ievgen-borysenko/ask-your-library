# Security

## Scope

Ask Your Library is a local, single-user tool. The CLI runs on your machine. The web UI is meant
to run on loopback: every launch command in the README and in `ui.py` passes `--host 127.0.0.1`,
because Chainlit's own default binds to all interfaces and the UI does not override it; it asks for
a password and is not designed to be exposed to a network or run for several users. Loopback is not
by itself a boundary against the browser on the same machine, so `ui.py` also refuses every `Host`
header other than `localhost` and `127.0.0.1` (Starlette's `TrustedHostMiddleware`) and sets its
login cookie to `SameSite=strict` on Chainlit's cookie module, `CHAINLIT_COOKIE_SAMESITE` being
already read by the time `chainlit run` loads `ui.py`; see "Threat model" in the README. Prompts,
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
and once a week. gitleaks (a release binary verified against a pinned SHA-256, not the action
wrapper) scans an explicit range: on a pull request every commit between its merge base with the
target branch and its head, merged branches included; on a push to `main` the pushed range; on the
weekly run, and on the one push that has no "before" commit, every commit reachable from any ref.
That push is the first one of `main` itself, at the creation of the repository: `main` is the
only branch the workflow reacts to, so no other branch ever arrives here without a "before". Each
merge commit's own diff against its first parent is read as well, and it has to be asked for by
name — `git log -p`, which is what gitleaks parses, prints nothing at all for a merge unless it
is told to. A merge can introduce content no side branch holds, a conflict resolved by writing a
key into the file being reconciled being the plain case, and such a key sat in no commit's patch
but the merge's: the range still counted its commits, so the scan passed without ever reading
them. At the time of this change, that was fourteen of the fifty commits the history then held.
The range is resolved before the scan, in its own assignment, and a range git cannot resolve now
fails the step. Inside the `echo` that reported the commit count it did not, because a command
substitution in an argument of a succeeding command discards its exit status: gitleaks then
logged "Invalid revision range", scanned nothing and exited 0. A range that resolves but holds no
commit fails the step too, for the same reason: a scan of zero commits is not a pass. Both
failures describe a force-push of `main`, and both are meant: one that moves the branch backwards
leaves a range of no commits, one whose "before" the repository no longer holds leaves a range
git cannot resolve, and neither of them is a scan.
OSV-Scanner runs over `uv.lock`, the resolved dependency set CI installs from. A secret, or an
advisory without a recorded exception, fails the job — and so does a scanner that cannot run, which
is why neither job is marked `continue-on-error`. A failed job blocks the merge once the
repository's branch protection lists it as a required check; GitHub offers that setting on public
repositories and on paid plans, and this repository is private on the free plan until its first
release, so until then a red check is honoured by hand and nothing merges over it. An exception is
an `[[IgnoredVulns]]` entry in `osv-scanner.toml` naming the advisory, the mitigation that keeps it
out of this repository, an owner and a review date after which the scanner reports it again.
Both workflows pin every third-party action to a commit SHA
with its version in a comment; the pin covers the action's code, not the container image the
OSV action fetches at run time by version. `.github/dependabot.yml` proposes those
bumps weekly, one grouped pull request per ecosystem for version updates and one for security
updates. CI holds no credentials — no API key, no provider account, and
the tests never make a paid call — so a pull request from a fork has nothing to steal: it runs
with the same read-only token as any other.

## Known dependency advisories

Open: none, as of the evening of 08.09, when the lockfile moved httpx2 to 2.12.0. The weekly OSV
job, not this paragraph, is the current state, because an unchanged lockfile can go red when the
advisory database moves: three advisories against httpx2 2.10.0 were published on 08.09 at about
20:45 UTC, between two green runs, and the bump that closed them was committed the same evening. No
advisory carries an exception: `osv-scanner.toml` holds no `[[IgnoredVulns]]` entry. Chainlit
2.11.1 carried two advisories about its MCP transports (command injection over stdio, SSRF over
HTTP/SSE); this repository never enabled MCP, and the upgrade to Chainlit 2.12.0 closed both. MCP
stays disabled (`[features.mcp] enabled = false` in `.chainlit/config.toml`, which is what makes
every transport unreachable; user-connected servers are off as well); enabling MCP is a deliberate
change that starts with re-reading this file. The OSV-Scanner job in
`.github/workflows/security.yml` reports any new advisory.
