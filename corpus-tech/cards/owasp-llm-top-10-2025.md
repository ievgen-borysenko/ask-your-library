---
date: 2026-09-18
tags: [book, tech-shelf]
type: book-card
source: "OWASP Top 10 for LLM Applications Team — OWASP Top 10 for LLM Applications 2025"
card_kind: shared
card_model: openrouter/anthropic/claude-sonnet-4.6
card_built: 2026-09-18
licence: CC-BY-SA-4.0
licence_url: https://creativecommons.org/licenses/by-sa/4.0/legalcode
work_url: https://genai.owasp.org/download/43299/
adapted: "a model-written summary of the work, not the work itself"
card_licence: CC-BY-SA-4.0
card_licence_url: https://creativecommons.org/licenses/by-sa/4.0/legalcode
---
# OWASP Top 10 for LLM Applications 2025 — OWASP Top 10 for LLM Applications Team

## Summary

The OWASP Top 10 for LLM Applications 2025, published in November 2024 by the OWASP Top 10 for LLM Applications Team, is a security reference guide aimed at developers, architects, and security practitioners building or evaluating systems that incorporate large language models. The guide catalogues and explains the ten most critical vulnerability classes specific to LLM-based applications, arguing that LLMs introduce risks that extend well beyond traditional software security concerns — including novel attack surfaces in training pipelines, inference behaviour, agent autonomy, and retrieval systems. Each entry describes the vulnerability, its common manifestations, and the conditions that amplify its impact. The guide is organised as a numbered list of vulnerabilities (LLM01 through LLM10), preceded by front matter covering licensing and revision history, and is intended to serve as a practical checklist for identifying and mitigating LLM-specific security weaknesses.

## Key ideas

- **Prompt injection manipulates model behaviour through crafted inputs** — User or indirect inputs can override intended model behaviour, bypass safety measures, enable unauthorised access, and influence critical decisions, even when the injected content is not human-readable. (LLM01:2025 Prompt Injection)
- **LLMs can expose sensitive data through their outputs** — Personal, financial, health, and proprietary information present in training data or application context may be disclosed in model responses, constituting privacy violations and intellectual property breaches. (LLM02:2025 Sensitive Information Disclosure)
- **Third-party components and pre-trained models introduce supply-chain risks** — Outdated packages, tampered models, licensing violations, and on-device LLMs all expand the attack surface beyond what traditional software dependency management addresses. (LLM03:2025 Supply Chain)
- **Training data manipulation can embed backdoors and biases into models** — Poisoning attacks targeting pre-training, fine-tuning, or embedding stages compromise model integrity and can create hidden triggers that alter behaviour without detection. (LLM04: Data and Model Poisoning)
- **Unvalidated LLM outputs passed downstream can cause XSS, SSRF, and remote code execution** — Because LLM output can be shaped by prompt input, failing to sanitise it before use in other system components is equivalent to granting users indirect access to those components. (LLM05:2025 Improper Output Handling)
- **Granting LLMs excessive functionality, permissions, or autonomy enables damaging actions** — When an LLM agent can call functions or interact with external systems beyond what is necessary, hallucinations or injected prompts can trigger real-world harm across confidentiality, integrity, and availability. (LLM06:2025 Excessive Agency)
- **System prompts should not be treated as secrets or security controls** — The real risk of system prompt leakage lies not in disclosure of the prompt text itself but in the underlying issues it reveals, such as embedded credentials, bypassed authorisation, or improper privilege separation. (LLM07:2025 System Prompt Leakage)
- **Weaknesses in vector storage and retrieval can expose sensitive information and corrupt outputs** — Inadequate access controls on embedding databases, cross-context leakage in multi-tenant environments, and poisoned vectors can all be exploited to manipulate RAG-augmented LLM responses. (LLM08:2025 Vector and Embedding Weaknesses)
- **Hallucination and overreliance together amplify the harm of LLM misinformation** — LLMs generate statistically plausible but fabricated content, and users who place excessive trust in that content without verification can incorporate false information into critical decisions. (LLM09:2025 Misinformation)
- **Uncontrolled inference enables denial of service, financial exhaustion, and model theft** — Allowing users to trigger excessive or unbounded LLM inference depletes computational resources, imposes unsustainable cloud costs, and can facilitate cloning of model behaviour. (LLM10:2025 Unbounded Consumption)

## Structure

- Front matter
- LLM01:2025 Prompt Injection
- LLM02:2025 Sensitive Information Disclosure
- LLM03:2025 Supply Chain
- LLM04: Data and Model Poisoning
- LLM05:2025 Improper Output Handling
- LLM06:2025 Excessive Agency
- LLM07:2025 System Prompt Leakage
- LLM08:2025 Vector and Embedding Weaknesses
- LLM09:2025 Misinformation
- LLM10:2025 Unbounded Consumption

## Terms

- **Prompt Injection** — Manipulation of an LLM's behaviour or output by crafting inputs that cause the model to override its guidelines, bypass safety measures, or pass unintended data to other system components.
- **Jailbreaking** — A specific form of prompt injection in which inputs cause the model to disregard its safety protocols entirely, requiring ongoing model training updates rather than only prompt-level defences.
- **Data Poisoning** — Deliberate manipulation of pre-training, fine-tuning, or embedding data to introduce vulnerabilities, backdoors, or biases that compromise model security, performance, or ethical behaviour.
- **Excessive Agency** — A vulnerability arising when an LLM-based system is granted excessive functionality, permissions, or autonomy, enabling harmful real-world actions triggered by unexpected, ambiguous, or manipulated model outputs.
- **Retrieval Augmented Generation (RAG)** — A model adaptation technique that enhances LLM response relevance by combining pre-trained language models with external knowledge sources retrieved via vector and embedding mechanisms.
- **Hallucination** — The generation by an LLM of content that appears accurate but is fabricated, produced by filling gaps in training data using statistical patterns without genuine understanding.
- **Denial of Wallet (DoW)** — An attack that initiates a high volume of LLM operations to exploit per-use cloud pricing, imposing unsustainable financial costs on the service provider.
- **Overreliance** — Excessive user trust in LLM-generated content without independent verification, which amplifies the real-world impact of misinformation and hallucination.

## Themes

- **Trust boundary erosion** — Across multiple vulnerabilities, the guide shows how LLMs blur traditional trust boundaries between user input, system instructions, external data, and downstream components, creating novel attack paths.
- **Integrity of the model lifecycle** — Supply chain risks, data poisoning, and embedding weaknesses collectively demonstrate that security must be considered at every stage from data collection and training through deployment and retrieval.
- **Principle of least privilege for AI agents** — Excessive agency, improper output handling, and system prompt leakage all point to the recurring need to restrict what LLMs and their extensions are permitted to access, execute, or return.
- **Inadequacy of prompt-level controls alone** — The guide repeatedly notes that system prompt restrictions, RAG, and fine-tuning do not fully mitigate vulnerabilities such as prompt injection, sensitive disclosure, or misinformation, requiring deeper architectural and training-level safeguards.
- **Resource and economic risk as a security concern** — Unbounded consumption frames computational exhaustion and financial damage as first-class security threats alongside traditional confidentiality and integrity concerns.
- **Human factors amplifying technical vulnerabilities** — Overreliance on LLM outputs and insufficient user awareness of data disclosure risks are identified as forces that compound the harm caused by technical weaknesses.
