---
date: 2026-09-18
tags: [book, tech-shelf]
type: book-card
source: "Martin Zinkevich — Rules of Machine Learning"
card_model: openrouter/anthropic/claude-sonnet-4.6
card_built: 2026-09-18
---
# Rules of Machine Learning — Martin Zinkevich

## Summary

*Rules of Machine Learning* is a practical guide written by Martin Zinkevich at Google, aimed at engineers and practitioners with a basic background in machine learning who want to apply Google's accumulated best practices. The work argues that most gains in ML systems come from good engineering, solid infrastructure, and well-crafted features rather than from sophisticated algorithms, and that complexity should be added only after simpler approaches are exhausted. It is organised as a progression through the ML product lifecycle: a terminology reference, guidance on whether to use ML at all, a first-pipeline phase focused on infrastructure, a second phase of feature engineering, and a third phase for handling plateaued growth with more advanced techniques. Forty-three numbered rules structure the advice throughout, supplemented by related-work pointers and an appendix describing Google products used as examples.

## Key ideas

- **Launch without ML first** — heuristics can capture roughly half the value of a full ML solution, so products should not wait for ML when data is absent. (4. Before Machine Learning)
- **Instrument metrics before building models** — tracking as much as possible in the current system before formalising ML objectives makes future evaluation and iteration far easier. (4. Before Machine Learning)
- **Keep the first model simple and get infrastructure right** — the first model delivers the largest product boost and its primary purpose is to validate the end-to-end pipeline, not to be algorithmically impressive. (5. ML Phase I: Your First Pipeline)
- **Feature engineering drives Phase II gains** — the second phase is characterised by pulling in as many features as possible and combining them intuitively, with metrics expected to keep rising throughout. (6. ML Phase II: Feature Engineering)
- **Plan to launch and iterate continuously** — no single model is final; teams should expect to launch new models regularly driven by new features, retuned regularisation, or revised objectives. (6. ML Phase II: Feature Engineering)
- **Slowed growth signals the need for sophistication** — when monthly gains diminish and metrics trade off against each other, the system has entered Phase III and must find more advanced approaches. (7. ML Phase III: Slowed Growth, Optimization Refinement, and Complex Models)
- **Misaligned objectives waste feature-engineering effort** — if product goals are not covered by the algorithmic objective, changing the objective or the goals is more productive than adding new features. (7. ML Phase III: Slowed Growth, Optimization Refinement, and Complex Models)
- **Launch decisions are proxies for long-term product goals** — short-term metric improvements used to justify launches must be evaluated against broader, longer-term product outcomes. (7. ML Phase III: Slowed Growth, Optimization Refinement, and Complex Models)

## Structure

- 1. Page Summary
- 2. Terminology
- 3. Overview
- 4. Before Machine Learning
- 5. ML Phase I: Your First Pipeline
- 6. ML Phase II: Feature Engineering
- 7. ML Phase III: Slowed Growth, Optimization Refinement, and Complex Models
- 8. Related Work
- 9. Acknowledgements
- 10. Appendix

## Terms

- **Instance** — the individual thing about which a prediction is to be made, such as a web page to be classified.
- **Feature Column** — a set of related features (Google-specific terminology), equivalent to a "namespace" in the VW system or a "field" elsewhere.
- **Example** — an instance together with its features and its label, forming the unit used for training.
- **Objective** — the specific metric that the learning algorithm is directly trying to optimise, as distinct from other metrics the team cares about.
- **Pipeline** — the full infrastructure surrounding an ML algorithm, from data gathering through training to model export and serving.
- **Training-serving skew** — the discrepancy that can arise between the data environment at training time and the data environment at serving time, treated as a key pitfall to monitor.

## Themes

- **Engineering over algorithms** — the work consistently argues that infrastructure quality and feature design matter more than algorithmic sophistication at every phase of development.
- **Incremental complexity** — a recurring concern is that adding complexity too early slows future iteration; simplicity should be exhausted before advancing to harder techniques.
- **Metric alignment** — the tension between what is easy to optimise and what actually reflects product or user goals runs through all three ML phases.
- **Lifecycle thinking** — the guide frames ML development as a staged progression with distinct priorities at each phase rather than a single design problem.
- **Continuous iteration** — launching, measuring, and relaunching is presented as the normal operating mode rather than an exception, with each launch informing the next.
