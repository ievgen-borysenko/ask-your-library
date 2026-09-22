# Ask Your Library

Ask about the books you own. The answer names the book and the chapter it came from, and plain
code — no second model — checks every quote against the passage it was copied from.

- The badge under each answer counts the quotes traced to a book's own **text**. A quote that
  matched only a **book card** (a per-book summary a model wrote) is counted apart and says so:
  a card is not the book.
- Open any passage under the badge to read what a quote was checked against, with the matched
  run highlighted inside it, and a line saying whether that passage is book text or a card.
- Half-remember a book? When the match is genuinely ambiguous the agent lists the candidates and
  asks; answer with a number or a title.
- The agent's steps appear above the answer — what it planned to look for, what it searched, and
  the real reason it stopped (enough evidence, step limit, two dry steps, chapter already
  attempted).
- The footer shows what the question cost: LLM calls, tokens, USD.
- If the library has no answer, the agent says so honestly.

Language switch: chat profile at the top (English / Українська).

Signing in: the login form's first field is labelled "Email address"; type the username there.
