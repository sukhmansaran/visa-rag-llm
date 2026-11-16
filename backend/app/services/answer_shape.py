"""
Code checks on the shape of a fast-path answer (M8.5).

The 3B answer model sometimes copies the context's framing instead of answering: a whole reply of "[Source 1]"
("Which IELTS test version is accepted for Express Entry?", 3/3 in the 2026-11-16 full evaluation), or a header line
"[Source 1] (Tier 1 - Work off campus as an international student - Canada.ca)" before the answer.

- strip_echoed_framing() removes lines that are the context's own framing (prepare_context in retrieval.py:
  "[Source N] (Tier T - title)" and "URL: ... (Retrieved: ...)"). They state nothing; inline [Source N] citations
  stay.
- is_hollow() says when what is left is no answer: fewer than MIN_WORDS words once citations are taken out. The
  pipeline then asks the model once more (RETRY_NUDGE); a second hollow reply becomes HOLLOW_FALLBACK, so the user
  is never shown a bare citation as if it were an answer.
"""

import re

_FRAMING_LINE = re.compile(
    r"^[ \t*>-]*(?:\[Source \d+\]\s*\(Tier [^\n]*\)|URL:\s*\S+\s*\(Retrieved:[^\n]*\))[ \t*]*$",
    re.MULTILINE,
)
_CITATION = re.compile(r"\[(?:Source|Sources)\s*[\d, ]+\]")
MIN_WORDS = 4

RETRY_NUDGE = (
    "\n\nYour previous reply had no answer text, only a citation. Answer the question in one to three full "
    "sentences from the sources, citing them, or say the official sources you have don't cover it."
)
HOLLOW_FALLBACK = (
    "I couldn't write an answer to this from the official sources I was given. Check the IRCC website "
    "(canada.ca) or ask a licensed immigration consultant (RCIC)."
)


def strip_echoed_framing(answer: str) -> str:
    if not answer:
        return answer
    cleaned = _FRAMING_LINE.sub("", answer)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def is_hollow(answer: str) -> bool:
    # a word: a whitespace-separated token with a letter of any script in it (numbers alone are not an answer)
    words = [t for t in _CITATION.sub(" ", answer or "").split() if any(ch.isalpha() for ch in t)]
    return len(words) < MIN_WORDS
