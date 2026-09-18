---
date: 2026-09-18
tags: [book, tech-shelf]
type: book-card
source: "Darren Edge, Ha Trinh, Newman Cheng, Joshua Bradley, Alex Chao, Apurva Mody, Steven Truitt, Jonathan Larson — From Local to Global: A Graph RAG Approach to Query-Focused Summarization"
card_model: openrouter/anthropic/claude-sonnet-4.6
card_built: 2026-09-18
---
# From Local to Global: A Graph RAG Approach to Query-Focused Summarization — Darren Edge, Ha Trinh, Newman Cheng, Joshua Bradley, Alex Chao, Apurva Mody, Steven Truitt, Jonathan Larson

## Summary

This paper, by Darren Edge and colleagues at Microsoft, proposes GraphRAG, a method that combines knowledge graph construction with query-focused summarization (QFS) to enable large language models to answer global sensemaking questions over entire private document corpora. Standard retrieval-augmented generation (vector RAG) retrieves locally relevant text chunks but fails on questions requiring holistic understanding of a dataset; prior QFS methods do not scale to RAG-sized corpora. GraphRAG addresses both limitations by using an LLM to extract an entity-relationship graph from source documents, detecting hierarchical communities in that graph via the Leiden algorithm, generating summaries of each community, and then applying map-reduce summarization over those summaries at query time. The paper is organised as an introduction to the problem, a background survey, a detailed methods section, an experimental analysis on two ~1-million-token corpora, results and discussion, and appendices covering extraction prompts, community detection examples, context window selection, evaluation prompts, and statistical analysis.

## Key ideas

- **GraphRAG pipeline** — Source documents are chunked, entities and relationships are LLM-extracted into a graph, communities are detected hierarchically, and community summaries are used for map-reduce query answering. (3 Methods)
- **Sensemaking queries** — Vector RAG fails on global questions requiring reasoning over connections across an entire corpus, which GraphRAG is specifically designed to handle. (2 Background)
- **Hierarchical community summarisation** — The Leiden algorithm partitions the entity graph into nested community levels (C0–C3), each yielding a different granularity of pre-computed summaries for query time. (3 Methods)
- **Map-reduce answer generation** — At query time, each community summary is independently rated for relevance and partially answered, then all partial answers are reduced into a final global answer. (3 Methods)
- **Token cost advantage of root-level communities** — Root-level (C0) community summaries require 9×–43× fewer tokens per query than full map-reduce over source texts while remaining competitive in quality. (5 Results)
- **Comprehensiveness and diversity wins** — All GraphRAG conditions outperformed vector RAG (semantic search) on comprehensiveness and diversity metrics; intermediate community levels also outperformed graph-free text summarisation. (5 Results)
- **Self-reflection in extraction** — A self-reflection prompting step is used during entity and relationship extraction to improve recall, at the cost of additional LLM calls. (Appendix A Entity and Relationship Extraction Approach)
- **Context window size effect** — Counterintuitively, an 8k token context window produced better comprehensiveness than larger windows (16k–64k) and was adopted uniformly across conditions. (Appendix C Context Window Selection)
- **LLM-as-judge evaluation** — Answers are compared pairwise using an LLM grader scoring comprehensiveness, diversity, empowerment, and directness, with winners determined by head-to-head win rates. (Appendix F Evaluation Prompts)
- **Statistical validation** — Non-parametric Wilcoxon signed-rank tests with Holm-Bonferroni correction confirm that GraphRAG improvements over vector RAG are statistically significant. (Appendix G Statistical Analysis)

## Structure

- 1. Abstract
- 2. 1 Introduction
- 3. 2 Background
- 4. 3 Methods
- 5. 4 Analysis
- 6. 5 Results
- 7. 6 Discussion
- 8. 7 Conclusion
- 9. Acknowledgements
- 10. References
- 11. Appendix A Entity and Relationship Extraction Approach
- 12. Appendix B Example Community Detection
- 13. Appendix C Context Window Selection
- 14. Appendix D Example Answer Comparison
- 15. Appendix E System Prompts
- 16. Appendix F Evaluation Prompts
- 17. Appendix G Statistical Analysis

## Terms

- **GraphRAG** — The authors' system combining LLM-derived knowledge graph indexing with hierarchical community summarisation to answer global queries over document corpora.
- **vector RAG (SS)** — The conventional RAG baseline that retrieves text chunks by embedding-based semantic similarity; used as the primary comparison condition labelled "semantic search."
- **sensemaking query** — A question requiring global understanding of an entire dataset rather than retrieval of locally relevant records.
- **community summary** — An LLM-generated textual summary of a detected graph community, stored at index time and used as the unit of context at query time.
- **map-reduce summarization (TS)** — A two-stage process where the LLM generates partial answers over many context units in parallel (map) and then combines them into a final answer (reduce); also used as a graph-free baseline condition.
- **covariate** — A claim or attribute associated with an entity node in the graph index, extracted alongside entities and relationships.
- **comprehensiveness** — An evaluation metric measuring how thoroughly an answer covers all aspects and details of a question.
- **empowerment** — An evaluation metric measuring how well an answer helps the reader understand and make informed judgements about the topic.

## Themes

- **Global vs. local retrieval** — The work is organised around the fundamental tension between retrieval methods that excel locally and summarisation methods needed for corpus-wide questions.
- **Scalability of summarisation** — A recurring concern is reducing the token cost of global summarisation so it becomes practical, addressed through hierarchical community pre-computation.
- **LLM-driven knowledge graph construction** — The use of LLMs not just for answering but for building the index (entity extraction, self-reflection, community report generation) runs throughout the methods and appendices.
- **Evaluation rigour** — The paper consistently addresses the difficulty of evaluating open-ended answers, employing LLM-as-judge pairwise comparison, multiple metrics, repeated runs, and non-parametric statistical testing.
- **Cost-quality trade-offs** — Choices about chunk size, community level, context window, and self-reflection are all framed as trade-offs between token expenditure and answer quality.
