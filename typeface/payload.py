from __future__ import annotations

from typeface.categories import CATEGORIES, category_name


def article_patch(body: dict, category_id: int) -> dict:
    """Arma el único PATCH permitido: el borrador sigue en borrador."""
    category_name(category_id)
    patch = {
        "body": body,
        "category": int(category_id),
        "_status": "draft",
    }
    if patch["_status"] != "draft":
        raise RuntimeError("El patch de una nota no puede salir de borrador.")
    if set(patch) != {"body", "category", "_status"}:
        raise RuntimeError("El patch de una nota trae campos de más.")
    return patch


def allowed_category(category_id: int) -> bool:
    try:
        return int(category_id) in CATEGORIES
    except (TypeError, ValueError):
        return False
