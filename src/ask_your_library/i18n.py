"""Language of the agent's user-facing text (answers, reports, CLI/UI labels).

ASK_LANG=en (default) | ua sets the process-wide default:
  uv run ask-library                     # English
  ASK_LANG=ua uv run ask-library         # Ukrainian
New keys must be added to every language.

Per-session override (web chat, several tabs in different languages at once):
set_lang() writes a contextvars.ContextVar, which lives in the calling context
and is copied into worker threads (anyio's to_thread copies contextvars), so
concurrent sessions never clobber each other. The CLI relies on the default.
"""
import contextvars

from .config import DEFAULT_LANG, SUPPORTED_LANGS

LANG = DEFAULT_LANG

_current = contextvars.ContextVar("ask_lang", default=LANG)


def set_lang(lang: str) -> None:
    """Override the language for the current context (one web session / one run)."""
    if lang in SUPPORTED_LANGS:
        _current.set(lang)


def get_lang() -> str:
    return _current.get()

_T = {
    # ---- nodes: what the user sees in answers and reports
    "refusal_answer": {
        "ua": "Я шукав у картках і транскриптах, але доказів по цьому "
              "питанню в бібліотеці не знайшов. Чесна відповідь: не знаю.",
        "en": "I searched both the book cards and the transcripts, but found "
              "no evidence for this question in the library. Honest answer: I don't know.",
    },
    "verif_no_evidence": {
        "ua": "доказів немає — відповідь і є чесною відмовою",
        "en": "no evidence — the answer itself is an honest refusal",
    },
    "verif_ok": {
        "ua": "OK: всі {n} цитат знайдені дослівно в уривках, на які вони посилаються{unused}",
        "en": "OK: all {n} quotes found verbatim in the passages they cite{unused}",
    },
    "verif_partial": {
        "ua": "ЧАСТКОВО: {ok} з {checked} цитат підтверджено в уривках, на які вони посилаються{unused}",
        "en": "PARTIAL: {ok} of {checked} quotes confirmed in the passages they cite{unused}",
    },
    "verif_warn": {
        "ua": "УВАГА: {broken} з {checked} цитат НЕ знайдені дослівно в жодному знайденому "
              "уривку (можлива галюцинація){unused}:\n  - {items}",
        "en": "WARNING: {broken} of {checked} quotes NOT found verbatim in any "
              "retrieved passage (possible hallucination){unused}:\n  - {items}",
    },
    "unused_note": {
        "ua": " ({n} доказів для книг, яких відповідь не називає, перевірено теж)",
        "en": " ({n} pieces of evidence for books the answer does not name were checked too)",
    },
    "unattributed_note": {
        "ua": " ({n} цитат знайдено в іншому уривку, ніж той, на який вони посилаються — не зараховано)",
        "en": " ({n} quotes found in a retrieved passage other than the one cited — not counted as confirmed)",
    },
    "stop_crag": {
        "ua": "CRAG-gate: {n} сухі кроки поспіль",
        "en": "CRAG gate: {n} dry steps in a row",
    },
    "stop_json": {
        "ua": "fallback: reflect двічі не зміг у валідний JSON",
        "en": "fallback: reflect failed to produce valid JSON twice",
    },
    "stop_chapter_again": {
        "ua": "зупинка: запитаний розділ уже пробували читати (повторне читання не дасть більше тексту)",
        "en": "stopped: requested chapter was already attempted (re-reading cannot show more text)",
    },
    "stop_limit": {
        "ua": "ліміт кроків ({n}) — хотів шукати далі",
        "en": "step limit ({n}) — wanted to keep searching",
    },
    "stop_enough": {
        "ua": "досить доказів",
        "en": "enough evidence",
    },
    "stop_clarify_repeat": {
        "ua": "повторний clarify не дозволено — фінішуємо з наявним",
        "en": "repeated clarify not allowed — finishing with what we have",
    },
    "stop_other": {
        "ua": "reflect: {what}",
        "en": "reflect: {what}",
    },
    "stop_deadline": {
        "ua": "дедлайн питання ({s} с): відповідаю з того, що вже знайдено",
        "en": "question deadline ({s} s) reached: answering from what was found",
    },
    "stop_catalog": {
        "ua": "каталог: відповідь з таблиць індексу, без пошуку",
        "en": "catalog: answered from the index tables, no search",
    },
    "verif_catalog": {
        "ua": "каталог: {n} з {total} книжок перелічено кодом з таблиць індексу (вичерпно; цитат немає)",
        "en": "catalog: {n} of {total} books listed by code from the index tables (exhaustive; no quotes to check)",
    },
    "catalog_count": {
        "ua": "У бібліотеці {n} книжок (за таблицями індексу).",
        "en": "Your library holds {n} books (by the index tables).",
    },
    "catalog_list": {
        "ua": "Книжок у бібліотеці: {n} (за таблицями індексу):\n{items}",
        "en": "{n} books in your library (by the index tables):\n{items}",
    },
    "catalog_has_yes": {
        "ua": "Так, є в бібліотеці:\n{items}",
        "en": "Yes, in your library:\n{items}",
    },
    "catalog_has_no": {
        "ua": "Книжки з назвою «{q}» в бібліотеці немає.",
        "en": "No book titled \"{q}\" is in your library.",
    },
    "catalog_closest_titles": {"ua": " Найближчі назви: {items}.", "en": " Closest titles: {items}."},
    "catalog_by_author": {
        "ua": "Книжок автора {author} в бібліотеці: {n}:\n{items}",
        "en": "{n} book(s) by {author} in your library:\n{items}",
    },
    "catalog_by_author_none": {
        "ua": "Книжок автора «{q}» в бібліотеці немає.",
        "en": "No books by \"{q}\" in your library.",
    },
    "catalog_closest_authors": {"ua": " Найближчі автори: {items}.", "en": " Closest authors: {items}."},
    "history_catalog": {
        "ua": "(відповідь з каталогу: {op}, {n} з {total} книжок; запит: {q}, знайдено: {found}; "
              "перелік назв в історію розмови не зберігається)",
        "en": "(catalogue answer: {op}, {n} of {total} books; asked about: {q}, found: {found}; "
              "the list of titles is not kept in the conversation)",
    },
    "history_yes": {"ua": "так", "en": "yes"},
    "history_no": {"ua": "ні", "en": "no"},
    "book_not_in_catalog": {
        "ua": "(Книжки з назвою «{q}» в каталозі бібліотеки не знайдено; шукав по всій бібліотеці.)",
        "en": "(No book titled \"{q}\" is in the library catalogue; the whole library was searched instead.)",
    },
    "clarify_candidates_list": {
        "ua": "Кандидати з бібліотеки (можна відповісти номером або назвою):\n{items}",
        "en": "Candidates in the library (answer with a number or a title):\n{items}",
    },
    "ui_clarify_unresolved": {
        "ua": "уточнення не збіглося з жодним кандидатом — відповідаю по всіх знайдених книжках",
        "en": "the clarification matched no candidate — answering over all books found",
    },
    "ev_clarify_unresolved": {
        "ua": "[plan] уточнення не збіглося з жодним кандидатом — лишаю всі докази",
        "en": "[plan] clarification matched no candidate — keeping all evidence",
    },
    "clarify_default_q": {
        "ua": "Яку саме книжку ти маєш на увазі?",
        "en": "Which book exactly do you mean?",
    },
    # language instructions for the model (end of the synthesize/reflect prompts)
    "answer_lang_instruction": {
        "ua": "Answer in the language of the question.",
        "en": "Answer in English regardless of the question language.",
    },
    "clarify_lang_instruction": {
        "ua": "IN THE LANGUAGE OF THEIR QUESTION",
        "en": "IN ENGLISH",
    },

    # ---- preflight: the three typical first-run environment failures
    "pf_no_key": {
        "ua": "Нема ключа OpenRouter: експортуй OPENROUTER_API_KEY (або додай у .env).",
        "en": "OpenRouter key missing: export OPENROUTER_API_KEY (or put it in .env).",
    },
    "pf_no_ollama": {
        "ua": "Не вдалося звернутися до Ollama на {url} (помилка з'єднання або запиту): "
              "запусти `ollama serve` і "
              "`ollama pull bge-m3` (або задай OLLAMA_URL / EMBED_BACKEND).",
        "en": "Could not reach Ollama at {url} (a connection or request error): "
              "run `ollama serve` and "
              "`ollama pull bge-m3` (or set OLLAMA_URL / EMBED_BACKEND).",
    },
    "pf_ollama_bad_reply": {
        "ua": "Щось на {url} відповіло (HTTP {status}), але це не придатна відповідь /api/tags "
              "(помилковий статус, не JSON або несподівана структура). Перевір, що на цій адресі "
              "саме Ollama (`curl {url}/api/tags`).",
        "en": "Something at {url} answered with HTTP {status}, but the reply is not a usable "
              "/api/tags (an error status, not JSON, or an unexpected shape): check that this "
              "address is really Ollama (`curl {url}/api/tags`).",
    },
    "pf_no_db": {
        "ua": "Бази нема: {path}. Побудуй демо-корпус "
              "(`uv run scripts/ingest_demo_corpus.py`, ~30 хв) або вкажи "
              "LIBRARY_DB_PATH на свою LanceDB.",
        "en": "Database not found: {path}. Build the demo corpus "
              "(`uv run scripts/ingest_demo_corpus.py`, ~30 min) or point "
              "LIBRARY_DB_PATH at your LanceDB.",
    },
    "pf_no_tables": {
        "ua": "У базі {path} нема таблиць: {tables}. Заверши інжест "
              "(`uv run scripts/ingest_demo_corpus.py --stage ingest` і --stage cards).",
        "en": "Database {path} is missing tables: {tables}. Finish the ingest "
              "(`uv run scripts/ingest_demo_corpus.py --stage ingest` and --stage cards).",
    },
    "pf_index_mismatch": {
        "ua": "Індекс не відповідає налаштованій embedding-моделі: {detail}",
        "en": "Index does not match the configured embedding model: {detail}",
    },
    "pf_header": {
        "ua": "Середовище не готове:",
        "en": "The environment is not ready:",
    },
    # ---- preflight: non-fatal notices (it works, but in a degraded shape)
    "pf_no_local_model": {
        "ua": "LLM_BACKEND=ollama, але модель {model} не завантажена: `ollama pull {model}` або OLLAMA_LLM_MODEL=<інша>",
        "en": "LLM_BACKEND=ollama, but the model {model} is not pulled: `ollama pull {model}` or set OLLAMA_LLM_MODEL",
    },
    "pf_no_embed_model": {
        "ua": "EMBED_BACKEND=ollama, але embedding-модель {model} не завантажена: "
              "`ollama pull {model}` або OLLAMA_EMBED_MODEL=<інша>",
        "en": "EMBED_BACKEND=ollama, but the embedding model {model} is not pulled: "
              "`ollama pull {model}` or set OLLAMA_EMBED_MODEL",
    },
    "pf_no_cards": {
        "ua": "Таблиці карток {table} нема: відповіді спираються лише на повний текст "
              "(картки книжок потребують LLM і не створюються `ayl-add`).",
        "en": "Cards table {table} absent: answers come from transcripts only "
              "(book cards need an LLM and are not built by `ayl-add`).",
    },
    "pf_notice_header": {
        "ua": "До відома:",
        "en": "Note:",
    },
    "cli_run_error": {
        "ua": "Помилка прогону: {e}\n(повний traceback: ASK_DEBUG=1)",
        "en": "Run failed: {e}\n(full traceback: ASK_DEBUG=1)",
    },

    # ---- eval harness
    "eval_auto_clarify_reply": {
        "ua": "Не можу зараз уточнити — обери найімовірніший варіант сам "
              "і поясни, чому саме він.",
        "en": "I can't clarify right now — pick the most likely candidate yourself "
              "and explain why.",
    },

    # ---- cli: chat loop banner, prompts, and per-step status lines
    "cli_banner": {
        "ua": "Ask Your Library — чат. Питай про свої книжки; вийти: exit\n",
        "en": "Ask Your Library — chat. Ask about your books; type exit to quit\n",
    },
    "cli_question": {"ua": "Питання: {q}", "en": "Question: {q}"},
    "cli_you": {"ua": "\nТи: ", "en": "\nYou: "},
    "cli_your_answer": {"ua": "Твоя відповідь: ", "en": "Your answer: "},
    "cli_bye": {"ua": "\nБувай!", "en": "\nBye!"},
    "ev_plan_fallback": {"ua": "[plan] планер не дав придатного плану (JSON або запити): шукаю за текстом питання",
                         "en": "[plan] the planner gave no usable plan (JSON or queries): searching the raw question"},
    "ev_plan": {"ua": "[plan] mode={mode}, запити: {queries}",
                "en": "[plan] mode={mode}, queries: {queries}"},
    "ev_plan_catalog": {"ua": "[plan] mode=catalog, операція: {op}",
                        "en": "[plan] mode=catalog, operation: {op}"},
    "ev_catalog_fallback_invalid_op": {"ua": "[plan] планер назвав операцію каталогу, якої нема: шукаю в текстах",
                                       "en": "[plan] the planner named a catalogue operation that does not exist: searching the texts instead"},
    "ev_catalog_fallback_after_clarify": {"ua": "[plan] запит до каталогу після уточнення не виконується: продовжую пошук у вибраній книжці",
                                          "en": "[plan] a catalogue request after a clarify reply is not honoured: the search goes on in the chosen book"},
    "ev_book_filter": {"ua": "[plan] питання називає книжку {book}: пошук лише в ній",
                       "en": "[plan] the question names {book}: retrieval limited to it"},
    "ev_book_unresolved": {"ua": "[plan] книжки з назвою «{q}» в каталозі немає: шукаю по всій бібліотеці",
                           "en": "[plan] no book titled \"{q}\" in the catalogue: searching the whole library"},
    "ev_catalog": {"ua": "[catalog] {op}: {n} з {total} книжок, з таблиць індексу",
                   "en": "[catalog] {op}: {n} of {total} books, from the index tables"},
    "ev_act": {"ua": "[act #{n}] знайдено {hits} хітів",
               "en": "[act #{n}] found {hits} hits"},
    "ev_observe": {"ua": "[observe] доказів разом: {n}{streak}",
                   "en": "[observe] evidence so far: {n}{streak}"},
    "ev_streak": {"ua": " (сухих кроків поспіль: {n})",
                  "en": " (dry steps in a row: {n})"},
    "ev_reflect_clarify": {"ua": "[reflect] неоднозначно — питаю користувача",
                           "en": "[reflect] ambiguous — asking the user"},
    "ev_reflect_chapter": {"ua": "[reflect] дочитуємо розділ: {book} / {section}",
                           "en": "[reflect] reading chapter: {book} / {section}"},
    "ev_reflect_probe": {"ua": "[reflect] coverage gate: одна перевірка кандидата {book}, якого докази ще не торкались",
                         "en": "[reflect] coverage gate: one look inside {book}, a candidate the evidence never touched"},
    "ev_reflect_search": {"ua": "[reflect] ще шукаємо: {q}",
                          "en": "[reflect] searching more: {q}"},
    "ev_reflect_enough": {"ua": "[reflect] досить, синтезуємо",
                          "en": "[reflect] enough, synthesizing"},
    "ev_clarify": {"ua": "[clarify] уточнення користувача: {a}",
                   "en": "[clarify] user clarification: {a}"},
    "ev_answer_header": {"ua": "\n=== ВІДПОВІДЬ ===\n{a}", "en": "\n=== ANSWER ===\n{a}"},
    "ev_provenance": {"ua": "\n[походження цитат] {v}", "en": "\n[quote provenance] {v}"},
    "ev_evidence_header": {"ua": "[докази] {n} елемент(ів) evidence, кожен з уривком, проти якого його перевірено "
                                 "(цитата має лежати всередині одного чанка; [...] розділяє чанки):",
                           "en": "[evidence] {n} evidence item(s), each with the passage it was checked against "
                                 "(a quote must sit inside one chunk; [...] separates chunks):"},
    "ev_evidence_item": {"ua": "  - {status}: {book} — {section} [{hit_id}]: \"{quote}\"",
                         "en": "  - {status}: {book} — {section} [{hit_id}]: \"{quote}\""},
    "ev_passage_missing": {"ua": "    (уривок не в цьому прогоні: hit_id не знайдено)",
                           "en": "    (passage not in this run: hit_id not found)"},
    "ev_status_confirmed": {"ua": "підтверджено", "en": "confirmed"},
    "ev_status_unattributed": {"ua": "знайдено в іншому уривку", "en": "found in another passage"},
    "ev_status_broken": {"ua": "не знайдено дослівно", "en": "not found verbatim"},
    "m_line1": {
        "ua": "[метрики] {model}: {calls} LLM-викликів, {tin} in / {tout} out токенів, "
              "~${cost:.4f}, {sec}s, пошукових кроків: {steps}",
        "en": "[metrics] {model}: {calls} LLM calls, {tin} in / {tout} out tokens, "
              "~${cost:.4f}, {sec}s, search steps: {steps}",
    },
    "m_stop": {"ua": "  зупинка: {r}", "en": "  stop: {r}"},
    "m_stop_default": {"ua": "(разова відповідь без циклу)",
                       "en": "(single-pass answer, no loop)"},
    "m_roles": {"ua": "  по вузлах: {roles}", "en": "  per node: {roles}"},
    "m_retrieval": {
        "ua": "  retrieval: {hits} хітів -> {ev} доказів; injection-редакцій: {red}",
        "en": "  retrieval: {hits} hits -> {ev} evidence items; injection redactions: {red}",
    },
    "m_cache": {"ua": "  кеш: {n} токенів прочитано з кешу",
                "en": "  cache: {n} tokens read from cache"},
    "m_session": {"ua": "  сесія разом: {q} питань, ~${cost:.4f}",
                  "en": "  session total: {q} questions, ~${cost:.4f}"},

    # ---- web ui: chat header, agent-step trace, and metrics footer
    "ui_welcome": {
        "ua": "Ask Your Library — питай про свою бібліотеку. Кроки агента "
              "(plan / act / observe / reflect) розгортаються над відповіддю.",
        "en": "Ask Your Library — ask about your library. Agent steps "
              "(plan / act / observe / reflect) expand above the answer.",
    },
    "ui_mode": {"ua": "режим: {mode}", "en": "mode: {mode}"},
    "ui_plan_catalog": {"ua": "режим: catalog, операція: {op}", "en": "mode: catalog, operation: {op}"},
    "ui_catalog_fallback_invalid_op": {"ua": "планер назвав операцію каталогу, якої нема: шукаю в текстах",
                                       "en": "the planner named a catalogue operation that does not exist: searching the texts instead"},
    "ui_catalog_fallback_after_clarify": {"ua": "запит до каталогу після уточнення не виконується: продовжую пошук у вибраній книжці",
                                          "en": "a catalogue request after a clarify reply is not honoured: the search goes on in the chosen book"},
    "ui_book_filter": {"ua": "питання називає книжку {book}: пошук лише в ній",
                       "en": "the question names {book}: retrieval limited to it"},
    "ui_book_unresolved": {"ua": "книжки з назвою «{q}» в каталозі немає: шукаю по всій бібліотеці",
                           "en": "no book titled \"{q}\" in the catalogue: searching the whole library"},
    "ui_catalog_step": {"ua": "{op}: {n} з {total} книжок, з таблиць індексу",
                        "en": "{op}: {n} of {total} books, from the index tables"},
    "ui_badge_catalog_title": {"ua": "Відповідь з каталогу", "en": "Catalogue answer"},
    "ui_badge_catalog": {"ua": "вичерпно: {n} з {total} книжок перелічено кодом з таблиць індексу; цитат немає",
                         "en": "exhaustive: {n} of {total} books listed by code from the index tables; no quotes to trace"},
    "ui_plan_fallback": {"ua": "планер не дав придатного плану (JSON або запити): шукаю за текстом питання",
                         "en": "the planner gave no usable plan (JSON or queries): searching the raw question"},
    "ui_queries": {"ua": "пошукові запити:", "en": "search queries:"},
    "ui_hits": {"ua": "знайдено {n} хітів:", "en": "found {n} hits:"},
    "ui_evidence": {"ua": "доказів разом: {n}", "en": "evidence so far: {n}"},
    "ui_streak": {"ua": " (сухих кроків поспіль: {n})", "en": " (dry steps in a row: {n})"},
    "ui_clarify_step": {"ua": "неоднозначно — питаю користувача",
                        "en": "ambiguous — asking the user"},
    "ui_chapter": {"ua": "дочитуємо розділ: {book} / {section}",
                   "en": "reading chapter: {book} / {section}"},
    "ui_probe": {"ua": "coverage gate: одна перевірка кандидата {book}",
                 "en": "coverage gate: one look inside {book}"},
    "ui_search_more": {"ua": "ще шукаємо: {q}", "en": "searching more: {q}"},
    "ui_enough": {"ua": "досить, синтезуємо", "en": "enough, synthesizing"},
    "ui_stopped": {"ua": "зупинка: {r}", "en": "stopped: {r}"},
    "ev_reflect_stopped": {"ua": "[reflect] зупинка: {r}", "en": "[reflect] stopped: {r}"},
    "ui_user_clarified": {"ua": "уточнення користувача: {a}", "en": "user clarification: {a}"},
    "ui_badge_title": {"ua": "Походження цитат", "en": "Quote provenance"},
    "ui_evidence_title": {"ua": "Елементи evidence ({n}, уривків: {p}): розкрийте уривок, щоб побачити текст, проти якого "
                                "перевірено його цитати (цитата має лежати всередині одного чанка; [...] розділяє чанки)",
                          "en": "Evidence items ({n}, in {p} passage(s)): open a passage to see the text its quotes were "
                                "checked against (a quote must sit inside one chunk; [...] separates chunks)"},
    "ui_passage_missing": {"ua": "(уривок не в цьому прогоні)", "en": "(passage not in this run)"},
    "ui_badge_ok": {"ua": "походження {ok}/{all} фрагментів evidence підтверджено",
                    "en": "evidence passages {ok}/{all} traced to their source"},
    "ui_badge_unattributed": {"ua": "{ok}/{all} підтверджено, {n} знайдено в іншому уривку, ніж цитований",
                              "en": "{ok}/{all} confirmed, {n} traced to a different passage than cited"},
    "ui_badge_warn": {"ua": "{broken}/{all} цитат не дослівні",
                      "en": "{broken}/{all} quotes not verbatim"},
    "ui_badge_which": {"ua": "які саме", "en": "which ones"},
    "ui_badge_unused": {"ua": " (+{n} доказів для книг, яких відповідь не називає)",
                        "en": " (+{n} evidence items for books the answer does not name)"},
    "ui_m_summary": {
        "ua": "модель: {model} | вартість: ${cost:.4f} (сесія: ${scost:.4f}) | "
              "час: {sec} с | кроки: {steps} | stop: {stop}",
        "en": "model: {model} | cost: ${cost:.4f} (session: ${scost:.4f}) | "
              "time: {sec} s | steps: {steps} | stop: {stop}",
    },
    "m_partial": {"ua": "[metrics] поки що ${cost:.4f}, {calls} виклик(ів), {sec} с — прогін на паузі, чекаю відповіді",
                  "en": "[metrics] so far ${cost:.4f}, {calls} call(s), {sec} s — run paused for your reply"},
    "ui_m_partial": {
        "ua": "модель: {model} | вартість поки що: ${cost:.4f} (прогін на паузі: чекаю відповіді) | час: {sec} с | кроків: {steps}",
        "en": "model: {model} | cost so far: ${cost:.4f} (run paused for your reply) | time: {sec} s | steps: {steps}",
    },
    "ui_m_details": {"ua": "деталі прогону", "en": "run details"},
    "ui_m_th": {"ua": "<th>вузол</th><th>виклики</th><th>in</th><th>out</th><th>$</th>",
                "en": "<th>node</th><th>calls</th><th>in</th><th>out</th><th>$</th>"},
    "ui_m_tokens": {
        "ua": "llm-виклики: {calls}; токени: {tin} in / {tout} out / кеш {cache}",
        "en": "LLM calls: {calls}; tokens: {tin} in / {tout} out / cache {cache}",
    },
    "ui_m_retrieval": {
        "ua": "retrieval: хітів переглянуто {hits}, дистильовано в докази {ev}",
        "en": "retrieval: {hits} hits scanned, {ev} distilled into evidence",
    },
    "ui_m_injection": {"ua": "injection-фільтр: вирізано рядків {n}",
                       "en": "injection filter: {n} lines redacted"},
    "ui_error": {"ua": "Помилка прогону агента: {e}", "en": "Agent run failed: {e}"},
}


def status_word(status: str) -> str:
    """The reader's word for a provenance verdict (confirmed / unattributed /
    broken); an unknown value is shown as is, so a fourth status cannot pass
    unnoticed in one interface only."""
    return t(f"ev_status_{status}") if status in ("confirmed", "unattributed", "broken") else status


def t(key: str, **kw) -> str:
    """Look up `key` in the current session's language and format it with `kw`."""
    s = _T[key][_current.get()]
    return s.format(**kw) if kw else s
