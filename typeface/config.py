from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    cms_url: str = "https://cms.basetucuman.com"
    model: str = "composer-2.5"
    state_path: Path = Path("state/last-id")
    recent_published: int = 40
    duplicate_ratio: float = 0.84
    duplicate_shared_tokens: int = 6
    duplicate_strong_tokens: int = 2
    caption_max: int = 80
    max_attempts: int = 2
    work_dir: Path = Path("scratch")


def load_config(path: Path | None = None) -> Config:
    file = path or Path("config.yaml")
    if not file.is_file():
        return Config()
    raw = _parse_flat(file.read_text(encoding="utf-8"))
    defaults = Config()
    return Config(
        cms_url=str(raw.get("cms_url") or defaults.cms_url).rstrip("/"),
        model=str(raw.get("model") or defaults.model),
        state_path=Path(raw.get("state_path") or defaults.state_path),
        recent_published=int(raw.get("recent_published") or defaults.recent_published),
        duplicate_ratio=float(raw.get("duplicate_ratio") or defaults.duplicate_ratio),
        duplicate_shared_tokens=int(raw.get("duplicate_shared_tokens") or defaults.duplicate_shared_tokens),
        duplicate_strong_tokens=int(raw.get("duplicate_strong_tokens") or defaults.duplicate_strong_tokens),
        caption_max=int(raw.get("caption_max") or defaults.caption_max),
        max_attempts=int(raw.get("max_attempts") or defaults.max_attempts),
        work_dir=Path(raw.get("work_dir") or defaults.work_dir),
    )


def _parse_flat(text: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.split("#", 1)[0].strip()
        if not stripped or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        parsed[key.strip()] = value.strip().strip("\"'")
    return parsed


def read_last_id(path: Path) -> int | None:
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return None
    return int(text)


def write_last_id(path: Path, value: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(f"{value}\n", encoding="utf-8")
    temporary.replace(path)
