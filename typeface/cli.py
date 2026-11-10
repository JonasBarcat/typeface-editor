from __future__ import annotations

import argparse
import json
import logging
import unittest
from pathlib import Path

from typeface.summary import render


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="typeface", description="Tipografía de borradores de Base Tucumán.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    once = sub.add_parser("once", help="Tipografía los borradores nuevos y deja todo en borrador.")
    once.add_argument("--dry-run", action="store_true", help="No escribe en el CMS ni avanza el último id.")
    once.add_argument("--fixture", type=Path, help="Nota local, sin CMS.")
    once.add_argument("--decisions", type=Path, help="Decisiones ya armadas, sin llamar al modelo.")
    once.add_argument("--since-id", type=int, help="Procesar borradores con id mayor a este.")
    once.add_argument("--config", type=Path, help="Ruta a config.yaml.")

    sub.add_parser("check", help="Corre las pruebas locales, sin CMS y sin modelo.")

    args = parser.parse_args(argv)
    if args.cmd == "check":
        return _check()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.INFO)
    logging.getLogger("typeface").propagate = True
    return _once(args)


def _check() -> int:
    import importlib.util

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("test_typeface", root / "tests" / "test_typeface.py")
    if spec is None or spec.loader is None:
        print("Falló: no están las pruebas.")
        return 1
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    suite = unittest.defaultTestLoader.loadTestsFromModule(module)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


def _once(args: argparse.Namespace) -> int:
    try:
        from dotenv import load_dotenv
    except ImportError:
        load_dotenv = None

    from typeface.article import load_article
    from typeface.config import load_config, read_last_id, write_last_id
    from typeface.decision import Decision
    from typeface.editor import decide as ask_model
    from typeface.errors import TypefaceError
    from typeface.pipeline import process

    log = logging.getLogger("typeface")

    if load_dotenv is not None:
        load_dotenv()
    cfg = load_config(args.config)
    try:
        if args.fixture:
            article = load_article(args.fixture)
            if args.decisions:
                fixed = Decision.from_mapping(json.loads(args.decisions.read_text(encoding="utf-8")))

                def decide(article, _fixed=fixed):
                    return _fixed
            else:

                def decide(article):
                    return ask_model(cfg, article, None, None)

            report = process([article], [], decide, _discard, cfg, advance=None)
        else:
            from typeface.cms import connect

            if args.since_id is not None:
                last_id = args.since_id
            else:
                last_id = read_last_id(cfg.state_path)
            if last_id is None:
                raise TypefaceError("No hay último id. Usá --since-id.")
            cms = connect(cfg)
            articles = cms.drafts_after(last_id)
            published = cms.recent_published(cfg.recent_published)
            if args.dry_run:
                log.info("dry-run: no se escribe ni se elimina en el CMS")

            def decide(article):
                image = None
                mime = None
                if article.image_url:
                    log.info("%s: bajando la imagen", article.id)
                    image, mime = cms.fetch_image(article.image_url)
                return ask_model(cfg, article, image, mime)

            def write(article, patch, caption):
                if args.dry_run:
                    return
                if caption and article.media_id and caption != (article.caption or ""):
                    cms.save_caption(article.media_id, caption)
                cms.save_draft(article.id, patch)

            def remove(article) -> bool:
                if args.dry_run:
                    return False
                cms.delete_article(article.id)
                if article.media_id:
                    try:
                        cms.delete_media(article.media_id)
                    except TypefaceError as exc:
                        log.warning("%s: la nota se eliminó pero la imagen no: %s", article.id, exc)
                return True

            def advance(article_id: int) -> None:
                if not args.dry_run:
                    write_last_id(cfg.state_path, article_id)

            report = process(articles, published, decide, write, cfg, advance, remove)
    except (TypefaceError, OSError, ValueError) as exc:
        print(f"Falló: {exc}")
        return 1
    print(render(report))
    return 0 if report.ok else 1


def _discard(_article, _patch, _caption) -> None:
    return None
