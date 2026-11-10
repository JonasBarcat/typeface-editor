from __future__ import annotations

import os

from typeface.article import Article, from_mapping
from typeface.config import Config
from typeface.duplicates import Story
from typeface.errors import TypefaceError
from typeface.payload import article_patch


class Cms:
    """Cliente del CMS. Solo actualiza borradores."""

    def __init__(self, session, cms_url: str):
        self.session = session
        self.cms_url = cms_url.rstrip("/")

    def drafts_after(self, last_id: int) -> list[Article]:
        page = 1
        found: list[Article] = []
        while True:
            response = self.session.get(
                f"{self.cms_url}/api/articles",
                params={
                    "where[_status][equals]": "draft",
                    "where[id][greater_than]": last_id,
                    "sort": "id",
                    "limit": 50,
                    "page": page,
                    "depth": 1,
                    "draft": "true",
                },
                timeout=60,
            )
            data = _check(response)
            found.extend(from_mapping(doc) for doc in data.get("docs") or [])
            if not data.get("hasNextPage"):
                break
            page += 1
        return found

    def recent_published(self, limit: int) -> list[Story]:
        response = self.session.get(
            f"{self.cms_url}/api/articles",
            params={
                "where[_status][equals]": "published",
                "sort": "-publishedAt",
                "limit": limit,
                "depth": 0,
                "page": 1,
            },
            timeout=60,
        )
        data = _check(response)
        stories: list[Story] = []
        for doc in data.get("docs") or []:
            stories.append(Story(int(doc["id"]), str(doc.get("title") or ""), str(doc.get("deck") or "")))
        return stories

    def fetch_image(self, url: str) -> tuple[bytes, str]:
        absolute = url if url.startswith("http") else f"{self.cms_url}/{url.lstrip('/')}"
        response = self.session.get(absolute, timeout=60)
        content = response.content or b""
        headers = getattr(response, "headers", {}) or {}
        mime = str(headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if response.status_code == 403 or (mime.startswith("text/html") and b"just a moment" in content[:800].lower()):
            raise TypefaceError("Cloudflare bloqueó la imagen del CMS.")
        if not response.ok:
            snippet = content[:200].decode("utf-8", errors="replace")
            raise TypefaceError(f"CMS {response.status_code} al bajar la imagen: {snippet}")
        if not content:
            raise TypefaceError("la imagen principal vino vacía")
        if not mime.startswith("image/"):
            mime = _image_mime(content)
        return content, mime

    def save_caption(self, media_id: int, caption: str) -> None:
        response = self.session.patch(
            f"{self.cms_url}/api/media/{media_id}",
            json={"caption": caption},
            timeout=60,
        )
        _check(response)

    def save_draft(self, article_id: int, patch: dict) -> None:
        if patch.get("_status") != "draft":
            raise TypefaceError("se rechazó un guardado que no deja la nota en borrador")
        article_patch(patch["body"], patch["category"])
        response = self.session.patch(
            f"{self.cms_url}/api/articles/{article_id}",
            params={"draft": "true"},
            json=patch,
            timeout=60,
        )
        data = _check(response)
        doc = data.get("doc") or data
        status = doc.get("_status")
        if status not in (None, "draft"):
            raise TypefaceError(f"el CMS devolvió _status={status} para {article_id}")

    def delete_article(self, article_id: int) -> None:
        self._delete("articles", article_id)

    def delete_media(self, media_id: int) -> None:
        self._delete("media", media_id)

    def _delete(self, collection: str, doc_id: int) -> None:
        response = self.session.delete(
            f"{self.cms_url}/api/{collection}/{doc_id}",
            timeout=60,
        )
        if response.status_code == 404:
            return
        if not response.ok:
            snippet = (response.text or "")[:300]
            raise TypefaceError(f"CMS {response.status_code} al eliminar {collection}/{doc_id}: {snippet}")


def connect(cfg: Config) -> Cms:
    try:
        import requests
    except ImportError as exc:
        raise TypefaceError("Falta requests. Instalá las dependencias con pip install -r requirements.txt") from exc

    session = requests.Session()
    session.headers["User-Agent"] = "typeface-editor/1.0"
    token = os.environ.get("CMS_TOKEN") or os.environ.get("JWT")
    if not token:
        email = os.environ.get("CMS_EMAIL")
        password = os.environ.get("CMS_PASSWORD")
        if not email or not password:
            raise TypefaceError("Falta CMS_TOKEN o CMS_EMAIL y CMS_PASSWORD.")
        response = session.post(
            f"{cfg.cms_url}/api/users/login",
            json={"email": email, "password": password},
            timeout=30,
        )
        data = _check(response)
        token = data.get("token")
        if not token:
            raise TypefaceError("El CMS no devolvió token.")
    session.headers["Authorization"] = f"JWT {token}"
    return Cms(session, cfg.cms_url)


def _image_mime(content: bytes) -> str:
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG"):
        return "image/png"
    if content.startswith(b"GIF8"):
        return "image/gif"
    if content.startswith(b"RIFF") and b"WEBP" in content[:16]:
        return "image/webp"
    raise TypefaceError("la imagen principal no es una imagen")


def _check(response) -> dict:
    text = response.text or ""
    if response.status_code == 403 and "just a moment" in text.lower():
        raise TypefaceError("Cloudflare bloqueó el pedido al CMS.")
    if not response.ok:
        raise TypefaceError(f"CMS {response.status_code}: {text[:300]}")
    try:
        data = response.json()
    except ValueError as exc:
        raise TypefaceError("El CMS no devolvió JSON.") from exc
    if not isinstance(data, dict):
        raise TypefaceError("El CMS devolvió una respuesta inesperada.")
    return data
