"""Compact, committable summary of an agent-eval report.

The full report (answers, scratchpads) stays out of git; this extracts what a
reader needs to audit a published number: the run fingerprint, the totals and
every failure with its reason.

  uv run eval/summarize_report.py eval/results/answers-<ts>.md > docs/eval-results/<date>.md
"""
import re
import sys
from pathlib import Path


def main() -> None:
    report = Path(sys.argv[1]).read_text(encoding="utf-8")
    run = re.search(r"^run: (.*)$", report, re.M)
    totals = report[report.rindex("\n---\n") + 5:].strip()
    fails = re.findall(r"^## (\S+) \((.*?)\) — FAIL: (.*)$", report, re.M)
    errors = re.findall(r"^## (\S+) — ERROR\n(.*)$", report, re.M)
    drill_no = re.findall(r"^## (\S+) \(.*?\) — PASS: .*drilldown NO.*$", report, re.M)
    # A PASS whose expected facts are not all in the answer: behaviour held and the
    # answer may still be missing what the golden item says it must carry. It is not
    # a failure (the facts row is not part of the verdict) and it is not silence either.
    facts_no = re.findall(r"^## (\S+) \(.*?\) — PASS: .*facts (\d+/\d+) NO.*$", report, re.M)
    print("# Agent eval summary\n")
    print(f"- run: `{run.group(1) if run else 'unknown'}`")
    print(f"- report: `{Path(sys.argv[1]).name}` (full answers not committed)\n")
    print("## Totals\n")
    print("```\n" + totals + "\n```\n")
    print("## Failures\n")
    for qid, meta, why in fails:
        print(f"- `{qid}` ({meta}): {why}")
    for qid in drill_no:
        print(f"- `{qid}`: PASS on titles/behaviour but no chapter drill-down where the golden expects one")
    for qid, ratio in facts_no:
        print(f"- `{qid}`: PASS on behaviour but only {ratio} expected facts are present in the answer")
    for qid, why in errors:
        print(f"- `{qid}`: ERROR, not completed: {why.strip()[:160]}")
    if not fails and not drill_no and not facts_no and not errors:
        print("- none")
    print("\nAnswer correctness is not scored; the facts row is substring presence, not correctness "
          "(a fact can sit in a sentence that says the wrong thing about it). See the golden notes and "
          "docs/examples for known failures (c06).")


if __name__ == "__main__":
    main()
