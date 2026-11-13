from __future__ import annotations

import logging
from typing import Callable, Optional

from typeface.article import Article
from typeface.categories import category_name as _category_name
from typeface.config import Config
from typeface.decision import Decision, normalize, polish_caption
from typeface.duplicates import Story, find_duplicate
from typeface.errors import TypefaceError
from typeface.lexical import apply_decision, audit, reconcile
from typeface.payload import article_patch
from typeface.summary import Report

Decide = Callable[[Article], Decision]
Write = Callable[[Article, dict, Optional[str]], None]
Advance = Callable[[int], None]
Remove = Callable[[Article], bool]

log = logging.getLogger(__name__)


def process(
    articles: list[Article],
    published: list[Story],
    decide: Decide,
    write: Write,
    cfg: Config,
    advance: Advance | None = None,
    remove: Remove | None = None,
) -> Report:
    report = Report()
    seen = list(published)
    ordered = sorted(articles, key=lambda article: article.id)
    log.info("%s borrador(es)", len(ordered))
    for article in ordered:
        log.info("evaluando %s", article.id)
        if article.status != "draft":
            report.failure_id = article.id
            report.failure = "no está en borrador"
            log.error("%s: no está en borrador", article.id)
            break
        other = find_duplicate(article.title, article.deck, seen, cfg, article.id)
        seen.append(Story(article.id, article.title, article.deck))
        if other is not None:
            report.duplicates.append((article.id, other.id))
            log.info("%s: tema repetido (igual a %s)", article.id, other.id)
            _advance(advance, article.id)
            continue
        try:
            decision = decide(article)
        except TypefaceError as exc:
            report.failure_id = article.id
            report.failure = str(exc)
            log.error("%s: %s", article.id, exc)
            break
        if decision.watermark:
            source = f" ({decision.watermark_source})" if decision.watermark_source else ""
            try:
                if remove is None:
                    raise TypefaceError("no se puede eliminar la nota")
                deleted = remove(article)
            except (TypefaceError, OSError) as exc:
                report.failure_id = article.id
                report.failure = str(exc)
                log.error("%s: %s", article.id, exc)
                break
            report.watermarks.append((article.id, decision.watermark_source))
            if deleted:
                log.info("%s: eliminada por marca de agua%s", article.id, source)
            else:
                log.info("%s: marca de agua%s, no se elimina en dry-run", article.id, source)
            _advance(advance, article.id)
            continue
        try:
            patch, caption = prepare(article, decision, cfg)
            write(article, patch, caption)
        except (TypefaceError, ValueError, OSError) as exc:
            report.failure_id = article.id
            report.failure = str(exc)
            log.error("%s: %s", article.id, exc)
            break
        report.typeset.append(article.id)
        if decision.category_id != article.category_id:
            before = _label(article.category_id)
            after = _label(decision.category_id)
            report.categories.append((article.id, before, after))
            log.info("%s: tipografiada, categoría %s → %s", article.id, before, after)
        else:
            log.info("%s: tipografiada", article.id)
        _advance(advance, article.id)
    return report


def prepare(article: Article, decision: Decision, cfg: Config) -> tuple[dict, str | None]:
    if decision.watermark:
        raise TypefaceError("la nota tiene marca de agua y no se edita")
    normalized = reconcile(article.body, normalize(decision))
    try:
        _category_name(normalized.category_id)
    except ValueError as exc:
        raise TypefaceError(str(exc)) from exc
    updated = apply_decision(article.body, normalized)
    problems = audit(updated, normalized)
    if problems:
        raise TypefaceError("; ".join(problems))
    caption = None
    if article.has_image:
        try:
            caption = polish_caption(normalized.caption, cfg.caption_max)
        except ValueError as exc:
            raise TypefaceError(str(exc)) from exc
    patch = article_patch(updated, normalized.category_id)
    return patch, caption


def _label(category_id: int) -> str:
    try:
        return _category_name(category_id)
    except ValueError:
        return str(category_id)


def _advance(advance: Advance | None, article_id: int) -> None:
    if advance is not None:
        advance(article_id)
