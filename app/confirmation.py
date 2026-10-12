"""Interpret a caller's spoken confirmation, as transcribed by speech-to-text.

Deliberately conservative: any negation wins over any affirmation ("yes, wait" -> declined),
and anything ambiguous is "unclear" so the agent must ask again.
"""
import re
from typing import Literal

Interpretation = Literal["affirmed", "declined", "unclear"]

AFFIRMATIVE_WORDS = {"yes", "yeah", "yep", "yup", "confirm", "confirmed", "correct", "proceed",
                     "affirmative", "sure", "ok", "okay"}
AFFIRMATIVE_PHRASES = ("go ahead", "do it", "please do")
NEGATIVE_WORDS = {"no", "nope", "not", "don't", "dont", "stop", "cancel", "wait", "hold", "never",
                  "negative", "nevermind"}
NUMBER_WORDS = {"zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
                "six": "6", "seven": "7", "eight": "8", "nine": "9"}


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower().replace("’", "'"))


def interpret(utterance: str) -> Interpretation:
    tokens = _tokens(utterance)
    if any(t in NEGATIVE_WORDS for t in tokens):
        return "declined"
    joined = " ".join(tokens)
    if any(t in AFFIRMATIVE_WORDS for t in tokens) or any(p in joined for p in AFFIRMATIVE_PHRASES):
        return "affirmed"
    return "unclear"


def spoken_digits(utterance: str) -> str:
    """'yes, one zero 4 two' -> '1042'."""
    out = []
    for t in _tokens(utterance):
        if t in NUMBER_WORDS:
            out.append(NUMBER_WORDS[t])
        else:
            out.extend(ch for ch in t if ch.isdigit())
    return "".join(out)


def code_matches(utterance: str, code: str) -> bool:
    return code in spoken_digits(utterance)
