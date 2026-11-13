from __future__ import annotations

import copy
import logging
import re

from typeface.decision import FORMAT_BOLD, FORMAT_ITALIC, Decision

log = logging.getLogger(__name__)

_BLOCK_TYPES = {"paragraph", "quote"}


def paragraphs_to_body(paragraphs: list[str]) -> dict:
    return {
        "root": {
            "type": "root",
            "format": "",
            "indent": 0,
            "version": 1,
            "direction": "ltr",
            "children": [_block("paragraph", [_text_node(text, 0)]) for text in paragraphs],
        }
    }


def plain_text(body: dict) -> str:
    return "".join(_node_text(child) for child in body["root"]["children"])


def apply_decision(body: dict, decision: Decision) -> dict:
    """Aplica negrita, itálica y cita en bloque.

    Además de las comillas de una cita que pasó a bloque, se puede omitir el
    signo de puntuación que queda suelto y, si después del bloque solo hay
    una, dos o tres palabras, ese resto.
    """
    original_children = body["root"]["children"]
    children: list[dict] = []
    for child in original_children:
        if child.get("type") not in _BLOCK_TYPES:
            children.append(copy.deepcopy(child))
            continue
        text = _node_text(child)
        if text == "":
            children.append(copy.deepcopy(child))
            continue
        for kind, part in _split_quotes(text, decision.quotes):
            if kind == "quote":
                children.append(_block("quote", [_text_node(_strip_wrapped_quote(part), 0)]))
            else:
                children.append(_block("paragraph", _inline_nodes(part, decision)))
    updated = copy.deepcopy(body)
    updated["root"]["children"] = _unwrap_quote_marks(children, decision)
    before = _joined(original_children)
    after = _joined(updated["root"]["children"])
    if not _same_except_wrappers(before, after, decision.quotes):
        raise RuntimeError("La tipografía cambió el texto. No se guarda.")
    return updated


def reconcile(body: dict, decision: Decision) -> Decision:
    """Deja una decisión que se puede aplicar sin rechazar la nota.

    Una cita que no está en el texto, o que ya entra en otra cita, se omite.
    La negrita y la itálica que solo viven dentro de un bloque también se omiten:
    pedirle al modelo que las saque suele hacer que la cita deje de coincidir.
    """
    quotes = _placeable_quotes(body, decision.quotes)
    return Decision(
        watermark=decision.watermark,
        watermark_source=decision.watermark_source,
        category_id=decision.category_id,
        caption=decision.caption,
        bold=_marks_outside_quotes(body, decision.bold, quotes, "negrita"),
        italic=_marks_outside_quotes(body, decision.italic, quotes, "itálica"),
        quotes=quotes,
    )


def audit(body: dict, decision: Decision) -> list[str]:
    """Comprueba que cada fragmento pedido haya quedado con su formato."""
    problems: list[str] = []
    full = plain_text(body)
    for needle in decision.bold:
        problems.extend(_mark_problems(body, full, needle, FORMAT_BOLD, "negrita"))
    for needle in decision.italic:
        problems.extend(_mark_problems(body, full, needle, FORMAT_ITALIC, "itálica"))
    for quote in decision.quotes:
        visible = _strip_wrapped_quote(quote)
        found = any(
            child.get("type") == "quote" and _node_text(child) in {quote, visible}
            for child in body["root"]["children"]
        )
        if not found:
            problems.append(f"la cita no quedó en bloque: «{_short(visible)}»")
    return problems


def _placeable_quotes(body: dict, quotes: list[str]) -> list[str]:
    blocks = _editable_texts(body)
    found: list[str] = []
    for quote in quotes:
        visible = _strip_wrapped_quote(quote)
        if any(quote in block for block in blocks):
            chosen = quote
        elif visible != quote and any(visible in block for block in blocks):
            chosen = visible
        else:
            log.warning("cita omitida, no está en el texto: «%s»", _short(visible))
            continue
        if chosen not in found:
            found.append(chosen)
    kept: list[str] = []
    for quote in found:
        longer = [other for other in found if len(other) > len(quote)]
        if longer and not _occurs_outside_blocks(blocks, quote, longer):
            log.info("cita omitida, ya está dentro de otra: «%s»", _short(quote))
            continue
        kept.append(quote)
    return kept


