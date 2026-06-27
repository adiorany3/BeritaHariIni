"""Penyimpanan JSON sederhana untuk hasil pencarian dan dashboard Streamlit."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json(path: str | Path, default: Any) -> Any:
    file_path = Path(path)
    if not file_path.exists():
        return default
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: str | Path, data: Any) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = file_path.with_suffix(file_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False),
        encoding="utf-8",
    )
    temporary.replace(file_path)


def article_ids(payload: dict[str, Any]) -> set[str]:
    return {
        str(article.get("id"))
        for article in payload.get("articles", [])
        if isinstance(article, dict) and article.get("id")
    }
