---
date: 2026-09-18
tags: [book, tech-shelf]
type: book-card
source: "Adam Wiggins — The Twelve-Factor App"
card_model: ollama/qwen2.5:14b
card_built: 2026-09-18
---
# The Twelve-Factor App — Adam Wiggins

## Summary

The Twelve-Factor App by Adam Wiggins is a guide for developers building software-as-a-service applications. It outlines twelve principles to ensure apps are portable, scalable, and suitable for continuous deployment. The book covers topics such as codebase management, dependency declaration, configuration isolation, and process execution, aiming to minimize the differences between development and production environments. It is structured into fifteen chapters, each focusing on a specific aspect of the twelve-factor methodology.

## Key ideas

- **Codebase tracked in revision control** — A single codebase is tracked in a version control system, with multiple deploys from the same codebase (I. Codebase).
- **Explicit dependency declaration** — Dependencies are declared in a manifest and isolated during execution (II. Dependencies).
- **Configuration stored in environment** — Configurations are stored in the environment rather than hardcoded in the code (III. Config).
- **Backing services as attached resources** — Backing services are treated as external resources accessed via URLs or credentials (IV. Backing services).
- **Strict separation of build and run stages** — The build, release, and run stages are strictly separated to ensure reproducibility (V. Build, release, run).
- **Stateless processes** — Processes are stateless and share-nothing, with data stored in stateful backing services (VI. Processes).
- **Port binding for service export** — Services are exported via port binding, allowing the app to be self-contained and web-facing (VII. Port binding).
- **Process model for concurrency** — Processes are disposable and can be scaled out via process types to handle diverse workloads (VIII. Concurrency).
- **Fast startup and graceful shutdown** — Processes start quickly and shut down gracefully to ensure robustness and scalability (IX. Disposability).
- **Dev/prod parity** — Development, staging, and production environments are kept as similar as possible to facilitate continuous deployment (X. Dev/prod parity).
- **Logs as event streams** — Logs are treated as event streams, written to stdout and managed by the execution environment (XI. Logs).
- **Admin tasks as one-off processes** — Administrative tasks are run as one-off processes in the same environment as regular processes (XII. Admin processes).

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

- **Codebase** — A single repository or set of repositories sharing a root commit, tracked in version control.
- **Dependency declaration** — A manifest file listing all dependencies required by the application.
- **Dependency isolation** — A tool that ensures dependencies are isolated from the surrounding system during execution.
- **Backing services** — External services accessed via URLs or credentials, such as databases or messaging systems.
- **Release** — A combination of a build and configuration ready for immediate execution in the execution environment.

## Themes

- **Portability** — Ensuring the application can run on any execution environment without modification.
- **Continuous deployment** — Facilitating rapid and reliable deployment of code changes.
- **Configuration management** — Managing configurations to minimize differences between development and production environments.
- **Process management** — Designing processes to be stateless and disposable for robustness and scalability.
