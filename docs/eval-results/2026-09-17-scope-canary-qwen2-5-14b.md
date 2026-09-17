# Scope canary — 2026-09-17

- prompt set: `eval/scope/out-of-scope.yaml` (9 requests)
- answering model: `qwen2.5:14b` via `ollama`
- code: `4b8a012`
- harness: `eval/scope_canary.py`, scored by `is_refusal` from `eval/run_agent_eval.py`
- result: **7/9 REFUSED**, in-scope controls **4/4 not refused**

| # | id | kind | verdict | mode | steps | calls | note |
|---|----|------|---------|------|-------|-------|------|
| 1 | sc01-code-linked-list | code | REFUSED | refusal | 0 | 1 | - |
| 2 | sc02-world-capital | world-knowledge | REFUSED | refusal | 0 | 1 | - |
| 3 | sc03-persona-chatbot | persona | REFUSED | refusal | 0 | 1 | - |
| 4 | sc04-opinion | opinion | REFUSED | refusal | 0 | 1 | - |
| 5 | sc05-translation | translation | REFUSED | refusal | 0 | 1 | - |
| 6 | sc06-arithmetic | math | REFUSED | refusal | 0 | 1 | - |
| 7 | sc07-chit-chat | chit-chat | REFUSED | refusal | 0 | 1 | - |
| 8 | sc08-poem-in-the-style-of-a-book | persona | ANSWERED | answer | 2 | 6 | the answer does not refuse, it answers the request (no declared marker, but it does not refuse) |
| 9 | sc09-publication-history | library-adjacent-but-not-in-books | ANSWERED | answer | 4 | 10 | the answer does not refuse, it answers the request: ['published in 1897'] |

## In-scope controls (real golden questions, same run, same model)

The gate must not fire on any of these. Each is capped at 120 s: the question asked of them is whether `plan` refused, not how good the answer is.

| id | golden set | gate fired | mode | steps | evidence | why this question |
|----|------------|------------|------|-------|----------|-------------------|
| c09-shipwreck-first-person | `en-demo.yaml` | no | identify | 3 | 2 | a vague half-remembered book: no title, no fact, the shape closest to chit-chat |
| k09-mention-london | `en-demo-catalog.yaml` | no | answer | 1 | 5 | an aggregation over the shelf: reads like a listing, needs the books' content |
| h16-which-stoic-book | `en-demo-extended.yaml` | no | answer | 3 | 4 | a recommendation — which of the two should I start — and therefore the likeliest false refusal under the 'give your own opinion' line of PLAN_RULES |
| k06-count-ua | `en-demo-catalog.yaml` | no | catalog | 0 | 0 | the same product in Ukrainian: the rule is written in English and the reader is not |

## What each request was answered with

**sc01-code-linked-list** — stop: outside the library: the request asks for something the library cannot supply — refused without a search

> This is a search over your own book library, not a general assistant: I answer only from what the books on your shelf say, and I cannot answer a request the library cannot supply. Ask me about a book on your shelf instead.

**sc02-world-capital** — stop: outside the library: the request asks for something the library cannot supply — refused without a search

> This is a search over your own book library, not a general assistant: I answer only from what the books on your shelf say, and I cannot answer a request the library cannot supply. Ask me about a book on your shelf instead.

**sc03-persona-chatbot** — stop: outside the library: the request asks for something the library cannot supply — refused without a search

> This is a search over your own book library, not a general assistant: I answer only from what the books on your shelf say, and I cannot answer a request the library cannot supply. Ask me about a book on your shelf instead.

**sc04-opinion** — stop: outside the library: the request asks for something the library cannot supply — refused without a search

> This is a search over your own book library, not a general assistant: I answer only from what the books on your shelf say, and I cannot answer a request the library cannot supply. Ask me about a book on your shelf instead.

**sc05-translation** — stop: outside the library: the request asks for something the library cannot supply — refused without a search

> This is a search over your own book library, not a general assistant: I answer only from what the books on your shelf say, and I cannot answer a request the library cannot supply. Ask me about a book on your shelf instead.

**sc06-arithmetic** — stop: outside the library: the request asks for something the library cannot supply — refused without a search

> This is a search over your own book library, not a general assistant: I answer only from what the books on your shelf say, and I cannot answer a request the library cannot supply. Ask me about a book on your shelf instead.

**sc07-chit-chat** — stop: outside the library: the request asks for something the library cannot supply — refused without a search

> This is a search over your own book library, not a general assistant: I answer only from what the books on your shelf say, and I cannot answer a request the library cannot supply. Ask me about a book on your shelf instead.

**sc08-poem-in-the-style-of-a-book** — stop: requested chapter was already attempted (re-reading cannot show more text)

> Over London's heart, the night's embrace, A shroud of mist, a veil of grace. In the shadows, secrets doth hide, As the gaslights dim, the fog creeps inside. [Dracula — Bram Stoker, CHAPTER VII] The moon's pale gaze, through foggy veils, Seeks the city's silent, shadowy trails. Mist creeps up walls, to windows near, Stealing the light, the night draws near. [Dracula — Bram Stoker, CHAPTER XIX] Gaslight flickers, dim and small, Through the fog, a mere red spark's call. Thick and dense, the mist grows strong, In the room, it lies, a silent throng. [Dracula — Bram Stoker, CHAPTER XIX] Sunrise struggles, but cannot break, The fog's hold tight, its grip awake. A sailor knows, though reason fails, The dawn's light fights, but fog prevails. [Dracula — Bram Stoker, CHAPTER VII]

**sc09-publication-history** — stop: step limit (4) — wanted to keep searching

> Dracula was first published in 1897 [Dracula — Bram Stoker, Summary]. The evidence does not provide information about Bram Stoker's publisher at the time.

