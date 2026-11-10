from __future__ import annotations

import copy
import re

from typeface.decision import FORMAT_BOLD, FORMAT_ITALIC, Decision

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

    La única edición permitida es borrar las comillas que envolvían una cita
    que pasó a bloque.
    """
    original = plain_text(body)
    children: list[dict] = []
    for child in body["root"]["children"]:
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
    if not _same_except_wrappers(original, plain_text(updated)):
        raise RuntimeError("La tipografía cambió el texto. No se guarda.")
    return updated


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
_TRAILING_WRAPPER = re.compile(r"""["“«„‟‘']\s*$""")
_LEADING_WRAPPER = re.compile(r"""^\s*["”»’']""")


def _unwrap_quote_marks(children: list[dict], decision: Decision) -> list[dict]:
    """Saca las comillas pegadas a una cita en bloque, incluso si están en otro párrafo."""
    cleaned: list[dict] = []
    for index, child in enumerate(children):
        if child.get("type") == "quote":
            text = _strip_wrapped_quote(_node_text(child))
            cleaned.append(_block("quote", [_text_node(text, 0)]) if text != _node_text(child) else child)
            continue
        if child.get("type") != "paragraph":
            cleaned.append(child)
            continue
        text = _node_text(child)
        next_is_quote = index + 1 < len(children) and children[index + 1].get("type") == "quote"
        prev_is_quote = bool(cleaned) and cleaned[-1].get("type") == "quote"
        if next_is_quote:
            text = _strip_trailing_wrapper(text)
        if prev_is_quote:
            text = _strip_leading_wrapper(text)
        if text.strip() == "":
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
    match = _LEADING_WRAPPER.match(text)
    if not match:
        return text
    return text[match.end() :].lstrip()


def _strip_wrapped_quote(text: str) -> str:
    if len(text) < 2 or text[0] not in _QUOTE_CHARS or text[-1] not in _QUOTE_CHARS:
        return text
    inner = text[1:-1].strip()
    return inner or text


def _same_except_wrappers(before: str, after: str) -> bool:
    """El texto nuevo solo puede haber perdido comillas y el espacio que las separaba de la cita."""
    index = 0
    for position, char in enumerate(before):
        if index < len(after) and after[index] == char:
            index += 1
            continue
        if char in _QUOTE_CHARS or (char.isspace() and _space_touches_quote(before, position)):
            continue
        return False
    return index == len(after)


def _space_touches_quote(text: str, position: int) -> bool:
    previous = next((char for char in reversed(text[:position]) if not char.isspace()), "")
    following = next((char for char in text[position + 1 :] if not char.isspace()), "")
    return previous in _QUOTE_CHARS or following in _QUOTE_CHARS


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
