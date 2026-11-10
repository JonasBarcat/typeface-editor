from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from typeface.lexical import paragraphs_to_body


@dataclass
class Article:
    id: int
    title: str
    deck: str
    body: dict
    category_id: int
    media_id: int | None = None
    image_url: str | None = None
    caption: str | None = None
    status: str = "draft"

    @property
    def has_image(self) -> bool:
        return self.media_id is not None or bool(self.image_url)


def from_mapping(data: dict) -> Article:
    if "paragraphs" in data:
        body = paragraphs_to_body(data["paragraphs"])
    else:
        body = data["body"]
    category = data.get("category_id", data.get("category"))
    if isinstance(category, dict):
        category = category.get("id")
    image = data.get("featuredImage")
    media_id = data.get("media_id")
    image_url = data.get("image_url")
    caption = data.get("caption")
    if isinstance(image, dict):
        media_id = image.get("id")
        image_url = image.get("url")
        caption = image.get("caption")
    elif isinstance(image, int):
        media_id = image
    return Article(
        id=int(data["id"]),
        title=str(data.get("title") or ""),
        deck=str(data.get("deck") or ""),
        body=body,
        category_id=int(category),
        media_id=None if media_id is None else int(media_id),
        image_url=image_url or None,
        caption=caption,
        status=str(data.get("status") or data.get("_status") or "draft"),
    )


def load_article(path: Path) -> Article:
    return from_mapping(json.loads(path.read_text(encoding="utf-8")))
