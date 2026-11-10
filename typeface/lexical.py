from __future__ import annotations

import copy

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
    """Aplica negrita, itálica y cita en bloque sin cambiar ni un carácter."""
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
                children.append(_block("quote", [_text_node(part, 0)]))
            else:
                children.append(_block("paragraph", _inline_nodes(part, decision)))
    updated = copy.deepcopy(body)
    updated["root"]["children"] = children
    if plain_text(updated) != original:
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
        if not any(child.get("type") == "quote" and _node_text(child) == quote for child in body["root"]["children"]):
            problems.append(f"la cita no quedó en bloque: «{_short(quote)}»")
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
