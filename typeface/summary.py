from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Report:
    typeset: list[int] = field(default_factory=list)
    watermarks: list[tuple[int, str]] = field(default_factory=list)
    categories: list[tuple[int, str, str]] = field(default_factory=list)
    duplicates: list[tuple[int, int]] = field(default_factory=list)
    failure_id: int | None = None
    failure: str = ""

    @property
    def ok(self) -> bool:
        return self.failure_id is None


def render(report: Report) -> str:
    lines: list[str] = []
    if report.typeset:
        lines.append("Tipografiados: " + ", ".join(str(item) for item in report.typeset))
    if report.watermarks:
        parts = [f"{article_id} ({source})" if source else str(article_id) for article_id, source in report.watermarks]
        lines.append("Eliminadas por marca de agua: " + ", ".join(parts))
    if report.categories:
        parts = [f"{article_id} {before} → {after}" for article_id, before, after in report.categories]
        lines.append("Categorías: " + "; ".join(parts))
    if report.duplicates:
        parts = [f"{article_id} (igual a {other_id})" for article_id, other_id in report.duplicates]
        lines.append("Temas repetidos: " + ", ".join(parts))
    if report.failure_id is not None:
        lines.append(f"Falló {report.failure_id}: {report.failure}")
    if not lines:
        return "No hay borradores nuevos."
    return "\n".join(lines)
