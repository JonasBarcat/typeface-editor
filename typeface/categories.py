CATEGORIES = {
    1: "Política",
    2: "Economía",
    3: "Deportes",
    4: "Sociedad",
    5: "Mundo",
}


def category_name(category_id: int) -> str:
    try:
        return CATEGORIES[int(category_id)]
    except (KeyError, TypeError, ValueError) as exc:
        known = ", ".join(f"{number} {name}" for number, name in CATEGORIES.items())
        raise ValueError(f"Categoría desconocida: {category_id}. Esperadas: {known}") from exc
