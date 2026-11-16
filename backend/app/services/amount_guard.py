"""
Amounts the sources don't state (M8.4).

The fast path writes its answer in one model call with no evidence step, so nothing checked its figures: asked for
the Start-up Visa fee, whose row in IRCC's fee table came without the amount, llama3.2:3b wrote "$1,225" (in 1 of 5
runs with the plain context, 3 of 3 with the merged one). A wrong fee or fund figure is the costliest kind of wrong
answer here, and the check is exact, so code makes it, after the answer is written:

  every money amount in the answer ($1,225 / CAD 1225 / 1,225 dollars) must be a number in the context the model
  was given or in the question; a sentence with one that isn't is removed, and the answer says an amount was left
  out and where to check it.

Only money amounts: other numbers are often the model's own arithmetic ("28 points in total") or the asker's.
"""

import re
from typing import Tuple

_MONEY = re.compile(
    r"(?:(?:CAD|CA\$|C\$|\$)\s?(\d[\d,]*(?:\.\d+)?))|(?:(\d[\d,]*(?:\.\d+)?)\s?(?:CAD\b|Canadian dollars|dollars))",
    re.IGNORECASE)
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_EMPTY_LINE = re.compile(r"^[\s\-*•\d.)]*$")
_MARKER = re.compile(r"^\s*(?:(?:[-*•]|\d+[.)])\s+)?")

NOTE = ("I couldn't find {what} in the official sources I was given, so I left {it} out. "
        "Check the current figure on the IRCC website (canada.ca).")


def _value(number: str) -> float:
    try:
        return float(number.replace(",", "").rstrip("."))
    except ValueError:
        return float("nan")


def _values(text: str) -> set:
    return {_value(n) for n in _NUMBER.findall(text or "")}


def _ungrounded(text: str, known: set) -> bool:
    return any(_value(a or b) not in known for a, b in _MONEY.findall(text))


def check(answer: str, context: str, question: str = "") -> Tuple[str, int]:
    """The answer without the sentences holding an amount the context and question don't state, and how many were
    removed. Unchanged (and 0) when every amount is stated."""
    known = _values(context) | _values(question)
    if not _ungrounded(answer or "", known):
        return answer, 0
    removed = 0
    lines = []
    for line in answer.split("\n"):
        if not _ungrounded(line, known):
            lines.append(line)
            continue
        marker = _MARKER.match(line).group(0)  # "- " / "1. ": stays when the bullet's first sentence goes
        kept = []
        for sentence in _SENTENCE_END.split(line[len(marker):]):
            if _ungrounded(sentence, known):
                removed += 1
            else:
                kept.append(sentence)
        rest = " ".join(kept)
        if not _EMPTY_LINE.match(rest):
            lines.append(marker + rest)
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    note = NOTE.format(what="that amount" if removed == 1 else "those amounts", it="it" if removed == 1 else "them")
    return (f"{text}\n\n{note}" if text else note), removed
