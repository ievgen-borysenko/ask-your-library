---
date: 2026-09-18
tags: [book, tech-shelf]
type: book-card
source: "Adam Wiggins — The Twelve-Factor App"
card_model: openrouter/anthropic/claude-sonnet-4.6
card_built: 2026-09-18
---
# The Twelve-Factor App — Adam Wiggins

## Summary

The Twelve-Factor App is a methodology guide written by Adam Wiggins, drawing on experience developing and operating hundreds of applications on the Heroku platform. Addressed to developers building software-as-a-service applications and to ops engineers who deploy them, it argues that modern web apps should follow twelve discrete principles to achieve portability, resilience, and continuous deployability without server administration overhead. The guide is organised as a brief contextual introduction followed by twelve numbered factors, each stating a rule and explaining its rationale. Together the factors address the full lifecycle of an application: source control, dependency management, configuration, external services, the build pipeline, process execution, networking, scaling, robustness, environment parity, observability, and administrative tasks.

## Key ideas

- **One codebase, many deploys** — a twelve-factor app is always tracked in a single version-control repository, with multiple deploys (production, staging, local) derived from that one codebase. (4. I. Codebase)
- **Explicit dependency declaration and isolation** — the app declares all dependencies completely via a manifest and uses an isolation tool so no implicit system-wide packages can leak in. (5. II. Dependencies)
- **Config stored in the environment** — everything that varies between deploys (credentials, resource handles, per-deploy values) must be stored in environment variables, strictly separated from code. (6. III. Config)
- **Backing services as attached resources** — the app makes no distinction between local and third-party services; both are treated as attached resources accessed via URLs or credentials held in config. (7. IV. Backing services)
- **Strict separation of build, release, and run stages** — a codebase passes through a build stage, is combined with config to form an immutable release, and is then executed; changes to code at runtime are impossible. (8. V. Build, release, run)
- **Stateless, share-nothing processes** — all persistent data must live in a backing service; no process may assume that anything cached in memory or on disk will be available to a future request. (9. VI. Processes)
- **Services exported via port binding** — the app is self-contained and exports HTTP (or other protocols) by binding to a port, rather than relying on a runtime-injected web server container. (10. VII. Port binding)
- **Scale out via the process model** — concurrency is achieved by running more processes of the appropriate type rather than by enlarging a single process internally. (11. VIII. Concurrency)
- **Disposable processes with fast startup and graceful shutdown** — processes must start quickly and shut down gracefully on SIGTERM, returning jobs to the queue, to enable elastic scaling and robust deploys. (12. IX. Disposability)
- **Dev/prod parity** — the time gap, personnel gap, and tools gap between development and production should all be minimised to support continuous deployment. (13. X. Dev/prod parity)
- **Logs as event streams** — the app writes its event stream unbuffered to stdout and never manages log files; routing and archival are the responsibility of the execution environment. (14. XI. Logs)
- **Admin tasks as one-off processes** — database migrations and other administrative tasks run as one-off processes against the same release, codebase, and config as the regular application processes. (15. XII. Admin processes)

## Structure

- 1. Introduction
- 2. Background
- 3. Who should read this document?
- 4. I. Codebase
- 5. II. Dependencies
- 6. III. Config
- 7. IV. Backing services
- 8. V. Build, release, run
- 9. VI. Processes
- 10. VII. Port binding
- 11. VIII. Concurrency
- 12. IX. Disposability
- 13. X. Dev/prod parity
- 14. XI. Logs
- 15. XII. Admin processes

## Terms

- **codebase** — a single repository, or set of repositories sharing a root commit, that maps one-to-one to an application.
- **deploy** — a running instance of the app, whether production, staging, or a developer's local environment.
- **backing service** — any service the app consumes over the network as part of normal operation, such as a database, queue, or SMTP server.
- **release** — the combination of a build artifact and its deploy-specific config, forming an immutable, executable unit.
- **process formation** — the array of named process types and their running instances that together perform the app's regular work.
- **dependency isolation** — the use of a tool (such as Virtualenv or Bundler's `bundle exec`) to ensure that only explicitly declared dependencies are available to the app at runtime.
- **vendoring/bundling** — the practice of scoping dependency libraries into the directory containing the app rather than installing them system-wide.

## Themes

- **Portability** — each factor reduces reliance on a specific operating environment, making the app deployable on any modern cloud platform without systems administration.
- **Strict separation of concerns** — the methodology repeatedly enforces hard boundaries: code from config, build from run, app logic from log routing, regular processes from admin tasks.
- **Continuous deployment** — minimising the time, personnel, and tooling gaps between development and production is a recurring goal that multiple factors directly support.
- **Scalability through statelessness** — by forbidding local state and modelling concurrency as additional processes, the methodology ensures the app can scale horizontally without architectural changes.
- **Robustness and operability** — disposability, graceful shutdown, fast startup, and treating logs as streams all serve the goal of an app that can be reliably managed and observed in production.
