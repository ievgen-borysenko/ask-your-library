---
date: 2026-09-18
tags: [book, tech-shelf]
type: book-card
source: "Noah Shinn, Federico Cassano, Edward Berman, Ashwin Gopinath, Karthik Narasimhan, Shunyu Yao — Reflexion: Language Agents with Verbal Reinforcement Learning"
card_kind: shared
card_model: openrouter/anthropic/claude-sonnet-4.6
card_built: 2026-09-18
licence: CC-BY-4.0
licence_url: https://creativecommons.org/licenses/by/4.0/
work_url: https://arxiv.org/html/2303.11366
adapted: "a model-written summary of the work, not the work itself"
---
# Reflexion: Language Agents with Verbal Reinforcement Learning — Noah Shinn, Federico Cassano, Edward Berman, Ashwin Gopinath, Karthik Narasimhan, Shunyu Yao

## Summary

Reflexion, by Noah Shinn, Federico Cassano, Edward Berman, Ashwin Gopinath, Karthik Narasimhan, and Shunyu Yao (2023), proposes a framework for reinforcing large-language-model agents without updating model weights. Instead of gradient-based training, agents verbally reflect on feedback from their environment, storing those reflections in an episodic memory buffer that conditions future attempts. The paper argues this verbal reinforcement acts as a semantic gradient signal analogous to human iterative learning from failure. It is organised as a core framework description, experiments across three task families (sequential decision-making, reasoning, and code generation), and discussion of limitations and broader impact, supplemented by appendices with additional model evaluations and worked examples for each task type. Reflexion achieves reported improvements of 22% on AlfWorld, 20% on HotPotQA, and 11% on HumanEval over strong baselines.

## Key ideas

- **Verbal reinforcement without weight updates** — Reflexion reinforces agents by converting environment feedback into natural-language reflections rather than performing gradient descent or model fine-tuning. (1 Introduction)
- **Three-model architecture** — The framework decomposes into an Actor that generates actions, an Evaluator that scores outcomes, and a Self-Reflection model that produces verbal improvement cues. (3 Reflexion: reinforcement via verbal reflection)
- **Episodic memory buffer** — Self-reflections are appended to a persistent memory that is passed as context in subsequent trials, allowing the agent to accumulate lessons across episodes. (3 Reflexion: reinforcement via verbal reflection)
- **Flexible feedback types** — Reflexion can incorporate scalar values, binary signals, or free-form language as feedback, from external environments or internally simulated sources. (3 Reflexion: reinforcement via verbal reflection)
- **Self-evaluation for autonomous operation** — For tasks where the environment only signals task completion, the framework implements self-evaluation via LLM-based natural-language classification or hand-written heuristics. (4 Experiments)
- **Emergent capability in stronger models** — The ability to produce useful self-corrections is an emergent quality of larger, stronger models; weaker models such as starchat-beta show no improvement from Reflexion. (Appendix A Evaluation with additional models)
- **Test-driven code generation** — In programming tasks, unit-test results serve as the feedback signal, and the Actor is instructed to revise only the function body based on test outcomes and prior self-reflection. (Appendix C Programming)
- **Local minima risk** — As a policy-optimisation technique, Reflexion may converge to non-optimal local minima and does not guarantee globally optimal solutions. (5 Limitations)
- **Interpretability advantage over classical RL** — Verbal self-reflections can be monitored by humans, making agent intent more diagnosable than black-box gradient-based policies. (6 Broader impact)

## Structure

- Abstract
- 1 Introduction
- 2 Related work
- 3 Reflexion: reinforcement via verbal reflection
- 4 Experiments
- 5 Limitations
- 6 Broader impact
- 7 Conclusion
- 8 Reproducibility
- References
- Appendix A Evaluation with additional models
- Appendix B Decision-making
- Appendix C Programming
- Appendix D Reasoning

## Terms

- **Reflexion** — The authors' framework in which language agents reinforce their behaviour by generating and storing verbal self-reflections rather than updating model weights.
- **Actor (Mₐ)** — The LLM component that generates text and actions conditioned on current state observations within the Reflexion architecture.
- **Evaluator (Mₑ)** — The model component that scores or judges the trajectories produced by the Actor to determine success or failure.
- **Self-Reflection model (Mₛᵣ)** — The model component that takes task feedback and trajectory history and produces a verbal summary of errors and suggested improvements.
- **episodic memory buffer (mem)** — The accumulating list of self-reflection strings that is prepended as context to the Actor's prompt in each new trial.
- **verbal reinforcement** — The paper's term for using natural-language feedback as a substitute for gradient-based reward signals in agent learning.
- **semantic gradient signal** — The authors' characterisation of self-reflective text as providing a concrete improvement direction analogous to a gradient in weight space.

## Themes

- **Learning from failure without retraining** — The central concern throughout is enabling agents to improve across trials using only language, avoiding the compute cost of fine-tuning.
- **Memory as a substitute for parameter updates** — Across all task domains the work treats an external textual memory as the mechanism by which experience is retained and reused.
- **Generality across task types** — The framework is evaluated on decision-making, open-domain reasoning, and code generation to demonstrate breadth of applicability.
- **Model capability as a prerequisite** — Results and appendices consistently show that Reflexion's benefits depend on the underlying LLM being sufficiently capable, raising questions about accessibility.
- **Interpretability and safety of autonomous agents** — The broader impact and limitations sections frame verbal reinforcement as a potential path toward more auditable and alignable agent behaviour.
