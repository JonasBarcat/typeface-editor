import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from io import StringIO
from pathlib import Path

from typeface.article import from_mapping, load_article
from typeface.cli import main
from typeface.cms import Cms
from typeface.config import Config, read_last_id, write_last_id
from typeface.decision import Decision, is_long_quote, normalize, polish_caption
from typeface.duplicates import Story, is_duplicate
from typeface.editor import build_prompt
from typeface.errors import TypefaceError
from typeface.lexical import apply_decision, audit, paragraphs_to_body, plain_text
from typeface.payload import article_patch
from typeface.pipeline import prepare, process
from typeface.summary import Report, render

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "article-938.json"
DECISIONS = ROOT / "fixtures" / "article-938-decisions.json"


class Response:
    def __init__(self, status, payload):
        self.status_code = status
        self.ok = 200 <= status < 300
        self.text = json.dumps(payload)
        self._payload = payload

    def json(self):
        return self._payload


class Session:
    def __init__(self, payload=None):
        self.payload = payload or {"doc": {"_status": "draft"}}
        self.calls = []

    def patch(self, url, params=None, json=None, timeout=None):
        self.calls.append({"url": url, "params": params, "json": json})
        return Response(200, self.payload)

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params})
        return Response(200, {"docs": [], "hasNextPage": False})


