from __future__ import annotations

import json
import logging
import os
import re

from typeface.article import Article
from typeface.config import Config
from typeface.decision import Decision, normalize
from typeface.errors import TypefaceError
from typeface.lexical import apply_decision, audit, plain_text, reconcile

_PARAGRAPH_TYPES = {"paragraph", "quote", "heading"}

log = logging.getLogger(__name__)


def decide(cfg: Config, article: Article, image: bytes | None, mime: str | None) -> Decision:
    if article.has_image and not image:
        raise TypefaceError("no se pudo leer la imagen para controlar la marca de agua")
    problems: list[str] = []
    last = Decision()
    for attempt in range(1, cfg.max_attempts + 1):
        log.info("%s: consultando al modelo", article.id)
        payload = _ask(cfg, article, problems, image, mime)
        if payload is None:
            problems = ["la respuesta no contenía un objeto JSON"]
            log.warning("%s: intento %d/%d rechazado: %s", article.id, attempt, cfg.max_attempts, problems[0])
            continue
        last = _decision_from_payload(payload, article.category_id)
        if last.watermark:
            return Decision(watermark=True, watermark_source=last.watermark_source, category_id=article.category_id)
        normalized = reconcile(article.body, normalize(last))
        try:
            updated = apply_decision(article.body, normalized)
            problems = audit(updated, normalized)
        except RuntimeError as exc:
            raise TypefaceError(str(exc)) from exc
        if article.has_image and not normalized.caption.strip():
            problems.append("falta el pie de foto")
        if not problems:
            return normalized
        log.warning(
            "%s: intento %d/%d rechazado: %s",
            article.id,
            attempt,
            cfg.max_attempts,
            "; ".join(problems),
        )
    detail = "; ".join(problems) if problems else "el modelo no devolvió una tipografía usable"
    raise TypefaceError(detail)


def build_prompt(article: Article, problems: list[str], *, has_image: bool) -> str:
    paragraphs = _paragraphs(article.body)
    lines = [
        "Sos el editor tipográfico de Base Tucumán. No reescribas: no cambies ni una palabra, ni el título, ni el sentido.",
        "No uses herramientas. Respondé solo con un objeto JSON.",
        "Marcá fragmentos copiados carácter por carácter del cuerpo.",
        "Negrita: nombres propios clave, instituciones, cargos, cifras y datos duros. No marques el resto corto que queda después de un bloque: ese resto no se publica. Si el dato solo está dentro de una cita en bloque, no lo marques.",
        "Itálica: citas textuales cortas y frases breves atribuidas, sin las comillas que las envuelven. Si la frase solo está dentro de una cita en bloque, no la marques.",
        "quotes: como máximo dos por nota, y solo si esa cita es el eje. Ordenalas de la más relevante a la menos: si mandás más de dos, se usan las dos primeras. Si hay varias citas de peso parecido, dejá quotes vacío. No llenes la nota de bloques. Una frase corta no va en quotes.",
        "No pases a bloque una cita si al sacarla queda un signo suelto (coma, punto, dos puntos, punto y coma, signos de exclamación o pregunta) o una, dos o tres palabras. Ese resto queda solo en una línea y no se publica.",
        "Copiá la cita sin las comillas que la envuelven: esas comillas se borran al pasar la cita a bloque.",
        "Categoría, un número: 1 Política (gobierno, partidos, elecciones, gestión), 2 Economía (precios, trabajo, producción, finanzas), 3 Deportes, 4 Sociedad (el resto, incluida la obra vial, salud, educación, seguridad, cultura), 5 Mundo (el eje está fuera de la Argentina).",
        "El pie de foto es una frase muy breve, en español rioplatense, de menos de 80 caracteres. No nombres al medio de origen.",
        'Forma: {"watermark": false, "watermark_source": "", "category_id": 4, "caption": "Pie.", "bold": [], "italic": [], "quotes": []}',
    ]
    if has_image:
        lines.append(
            "La imagen adjunta es la foto principal. Si tiene marca de agua o logo de La Gaceta, Contexto Tucumán, iProfesional u otro medio, watermark es true y watermark_source es el medio. En ese caso dejá bold, italic y quotes vacíos."
        )
    else:
        lines.append("No hay imagen: watermark false y caption vacío.")
    lines.append(
        "Nota:\n"
        + json.dumps(
            {
                "titulo": article.title,
                "copete": article.deck,
                "categoria_actual": article.category_id,
                "parrafos": paragraphs,
            },
            ensure_ascii=False,
        )
    )
    if problems:
        lines.append("El intento anterior se rechazó. Corregí solo esto:\n" + "\n".join(f"- {item}" for item in problems))
    return "\n\n".join(lines)


def _ask(cfg: Config, article: Article, problems: list[str], image: bytes | None, mime: str | None) -> dict | None:
    try:
        from cursor_sdk import Agent, AgentOptions, CursorAgentError, LocalAgentOptions, SDKImage, UserMessage
    except ImportError as exc:
        raise TypefaceError("Falta cursor-sdk. Instalá las dependencias con pip install -r requirements.txt") from exc

    api_key = os.environ.get("CURSOR_API_KEY")
    if not api_key:
        raise TypefaceError("Falta CURSOR_API_KEY.")
    cfg.work_dir.mkdir(parents=True, exist_ok=True)
    images = None
    if image:
        images = [SDKImage.from_data(image, mime or "image/jpeg")]
    message = UserMessage(text=build_prompt(article, problems, has_image=image is not None), images=images)
    options = AgentOptions(
        model=cfg.model,
        api_key=api_key,
        local=LocalAgentOptions(cwd=str(cfg.work_dir)),
    )
    try:
        result = Agent.prompt(message, options)
    except CursorAgentError as exc:
        raise TypefaceError(str(exc)) from exc
    status = getattr(result.status, "value", result.status)
    if str(status) != "finished":
        raise TypefaceError(f"la ejecución terminó en estado '{status}'")
    return _extract_json(result.result or "")


def _decision_from_payload(payload: dict, fallback_category: int) -> Decision:
    category = payload.get("category_id", fallback_category)
    try:
        category_id = int(category)
    except (TypeError, ValueError):
        category_id = 0
    return Decision(
        watermark=bool(payload.get("watermark")),
        watermark_source=str(payload.get("watermark_source") or "").strip(),
        category_id=category_id,
        caption=str(payload.get("caption") or ""),
        bold=_list(payload.get("bold")),
        italic=_list(payload.get("italic")),
        quotes=_list(payload.get("quotes")),
    )


def _list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _paragraphs(body: dict) -> list[str]:
    paragraphs: list[str] = []
    for child in body.get("root", {}).get("children", []):
        if child.get("type") not in _PARAGRAPH_TYPES:
            continue
        text = plain_text({"root": {"children": [child]}})
        if text:
            paragraphs.append(text)
    return paragraphs


def _extract_json(text: str) -> dict | None:
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    candidates = [fenced.group(1)] if fenced else []
    candidates.append(text)
    for candidate in candidates:
        start = candidate.find("{")
        while start != -1:
            end = _matching_brace(candidate, start)
            if end is not None:
                try:
                    parsed = json.loads(candidate[start : end + 1])
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, dict):
                    return parsed
            start = candidate.find("{", start + 1)
    return None


def _matching_brace(text: str, start: int) -> int | None:
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return None
