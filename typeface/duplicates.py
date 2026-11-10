from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from typeface.config import Config

_WHITESPACE = re.compile(r"\s+")
_WORD = re.compile(r"[0-9a-z]+")
_STOP = {
    "del",
    "los",
    "las",
    "una",
    "uno",
    "por",
    "con",
    "sus",
    "para",
    "como",
    "mas",
    "esta",
    "este",
    "esto",
    "esa",
    "ese",
    "eso",
    "tras",
    "ante",
    "sobre",
    "entre",
    "desde",
    "hasta",
    "cuando",
    "donde",
    "que",
    "les",
    "fue",
    "son",
    "hay",
    "nos",
    "the",
}


@dataclass(frozen=True)
class Story:
    id: int
    title: str
    deck: str


def find_duplicate(title: str, deck: str, others: list[Story], cfg: Config, own_id: int | None = None) -> Story | None:
    for other in others:
        if own_id is not None and other.id == own_id:
            continue
        if is_duplicate(title, deck, other.title, other.deck, cfg):
            return other
    return None


def is_duplicate(title_a: str, deck_a: str, title_b: str, deck_b: str, cfg: Config) -> bool:
    left = _normalize(title_a)
    right = _normalize(title_b)
    if not left or not right:
        return False
    if left == right:
        return True
    if min(len(left), len(right)) >= 40 and (left in right or right in left):
        return True
    if SequenceMatcher(None, left, right).ratio() >= cfg.duplicate_ratio:
        return True
    tokens_a = _tokens(f"{title_a} {deck_a}")
    tokens_b = _tokens(f"{title_b} {deck_b}")
    shared = tokens_a & tokens_b
    strong = [token for token in shared if any(char.isdigit() for char in token) or len(token) >= 7]
    return len(shared) >= cfg.duplicate_shared_tokens and len(strong) >= cfg.duplicate_strong_tokens


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return _WHITESPACE.sub(" ", stripped).casefold().strip()


def _tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for word in _WORD.findall(_normalize(text)):
        if word in _STOP:
            continue
        if len(word) <= 2 and not any(char.isdigit() for char in word):
            continue
        tokens.add(word)
    return tokens