class TypefaceTests(unittest.TestCase):
    def setUp(self):
        self.article = load_article(FIXTURE)
        self.decision = normalize(Decision.from_mapping(json.loads(DECISIONS.read_text(encoding="utf-8"))))
        self.cfg = Config()

    def test_fixture_keeps_every_character_and_marks_the_example(self):
        updated = apply_decision(self.article.body, self.decision)
        self.assertEqual(plain_text(updated), plain_text(self.article.body))
        self.assertEqual(audit(updated, self.decision), [])
        quotes = [child for child in updated["root"]["children"] if child["type"] == "quote"]
        self.assertEqual(len(quotes), 5)
        for quote in quotes:
            self.assertTrue(all(node["format"] == 0 for node in quote["children"]))
        again = apply_decision(updated, self.decision)
        self.assertEqual(plain_text(again), plain_text(updated))
        self.assertEqual(audit(again, self.decision), [])

    def test_short_phrase_never_becomes_a_block_quote(self):
        self.assertFalse(is_long_quote("animaloide"))
        self.assertFalse(
            is_long_quote("por el don de su vida y por los años de fecundo ministerio episcopal entre nosotros")
        )
        for quote in self.decision.quotes:
            self.assertTrue(is_long_quote(quote), quote)
        body = paragraphs_to_body(['Dijo "animaloide" y siguió.'])
        decision = normalize(Decision(quotes=["animaloide"], category_id=4, caption="Nota."))
        updated = apply_decision(body, decision)
        self.assertTrue(all(child["type"] != "quote" for child in updated["root"]["children"]))
        self.assertEqual(audit(updated, decision), [])

    def test_long_quote_splits_a_paragraph(self):
        quote = "Esta es una cita larga de prueba. Tiene dos oraciones y supera el umbral de una frase breve."
        self.assertTrue(is_long_quote(quote))
        body = paragraphs_to_body([f"Antes dijo esto. {quote} Después cerró."])
        decision = normalize(Decision(quotes=[quote], category_id=4, caption="Nota."))
        updated = apply_decision(body, decision)
        kinds = [child["type"] for child in updated["root"]["children"]]
        self.assertEqual(kinds, ["paragraph", "quote", "paragraph"])
        self.assertEqual(plain_text(updated), plain_text(body))

    def test_missing_span_is_rejected(self):
        decision = normalize(Decision(bold=["este fragmento no existe"], category_id=4, caption="Nota."))
        updated = apply_decision(self.article.body, decision)
        self.assertTrue(audit(updated, decision))

    def test_payload_stays_a_draft(self):
        patch, caption = prepare(self.article, self.decision, self.cfg)
        self.assertEqual(set(patch), {"body", "category", "_status"})
        self.assertEqual(patch["_status"], "draft")
        self.assertEqual(patch["category"], 4)
        self.assertEqual(caption, "Héctor Aguer.")
        self.assertEqual(plain_text(patch["body"]), plain_text(self.article.body))
        with self.assertRaises(ValueError):
            article_patch(self.article.body, 9)

    def test_caption_gets_a_period_and_rejects_a_long_one(self):
        self.assertEqual(polish_caption("Héctor Aguer", 80), "Héctor Aguer.")
        with self.assertRaises(ValueError):
            polish_caption("x" * 80, 80)

    def test_watermark_is_deleted_and_not_edited(self):
        writes = []
        removed = []

        def decide(_article):
            return Decision(watermark=True, watermark_source="La Gaceta", category_id=4)

        report = process(
            [self.article],
            [],
            decide,
            lambda *args: writes.append(args),
            self.cfg,
            remove=lambda article: removed.append(article.id) or True,
        )
        self.assertEqual(writes, [])
        self.assertEqual(removed, [938])
        self.assertEqual(render(report), "Eliminadas por marca de agua: 938 (La Gaceta)")

    def test_category_correction_stays_in_the_summary(self):
        article = replace(self.article, category_id=1)
        decision = replace(self.decision, category_id=4)
        report = process([article], [], lambda _article: decision, lambda *_args: None, self.cfg)
        self.assertIn("Tipografiados: 938", render(report))
        self.assertIn("938 Política → Sociedad", render(report))

    def test_repeated_story_is_left_alone(self):
        first = self.article
        second = replace(
            self.article,
            id=939,
            title="Murió Héctor Aguer a los 83 años, el exarzobispo emérito de La Plata",
            deck="La Arquidiócesis platense confirmó la muerte de monseñor Aguer y pidió una oración.",
        )
        self.assertTrue(is_duplicate(first.title, first.deck, second.title, second.deck, self.cfg))
        self.assertFalse(
            is_duplicate(
                "La selección venció en el clásico tucumano",
                "Golpe de Atlético en el norte.",
                "El precio del pan subió en la provincia",
                "Panaderías remarcaron esta semana.",
                self.cfg,
            )
        )
        writes = []
        report = process([first, second], [], lambda _article: self.decision, lambda *args: writes.append(args), self.cfg)
        self.assertEqual([call[0].id for call in writes], [938])
        self.assertIn("Temas repetidos: 939 (igual a 938)", render(report))

    def test_published_story_blocks_the_draft(self):
        published = [
            Story(
                900,
                "Murió Héctor Aguer a los 83 años, el exarzobispo emérito de La Plata",
                "La Arquidiócesis platense confirmó la muerte de monseñor Aguer.",
            )
        ]
        report = process([self.article], published, lambda _article: self.decision, lambda *_args: None, self.cfg)
        self.assertEqual(render(report), "Temas repetidos: 938 (igual a 900)")

    def test_a_published_article_is_not_written(self):
        article = replace(self.article, status="published")
        writes = []
        report = process([article], [], lambda _article: self.decision, lambda *args: writes.append(args), self.cfg)
        self.assertEqual(writes, [])
        self.assertEqual(report.failure, "no está en borrador")

    def test_failure_does_not_advance_the_last_id(self):
        advanced = []

        def decide(article):
            if article.id == 939:
                raise TypefaceError("el modelo no respondió")
            return self.decision

        second = replace(self.article, id=939, title="Otro hecho distinto en la ciudad", deck="Una obra chica.")
        report = process([self.article, second], [], decide, lambda *_args: None, self.cfg, advance=advanced.append)
        self.assertEqual(advanced, [938])
        self.assertIn("Falló 939: el modelo no respondió", render(report))
        self.assertIn("Tipografiados: 938", render(report))

    def test_summary_when_there_is_nothing_to_do(self):
        self.assertEqual(render(Report()), "No hay borradores nuevos.")

    def test_prompt_forbids_rewriting_and_copies_the_body(self):
        prompt = build_prompt(self.article, [], has_image=True)
        self.assertIn("No reescribas", prompt)
        self.assertIn("Héctor Aguer", prompt)
        self.assertIn("marca de agua", prompt)

    def test_cms_only_patches_drafts(self):
        session = Session()
        cms = Cms(session, "https://cms.basetucuman.com")
        patch, _caption = prepare(self.article, self.decision, self.cfg)
        cms.save_draft(938, patch)
        call = session.calls[0]
        self.assertEqual(call["params"], {"draft": "true"})
        self.assertEqual(call["json"]["_status"], "draft")
        self.assertNotIn("title", call["json"])

        class Explode:
            def patch(self, *args, **kwargs):
                raise AssertionError("no debía llamar al CMS")

        with self.assertRaises(TypefaceError):
            Cms(Explode(), "https://cms.basetucuman.com").save_draft(
                1, {"_status": "published", "body": {}, "category": 4}
            )

        class Published:
            def patch(self, *args, **kwargs):
                return Response(200, {"doc": {"_status": "published"}})

        with self.assertRaises(TypefaceError):
            Cms(Published(), "https://cms.basetucuman.com").save_draft(1, patch)

    def test_watermark_delete_hits_the_article_and_its_image(self):
        class DeleteSession:
            def __init__(self):
                self.urls = []

            def delete(self, url, timeout=None):
                self.urls.append(url)

                class Deleted:
                    status_code = 200
                    ok = True
                    text = ""

                return Deleted()

        session = DeleteSession()
        cms = Cms(session, "https://cms.basetucuman.com")
        cms.delete_article(940)
        cms.delete_media(12)
        self.assertEqual(
            session.urls,
            [
                "https://cms.basetucuman.com/api/articles/940",
                "https://cms.basetucuman.com/api/media/12",
            ],
        )

    def test_failed_delete_does_not_advance(self):
        advanced = []

        def remove(_article):
            raise TypefaceError("CMS 500 al eliminar articles/938")

        report = process(
            [self.article],
            [],
            lambda _article: Decision(watermark=True, watermark_source="La Gaceta", category_id=4),
            lambda *_args: None,
            self.cfg,
            advance=advanced.append,
            remove=remove,
        )
        self.assertEqual(advanced, [])
        self.assertIn("Falló 938", render(report))

    def test_fetch_image_accepts_jpeg_bytes(self):
        jpeg = b"\xff\xd8\xff\xe0" + b"foto"

        class ImageSession:
            def get(self, url, timeout=None):
                class ImageResponse:
                    status_code = 200
                    ok = True
                    content = jpeg
                    headers = {"Content-Type": "image/jpeg"}

                return ImageResponse()

        content, mime = Cms(ImageSession(), "https://cms.basetucuman.com").fetch_image(
            "https://cms.basetucuman.com/api/media/file/a.jpg"
        )
        self.assertEqual(content, jpeg)
        self.assertEqual(mime, "image/jpeg")

    def test_draft_query_filters_status_and_id(self):
        session = Session()
        Cms(session, "https://cms.basetucuman.com").drafts_after(900)
        params = session.calls[0]["params"]
        self.assertEqual(params["where[_status][equals]"], "draft")
        self.assertEqual(params["where[id][greater_than]"], 900)
        self.assertEqual(params["draft"], "true")

    def test_cms_document_maps_without_session_data(self):
        article = from_mapping(
            {
                "id": 3,
                "title": "Obra",
                "deck": "Ruta",
                "body": paragraphs_to_body(["Texto."]),
                "category": {"id": 1, "title": "Política"},
                "featuredImage": {"id": 8, "url": "https://cms.basetucuman.com/api/media/file/a.jpg", "caption": None},
                "_status": "draft",
            }
        )
        self.assertEqual(article.category_id, 1)
        self.assertEqual(article.media_id, 8)
        self.assertEqual(article.status, "draft")

    def test_last_id_roundtrip(self):
        import tempfile

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "last-id"
            self.assertIsNone(read_last_id(path))
            write_last_id(path, 938)
            self.assertEqual(read_last_id(path), 938)

    def test_fixture_command_prints_one_summary(self):
        import logging

        buffer = StringIO()
        with redirect_stdout(buffer), redirect_stderr(StringIO()):
            code = main(["once", "--fixture", str(FIXTURE), "--decisions", str(DECISIONS)])
        self.assertEqual(code, 0)
        self.assertEqual(buffer.getvalue().strip(), "Tipografiados: 938")
        logging.getLogger("typeface").propagate = False

    def test_each_article_is_logged(self):
        with self.assertLogs("typeface.pipeline", level="INFO") as captured:
            process([self.article], [], lambda _article: self.decision, lambda *_args: None, self.cfg)
        text = "\n".join(captured.output)
        self.assertIn("evaluando 938", text)
        self.assertIn("938: tipografiada", text)

        def watermark(_article):
            return Decision(watermark=True, watermark_source="La Gaceta", category_id=4)

        with self.assertLogs("typeface.pipeline", level="INFO") as captured:
            process(
                [self.article],
                [],
                watermark,
                lambda *_args: None,
                self.cfg,
                remove=lambda _article: True,
            )
        self.assertIn("eliminada por marca de agua (La Gaceta)", "\n".join(captured.output))


if __name__ == "__main__":
    unittest.main()