def _occurs_outside_blocks(blocks: list[str], needle: str, quotes: list[str]) -> bool:
    return any(_occurs_outside(block, needle, _quote_spans(block, quotes)) for block in blocks)


def _marks_outside_quotes(body: dict, needles: list[str], quotes: list[str], label: str) -> list[str]:
    full = plain_text(body)
    spans = _quote_spans(full, quotes)
    kept: list[str] = []
    for needle in needles:
        if needle in full and not _occurs_outside(full, needle, spans):
            log.info("«%s» solo está dentro de una cita en bloque; no va en %s", _short(needle), label)
            continue
        kept.append(needle)
    return kept


def _editable_texts(body: dict) -> list[str]:
    texts = []
    for child in body.get("root", {}).get("children", []):
        if child.get("type") not in _BLOCK_TYPES:
            continue
        text = _node_text(child)
        if text:
            texts.append(text)
    return texts


def _quote_spans(text: str, quotes: list[str]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for quote in quotes:
        variants = [quote]
        visible = _strip_wrapped_quote(quote)
        if visible != quote:
            variants.append(visible)
        for variant in variants:
            start = 0
            while variant:
                index = text.find(variant, start)
                if index < 0:
                    break
                spans.append((index, index + len(variant)))
                start = index + len(variant)
    return spans


def _occurs_outside(text: str, needle: str, spans: list[tuple[int, int]]) -> bool:
    start = 0
    while True:
        index = text.find(needle, start)
        if index < 0:
            return False
        end = index + len(needle)
        if not any(span_start <= index and end <= span_end for span_start, span_end in spans):
            return True
        start = end


def _mark_problems(body: dict, full: str, needle: str, bit: int, label: str) -> list[str]:
    if needle not in full:
        return [f"«{needle}» no está en el texto"]
    occurrences, unmarked = _coverage(body, needle, bit)
    if occurrences == 0:
        return [f"«{needle}» solo aparece dentro de una cita en bloque; sacalo de {label}"]
    if unmarked:
        return [f"«{needle}» no quedó en {label}"]
    return []


def _coverage(body: dict, needle: str, bit: int) -> tuple[int, int]:
    occurrences = 0
    unmarked = 0
    for child in body["root"]["children"]:
        if child.get("type") == "quote":
            continue
        chars: list[tuple[str, int]] = []
        for node in _text_nodes(child):
            fmt = int(node.get("format") or 0)
            chars.extend((char, fmt) for char in node.get("text") or "")
        text = "".join(char for char, _fmt in chars)
        start = 0
        while True:
            index = text.find(needle, start)
            if index < 0:
                break
            occurrences += 1
            window = chars[index : index + len(needle)]
            if not all(fmt & bit == bit for _char, fmt in window):
                unmarked += 1
            start = index + len(needle)
    return occurrences, unmarked


_QUOTE_CHARS = set('"“”«»„‟‘’\'')
_DEBRIS_PUNCT = set(",.;:…?!")
_TRAILING_WRAPPER = re.compile(r"""["“«„‟‘']\s*$""")
_LEADING_WRAPPER = re.compile(r"""^\s*["”»’']""")
_LEADING_DEBRIS = re.compile(r"^(?:[\s,.;:…?!]*[,.;:…?!][\s,.;:…?!]*)")
_SENTINEL = "\u0001"
_SHORT_TAIL = 3


def _unwrap_quote_marks(children: list[dict], decision: Decision) -> list[dict]:
    """Saca comillas, signos sueltos y un resto de hasta tres palabras después de un bloque."""
    cleaned: list[dict] = []
    tail_open = False
    for index, child in enumerate(children):
        if child.get("type") == "quote":
            text = _strip_wrapped_quote(_node_text(child))
            cleaned.append(_block("quote", [_text_node(text, 0)]) if text != _node_text(child) else child)
            tail_open = True
            continue
        if child.get("type") != "paragraph":
            cleaned.append(child)
            tail_open = False
            continue
        text = _node_text(child)
        next_is_quote = index + 1 < len(children) and children[index + 1].get("type") == "quote"
        if next_is_quote:
            text = _strip_trailing_wrapper(text)
        if tail_open:
            text = _strip_leading_wrapper(text)
            text = _strip_leading_debris(text)
            if _word_count(text) <= _SHORT_TAIL:
                if _word_count(text) > 0:
                    tail_open = False
                continue
            tail_open = False
        elif text.strip() == "":
            continue
        if text == _node_text(child):
            cleaned.append(child)
        else:
            cleaned.append(_block("paragraph", _inline_nodes(text, decision)))
    return cleaned


def _strip_trailing_wrapper(text: str) -> str:
    match = _TRAILING_WRAPPER.search(text)
    if not match:
        return text
    return text[: match.start()].rstrip()


def _strip_leading_wrapper(text: str) -> str:
    """Saca la comilla de cierre que quedó pegada. No toca una cita que empieza de nuevo."""
    match = _LEADING_WRAPPER.match(text)
    if not match:
        return text
    rest = text[match.end() :].lstrip()
    if rest == "":
        return ""
    first = rest[0]
    if first.isupper() or first.isdigit() or first in "¿¡«":
        return text
    return rest


def _strip_leading_debris(text: str) -> str:
    """Saca la coma, el punto u otro signo que quedó al frente del párrafo siguiente."""
    return _LEADING_DEBRIS.sub("", text, count=1)


def _word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def _strip_wrapped_quote(text: str) -> str:
    if len(text) < 2 or text[0] not in _QUOTE_CHARS or text[-1] not in _QUOTE_CHARS:
        return text
    inner = text[1:-1].strip()
    return inner or text


def _joined(children: list[dict]) -> str:
    return _SENTINEL.join(_node_text(child) for child in children)


def _same_except_wrappers(before: str, after: str, quotes: list[str]) -> bool:
    """El texto nuevo solo puede haber perdido comillas, un signo suelto o un resto de hasta tres palabras."""
    return _align(before, after, 0, 0, quotes)


def _align(before: str, after: str, i: int, j: int, quotes: list[str]) -> bool:
    while i < len(before) or j < len(after):
        if i < len(before) and before[i] == _SENTINEL:
            i += 1
            continue
        if j < len(after) and after[j] == _SENTINEL:
            j += 1
            continue
        if i < len(before) and j < len(after) and before[i] == after[j]:
            i += 1
            j += 1
            continue
        if i < len(before) and before[i] in _QUOTE_CHARS:
            i += 1
            continue
        if i < len(before) and before[i].isspace() and _space_touches_quote(before, i):
            i += 1
            continue
        span = _tail_span(before, after, i, j, quotes)
        if span:
            i += span
            continue
        return False
    return True


def _tail_span(before: str, after: str, i: int, j: int, quotes: list[str]) -> int:
    if i >= len(before) or not _at_quote_edge(before, i, quotes):
        return 0
    end = i
    while end < len(before) and (before[end].isspace() or before[end] in _DEBRIS_PUNCT):
        end += 1
    candidates = [end] if end > i else []
    words = 0
    while words < _SHORT_TAIL and end < len(before):
        if before[end].isspace() or before[end] == _SENTINEL or before[end] in _DEBRIS_PUNCT:
            break
        while end < len(before) and not before[end].isspace() and before[end] != _SENTINEL:
            end += 1
        words += 1
        while end < len(before) and before[end].isspace():
            end += 1
        candidates.append(end)
    for candidate in candidates:
        if _align(before, after, candidate, j, quotes):
            return candidate - i
    return 0


def _at_quote_edge(text: str, position: int, quotes: list[str]) -> bool:
    if _follows_quote_boundary(text, position):
        return True
    for quote in quotes:
        if len(quote) < 2:
            continue
        start = 0
        while True:
            found = text.find(quote, start)
            if found < 0:
                break
            if _only_debris_between(text, found + len(quote), position):
                return True
            start = found + 1
    return False


def _follows_quote_boundary(text: str, position: int) -> bool:
    index = position - 1
    while index >= 0:
        char = text[index]
        if char in _QUOTE_CHARS:
            return True
        if char == _SENTINEL or char.isspace() or char in _DEBRIS_PUNCT:
            index -= 1
            continue
        return False
    return False


def _only_debris_between(text: str, start: int, end: int) -> bool:
    if end < start:
        return False
    for index in range(start, end):
        char = text[index]
        if char in _QUOTE_CHARS or char == _SENTINEL or char.isspace() or char in _DEBRIS_PUNCT:
            continue
        return False
    return True


def _space_touches_quote(text: str, position: int) -> bool:
    previous = _significant(text, position, -1)
    following = _significant(text, position, 1)
    return previous in _QUOTE_CHARS or following in _QUOTE_CHARS


def _significant(text: str, position: int, step: int) -> str:
    index = position + step
    while 0 <= index < len(text) and (text[index].isspace() or text[index] == _SENTINEL):
        index += step
    if 0 <= index < len(text):
        return text[index]
    return ""


def _split_quotes(text: str, quotes: list[str]) -> list[tuple[str, str]]:
    ordered = sorted(set(quotes), key=len, reverse=True)
    parts: list[tuple[str, str]] = []
    index = 0
    while index < len(text):
        match = next((quote for quote in ordered if text.startswith(quote, index)), None)
        if match:
            parts.append(("quote", match))
            index += len(match)
            continue
        next_at = None
        for quote in ordered:
            found = text.find(quote, index)
            if found != -1 and (next_at is None or found < next_at):
                next_at = found
        if next_at is None:
            parts.append(("text", text[index:]))
            break
        if next_at > index:
            parts.append(("text", text[index:next_at]))
        index = next_at
    return [(kind, part) for kind, part in parts if part]


def _inline_nodes(text: str, decision: Decision) -> list[dict]:
    ranges = _ranges(text, decision.bold, FORMAT_BOLD) + _ranges(text, decision.italic, FORMAT_ITALIC)
    if not ranges:
        return [_text_node(text, 0)]
    cuts = {0, len(text)}
    for start, end, _bit in ranges:
        cuts.add(start)
        cuts.add(end)
    points = sorted(cuts)
    nodes: list[dict] = []
    for start, end in zip(points, points[1:]):
        if start == end:
            continue
        bits = 0
        for range_start, range_end, bit in ranges:
            if range_start <= start and end <= range_end:
                bits |= bit
        nodes.append(_text_node(text[start:end], bits))
    return nodes or [_text_node(text, 0)]


def _ranges(text: str, needles: list[str], bit: int) -> list[tuple[int, int, int]]:
    found: list[tuple[int, int, int]] = []
    for needle in needles:
        start = 0
        while True:
            index = text.find(needle, start)
            if index < 0:
                break
            found.append((index, index + len(needle), bit))
            start = index + len(needle)
    return found


def _block(kind: str, children: list[dict]) -> dict:
    node = {
        "type": kind,
        "format": "",
        "indent": 0,
        "version": 1,
        "direction": "ltr",
        "children": children,
    }
    if kind == "paragraph":
        node["textStyle"] = ""
        node["textFormat"] = 0
    return node


def _text_node(text: str, fmt: int) -> dict:
    return {
        "mode": "normal",
        "text": text,
        "type": "text",
        "style": "",
        "detail": 0,
        "format": fmt,
        "version": 1,
    }


def _node_text(node: dict) -> str:
    if node.get("type") == "text":
        return str(node.get("text") or "")
    if node.get("type") == "linebreak":
        return "\n"
    return "".join(_node_text(child) for child in node.get("children") or [])


def _text_nodes(node: dict) -> list[dict]:
    if node.get("type") == "text":
        return [node]
    found: list[dict] = []
    for child in node.get("children") or []:
        found.extend(_text_nodes(child))
    return found


def _short(text: str) -> str:
    return text if len(text) <= 48 else text[:48] + "…"
