"""
Language check (M1.3, decision D6): Pendu answers in English only, for now.

A small model is much weaker outside English and the evaluation set is English, so a question in another language
gets a fixed reply instead of a model call. Runs locally in well under a millisecond, three tests in order:
  1. script:   most letters are not Latin (Hindi, Punjabi, Chinese, Arabic, ...)   -> not English
  2. English:  at least two English function words ("how", "can", "I", "my", "the", ...), or at least half the
               words are known English words ("Study permit extension documents")             -> English,
               even with names and places in other languages ("José García", "Université de Montréal")
  3. detector: py3langid, trusted only for 4+ words and a confident non-English guess  -> not English
Acronyms (PGWP, IELTS, CRS, eTA) belong to no language and are not counted.
Anything else (short or unclear input: "eTA", "biometrics?") counts as English: the input guardrail and the pipeline
handle it as before. A false "not English" would refuse a real question, so every doubt resolves to English.
"""

import re
import threading
import unicodedata
from dataclasses import dataclass
from typing import Optional

# Function words that are common in English and not words in Spanish, French, Portuguese, German or Italian
# ("a", "in", "an", "was", "will", "do", "no", "me", "as" are left out for that reason). "I" counts only as a
# capital: lowercase "i" is an Italian article.
_ENGLISH_WORDS = frozenset("""
the is are am were be been being how what when where which who whom why can could should would does did have has
had need my your our their his its you we they it this that these those with for from about after before during if
than then there here and or not of to at by any some much many get got want into while without
""".split())
# Immigration words that are English and not words in those languages (so not "visa", "document", "permis")
_ENGLISH_DOMAIN = frozenset("""
study studies studying student students permit permits work working job jobs hours money funds fee fees cost
extension extend apply applying application spouse family children kids letter test score entry express college
university school proof bank statement deadline required requirements eligible eligibility processing time days
weeks months years country travel visitor tourist refused approved expired expires renew skilled worker workers
insurance medical exam police certificate
""".split())
_ACRONYM_RE = re.compile(r"^(?:[A-Z]{2,}s?|e[A-Z]{2,})$")
_WORD_RE = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?")
_MIN_ENGLISH_WORDS = 2
_MIN_DETECTOR_WORDS = 4  # shorter fragments ("Super visa insurance") are too ambiguous to refuse
_DETECTOR_CONFIDENCE = 0.7  # the English tests run first, so a weaker guess is safe here

_identifier = None
_identifier_lock = threading.Lock()


@dataclass(frozen=True)
class LanguageResult:
    english: bool
    language: Optional[str]  # ISO 639-1 guess ("hi", "fr", ...), None when unknown
    method: str              # empty | script | english_words | detector | unclear


def _detector():
    global _identifier
    if _identifier is None:
        with _identifier_lock:
            if _identifier is None:
                from py3langid.langid import MODEL_FILE, LanguageIdentifier
                _identifier = LanguageIdentifier.from_pickled_model(MODEL_FILE, norm_probs=True)
    return _identifier


def _guess(text: str):
    language, probability = _detector().classify(text)
    return language, float(probability)


def _is_latin(char: str) -> bool:
    return "LATIN" in unicodedata.name(char, "")


def check_language(text: str) -> LanguageResult:
    letters = [c for c in (text or "") if c.isalpha()]
    if not letters:
        return LanguageResult(True, None, "empty")

    if sum(not _is_latin(c) for c in letters) * 2 > len(letters):
        language, _ = _guess(text)
        return LanguageResult(False, None if language == "en" else language, "script")

    words = [w for w in _WORD_RE.findall(text) if w == "I" or not _ACRONYM_RE.match(w)]
    function_words = sum(1 for w in words if w == "I" or (w.lower() in _ENGLISH_WORDS and w != "i"))
    known = function_words + sum(1 for w in words if w.lower() in _ENGLISH_DOMAIN)
    if function_words >= _MIN_ENGLISH_WORDS or (words and known * 2 >= len(words)):
        return LanguageResult(True, "en", "english_words")

    if len(words) >= _MIN_DETECTOR_WORDS:
        language, probability = _guess(text)
        if language != "en" and probability >= _DETECTOR_CONFIDENCE:
            return LanguageResult(False, language, "detector")
    return LanguageResult(True, None, "unclear")
