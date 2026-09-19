---
date: 2026-09-18
tags: [book, tech-shelf]
type: book-card
source: "Shunyu Yao, Jeffrey Zhao, Dian Yu, Nan Du, Izhak Shafran, Karthik Narasimhan, Yuan Cao — ReAct: Synergizing Reasoning and Acting in Language Models"
card_kind: shared
card_model: openrouter/anthropic/claude-sonnet-4.6
card_built: 2026-09-18
licence: CC-BY-4.0
licence_url: https://creativecommons.org/licenses/by/4.0/
work_url: https://arxiv.org/html/2210.03629
adapted: "a model-written summary of the work, not the work itself"
---
# ReAct: Synergizing Reasoning and Acting in Language Models — Shunyu Yao, Jeffrey Zhao, Dian Yu, Nan Du, Izhak Shafran, Karthik Narasimhan, Yuan Cao

## Summary

ReAct: Synergizing Reasoning and Acting in Language Models is a 2022 research paper by Shunyu Yao, Jeffrey Zhao, Dian Yu, Nan Du, Izhak Shafran, Karthik Narasimhan, and Yuan Cao (Princeton University and Google Brain), addressed to researchers working on large language models and autonomous agents. The paper proposes ReAct, a prompting method that augments an LLM's action space with a language "thought" space, enabling the model to interleave reasoning traces and task-specific actions in a single trajectory. The authors argue that this synergy overcomes the limitations of reasoning-only approaches (which hallucinate or lose track of context) and acting-only approaches (which cannot plan or recover from errors). The work is organised as an introduction motivating the idea, a formal description of the method, evaluations on knowledge-intensive reasoning tasks (HotPotQA, FEVER) and interactive decision-making tasks (ALFWorld, WebShop), related work, and a conclusion, followed by appendices covering additional results, experiment details, prompts, trajectories, and error analysis.

## Key ideas

- **Interleaved reasoning and acting** — ReAct extends the agent's action space to include free-form language thoughts that update context without affecting the environment, allowing reasoning and acting to mutually support each other. (2 ReAct: Synergizing Reasoning + Acting)
- **Superiority over reasoning-only and acting-only baselines** — On HotPotQA and FEVER, ReAct outperforms chain-of-thought (CoT) prompting alone and action-only prompting alone, reducing hallucination and improving grounding. (3 Knowledge-Intensive Reasoning Tasks)
- **Wikipedia API interaction for knowledge retrieval** — ReAct uses search, lookup, and finish actions against a Wikipedia API to retrieve external information during multi-hop question answering and fact verification. (3 Knowledge-Intensive Reasoning Tasks)
- **Strong performance on interactive decision-making** — On ALFWorld and WebShop, ReAct substantially outperforms imitation-learning-style and action-only baselines by using thoughts to decompose goals, track subgoals, and apply commonsense knowledge. (4 Decision Making Tasks)
- **Generality across LLMs** — ReAct prompting is effective with both PaLM-540B and GPT-3 (text-davinci-002), with GPT-3 achieving higher scores, suggesting the method is not model-specific. (Appendix A Additional Results)
- **Fine-tuning extends ReAct beyond prompt-length limits** — Fine-tuning smaller PaLM models (8B, 62B) on ReAct-style trajectories yields promising results, addressing the in-context length constraint that limits few-shot ReAct on complex tasks. (Appendix B Experiment Details)
- **Interpretable decision traces** — Because thoughts are explicit natural-language steps, ReAct trajectories are human-readable and diagnosable, enabling identification of distinct success and failure modes. (Appendix E More Analysis)
- **Ability to obtain up-to-date knowledge** — By interacting with live Wikipedia, ReAct can answer questions correctly even when dataset labels are outdated, unlike CoT or standard prompting. (Appendix A Additional Results)

## Structure

- Abstract
- 1 Introduction
- 2 ReAct: Synergizing Reasoning + Acting
- 3 Knowledge-Intensive Reasoning Tasks
- 4 Decision Making Tasks
- 5 Related Work
- 6 Conclusion
- References
- Appendix A Additional Results
- Appendix B Experiment Details
- Appendix C Prompts
- Appendix D Trajectories
- Appendix E More Analysis

## Terms

- **ReAct** — The proposed method that augments an agent's action space with a language thought space, enabling interleaved reasoning traces and environment-affecting actions within a single trajectory.
- **thought (reasoning trace)** — An action taken in the language space that does not affect the external environment but updates the agent's context to support subsequent reasoning or acting.
- **action space augmentation** — The formal extension of the standard action set 𝒜 to 𝒜̂ = 𝒜 ∪ ℒ, where ℒ is the space of language thoughts.
- **Act** — The ablation baseline that uses only environment-affecting actions with no reasoning traces, used to isolate the contribution of thoughts.
- **CoT (Chain-of-Thought)** — A reasoning-only baseline where the model generates a reasoning chain without interacting with an external environment, used as a comparison to ReAct.
- **ReAct-IM** — An ablation variant of ReAct for ALFWorld in which thoughts are restricted to dense external-feedback style, lacking internal subgoal tracking and commonsense inference.

## Themes

- **Synergy between reasoning and acting** — The central claim is that reasoning and acting are mutually reinforcing: reasoning guides what actions to take, and observations from actions ground and correct ongoing reasoning.
- **Grounding to reduce hallucination** — A recurring concern is that pure reasoning models hallucinate facts, and external interaction via actions provides the grounding needed to correct or avoid such errors.
- **Interpretability and controllability of LLM agents** — By making the reasoning process explicit as natural-language thoughts, ReAct produces transparent trajectories that expose how and why decisions are made.
- **Generalisation across task types** — The paper consistently tests whether findings hold across both knowledge-intensive reasoning tasks and long-horizon interactive decision-making tasks, treating breadth of evaluation as a core requirement.
- **Scalability and limitations of in-context learning** — The work repeatedly confronts the constraint that few-shot prompting is bounded by input length, motivating fine-tuning experiments and flagging this as a direction for future work.
