---
date: 2026-09-18
tags: [book, tech-shelf]
type: book-card
source: "Heather Adkins, Betsy Beyer, Paul Blankinship, Piotr Lewandowski, Ana Oprea, Adam Stubblefield — Building Secure and Reliable Systems"
card_model: openrouter/anthropic/claude-sonnet-4.6
card_built: 2026-09-18
---
# Building Secure and Reliable Systems — Heather Adkins, Betsy Beyer, Paul Blankinship, Piotr Lewandowski, Ana Oprea, Adam Stubblefield

## Summary

*Building Secure and Reliable Systems* (2020), by Heather Adkins, Betsy Beyer, Paul Blankinship, Piotr Lewandowski, Ana Oprea, and Adam Stubblefield — all practitioners at Google — argues that security and reliability are not separate disciplines but inherent, overlapping properties of any system, and that both must be integrated from the earliest design decisions through implementation, maintenance, and organisational culture. Written for software engineers, site reliability engineers, and security engineers, the book is organised in five parts: an introductory section on the intersection of the two disciplines and the nature of adversaries; a design section covering least privilege, understandability, resilience, recovery, and denial-of-service mitigation; an implementation section on writing, testing, and deploying code safely; a maintenance section on disaster planning, crisis management, and recovery; and a final section on organisational roles and building a security-and-reliability culture. Case studies drawn from Google's own infrastructure illustrate each major theme.

## Key ideas

- **Security and reliability are mutually dependent** — A system cannot be considered truly reliable if it is not secure, and cannot be considered secure if it is unreliable, so the two must be designed together from the start. (The Intersection of Security and Reliability)
- **Adversaries must be understood to build resilience** — Studying the tactics, techniques, and procedures of both malicious actors and non-human failure sources (such as power outages caused by animals) is essential to designing survivable systems. (Understanding Adversaries)
- **Safe proxies reduce privileged access risk** — Routing administrative commands through a proxy that audits, rate-limits, and approves operations protects production from both accidental and malicious human actions without requiring changes to underlying systems. (Case Study: Safe Proxies)
- **Security and reliability requirements need not conflict with feature velocity** — Treating security and reliability as nonfunctional requirements that are balanced against functional ones early in design avoids the far greater cost of retrofitting them later. (Design Tradeoffs)
- **Least privilege limits the blast radius of mistakes and compromise** — Systems should be designed so that any person or credential can cause only the minimum damage possible, because human error, phishing, and credential compromise are inevitable. (Design for Least Privilege)
- **Understandability is a prerequisite for safe modification** — A system whose operational behaviour and invariants can be accurately reasoned about is less likely to have security vulnerabilities or resilience failures introduced during changes. (Design for Understandability)
- **Infrastructure must support rapid, safe change** — Because the vulnerability and regulatory landscape shifts constantly, systems must be designed to accept frequent updates without sacrificing reliability. (Design for a Changing Landscape)
- **Resilience and recovery are complementary but distinct design goals** — Resilience delays or withstands breakage so services remain running; recovery restores systems after breakage; both must be designed in deliberately. (Design for Resilience)
- **The software supply chain must be verifiable end-to-end** — Controls on source, build, and test stages have limited value if adversaries can bypass them by deploying directly; each supply-chain step must provide proof of correct execution. (Deploying Code)
- **Debugging access must be balanced against security** — Granting read-only or investigative access creates abuse risk, so logging, access controls, and investigation tooling must be designed to satisfy both operational and security requirements simultaneously. (Investigating Systems)
- **Disaster planning requires continuous, tested preparation** — Rather than hoping systems survive, organisations should maintain incident response teams, pre-stage resources, and regularly test response plans before a crisis occurs. (Disaster Planning)
- **Security and reliability are everyone's responsibility** — Delegating these concerns solely to isolated specialist teams is ineffective; they must be integrated into every role across the organisation and supported by an explicit cultural commitment. (Building a Culture of Security and Reliability)

## Structure

- 1. Foreword by Royal Hansen
- 2. Foreword by Michael Wildpaner
- 3. Preface
- 4. Introductory Material
- 5. The Intersection of Security and Reliability
- 6. Understanding Adversaries
- 7. Designing Systems
- 8. Case Study: Safe Proxies
- 9. Design Tradeoffs
- 10. Design for Least Privilege
- 11. Design for Understandability
- 12. Design for a Changing Landscape
- 13. Design for Resilience
- 14. Design for Recovery
- 15. Mitigating Denial-of-Service Attacks
- 16. Implementing Systems
- 17. Case Study: Designing, Implementing, and Maintaining a Publicly Trusted CA
- 18. Writing Code
- 19. Testing Code
- 20. Deploying Code
- 21. Investigating Systems
- 22. Maintaining Systems
- 23. Disaster Planning
- 24. Crisis Management
- 25. Recovery and Aftermath
- 26. Organization and Culture
- 27. Case Study: Chrome Security Team
- 28. Understanding Roles and Responsibilities
- 29. Building a Culture of Security and Reliability
- 30. Conclusion
- 31. A Disaster Risk Assessment Matrix
- 32. About the Editors

## Terms

- **Safe proxy** — A framework that routes privileged administrative commands through a controlled intermediary that audits, approves, and rate-limits operations, preventing direct access to production systems.
- **Zero Touch Prod** — A Google project aimed at eliminating direct human access to production systems by requiring all changes to flow through automated, audited safe-proxy mechanisms.
- **Software supply chain** — The full sequence of writing, building, testing, and deploying a software system, each step of which must offer verifiable proof of correct execution to prevent adversarial bypass.
- **Understandability** — The extent to which a person with relevant technical background can accurately and confidently reason about both the operational behaviour of a system and its invariants, including security and availability properties.
- **Resilience** — A system's designed ability to hold out against, delay, or withstand major malfunctions or disruptions, keeping services running (possibly in degraded mode) without requiring human intervention.
- **Incident Management at Google (IMAG)** — Google's unified incident-response framework, applied to both reliability outages and security incidents, that structures how teams collaborate and communicate during a crisis.
- **Least privilege** — A design principle requiring that every person, credential, or component be granted only the minimum access needed for its function, so that mistakes or compromises cause the smallest possible harm.
- **Tactics, techniques, and procedures (TTPs)** — The specific methods an adversary uses to target and exploit systems, studied to inform resilient and survivable system design.

## Themes

- **Integration over separation** — The book consistently argues against treating security and reliability as afterthoughts or siloed specialisms, insisting both must be woven into every phase of the system lifecycle.
- **Design as the highest-leverage intervention** — Across all parts, the work returns to the principle that decisions made at design time are the most cost-effective place to address security and reliability concerns.
- **Human fallibility as a design input** — From least-privilege design to crisis management, the book treats human error, credential compromise, and cognitive limits as certainties to be engineered around rather than exceptions to be hoped away.
- **Verifiability and auditability** — Whether discussing safe proxies, the software supply chain, or debugging access, the work emphasises that every significant action in a system should be traceable and provable.
- **Culture and organisation as technical infrastructure** — Part V frames organisational structure, role definition, and cultural norms as engineering problems with the same importance as code or architecture.
- **Preparedness through practice** — Disaster planning, crisis management, and recovery chapters collectively argue that resilience is built by rehearsing responses before incidents occur, not by reacting to them unprepared.
