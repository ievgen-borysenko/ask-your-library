# Demo corpus: what is here, from where, under which statements

`manifest.yaml` is the single source of truth: every book with its source and its identifier (the
Project Gutenberg ebook number, or the archive.org item of a LibriVox recording), and for the
fetched and prepared inputs a SHA-256: for a Gutenberg book it pins the downloaded text, for a
LibriVox book it pins the committed transcript file under `prepared-audio/` (the audio itself is
not pinned and not committed), and the two canaries carry no checksum because their text is
committed as is. `scripts/ingest_demo_corpus.py` builds the library from it; the Gutenberg texts
are not committed, they are fetched at build time.

**Texts: 31 books from Project Gutenberg.** Project Gutenberg distributes them as public domain
**in the United States** and says so on its own terms: it does not guarantee the same status in
other countries, and for a translated work (this corpus has English translations of at least Cervantes,
Dumas, Verne, Leblanc, Homer, Marcus Aurelius, Seneca, Bourrienne and Shevchenko) the edition and the
translation are the ones Gutenberg publishes under that ebook number, which may have a status of
their own where you are. Check before reusing the texts outside the United States. The ingest
strips the Gutenberg header and footer; the Project Gutenberg trademark is not used for anything.
Statement: <https://www.gutenberg.org/policy/permission.html>.

**Audio: 2 books from LibriVox** (Alice's Adventures in Wonderland, The Time Machine), the
archive.org items named in the manifest. LibriVox releases its recordings into the public domain,
again stated from the United States: <https://librivox.org/pages/public-domain/>. What is
committed here is not the audio but `prepared-audio/*.json`: the **machine transcription** of those
recordings made for this project (Whisper, lower-cased, punctuation-free), which carries the
readers' announcements and recognition errors and is not an authoritative text of any edition.

**Book cards (`cards/*.md`, 33)** are short structured descriptions (summary, plot, characters,
takeaways) written for this project with a language model. They are derivative descriptions, not
text from the books; a test checks that every work a card quotes by title exists in that book's
table of contents. They form the `cards` corpus of the demo index.

**Tables of contents (`toc/*.json`, 35)** are chapter lists derived from the source texts and used
by the ingest to split chapters; one per book, plus one per canary.

**Canaries (`canaries/*.txt`, 2, with their TOC files)** are two synthetic novellas written for
this repository, with invented authors, to test prompt-injection handling and, in future, an
entitlement check. Any secret-looking strings inside them are test tokens, not credentials.

**Terms.** The project's own files in this directory (manifest, tables of contents, book cards,
transcripts, canaries) are under the repository's Apache-2.0 license to the extent the project
holds rights in them; the underlying works keep the public-domain status described above, which
the project cannot extend or restrict.
