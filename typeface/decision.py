from __future__ import annotations

import re
from dataclasses import dataclass, field

FORMAT_BOLD = 1
FORMAT_ITALIC = 2

_SENTENCE_END = re.compile(r"[.!?…]+")
MAX_BLOCK_QUOTES = 2


@dataclass
class Decision:
    watermark: bool = False
    watermark_source: str = ""
    category_id: int = 0
    caption: str = ""
    bold: list[str] = field(default_factory=list)
    italic: list[str] = field(default_factory=list)
    quotes: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, data: dict) -> Decision:
        return cls(
            watermark=bool(data.get("watermark")),
            watermark_source=str(data.get("watermark_source") or ""),
            category_id=_as_int(data.get("category_id")),
            caption=str(data.get("caption") or ""),
            bold=_strings(data.get("bold")),
            italic=_strings(data.get("italic")),
            quotes=_strings(data.get("quotes")),
        )


def _as_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def is_long_quote(text: str) -> bool:
    """Cita en bloque: dos oraciones, o varias cláusulas. La frase corta no entra."""
    stripped = text.strip()
    size = len(stripped)
    if size < 80:
        return False
    ends = len(_SENTENCE_END.findall(stripped))
    if ends >= 2:
        return True
    if size >= 140:
        return True
    return stripped.count(",") >= 2 and size >= 100


def normalize(decision: Decision) -> Decision:
    """Una frase corta pasa a itálica. En bloque quedan como máximo dos citas largas."""
    italic = _unique(item.strip() for item in decision.italic if len(item.strip()) >= 2)
    quotes: list[str] = []
    for raw in decision.quotes:
        quote = raw.strip()
        if len(quote) < 2:
            continue
        if is_long_quote(quote):
            if len(quotes) < MAX_BLOCK_QUOTES:
                quotes.append(quote)
            continue
        if quote not in italic:
            italic.append(quote)
    return Decision(
        watermark=decision.watermark,
        watermark_source=decision.watermark_source.strip(),
        category_id=decision.category_id,
        caption=" ".join(decision.caption.split()),
        bold=_unique(item.strip() for item in decision.bold if len(item.strip()) >= 2),
        italic=italic,
        quotes=_unique(quotes),
    )


def _unique(items) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        unique.append(item)
    return unique


def polish_caption(caption: str, max_chars: int) -> str:
    text = " ".join(caption.split())
    if text and text[-1] not in ".!?":
        text += "."
    if not text:
        raise ValueError("falta el pie de foto")
    if len(text) > max_chars:
        raise ValueError(f"el pie de foto tiene {len(text)} caracteres y el máximo es {max_chars}")
    return text
