"""Card/model identifiers, portable export names and stable collision handling."""

from __future__ import annotations

import itertools
import json
import re
import unicodedata
from collections import Counter
from collections.abc import Iterator
from pathlib import Path


CARD_ID = re.compile(r"(\d{5})-\d+-([a-z0-9]+-\d{4}-\d{2})")
MODEL_ID = re.compile(r"(\d{5})-([a-z0-9]+-\d{4}-\d{2})")
INVALID_FOLDER_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
RESERVED_FOLDER_NAMES = {
    "CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
EXPORT_INFO = ".holodori-model.json"


def card_model_id(card_id: str) -> str | None:
    """Derive the model ID by dropping the rarity segment of a card ID."""
    match = CARD_ID.fullmatch(card_id.removeprefix("card-"))
    return f"{match[1]}-{match[2]}" if match else None


def model_id_from_input(value: str) -> tuple[str, str]:
    """Accept a card ID, model ID, or full live2d_mdl_* asset name."""
    value = value.removeprefix("live2d_mdl_").removeprefix("card-")
    model_id = card_model_id(value) or (value if MODEL_ID.fullmatch(value) else None)
    if model_id is None:
        raise ValueError("ID 格式应为 04016-5-uniq-0079-00 或 04016-uniq-0079-00")
    return model_id, model_id[:5]


def _reserved(name: str) -> bool:
    return name.split(".", 1)[0].upper() in RESERVED_FOLDER_NAMES


def validate_name(name: str) -> None:
    if (not name or name in {".", ".."} or name.endswith((" ", "."))
            or INVALID_FOLDER_CHARS.search(name) or _reserved(name)):
        raise ValueError(f"无效或不安全的保存文件名：{name!r}")


def _truncate(text: str, size: int) -> str:
    return text.encode("utf-8")[:size].decode("utf-8", errors="ignore")


def card_filename(name: str) -> str:
    replacements = dict(zip('<>:"/\\|?*', '＜＞：＂／＼｜？＊'))
    name = "".join(replacements.get(c, c) for c in unicodedata.normalize("NFC", name)
                   if unicodedata.category(c)[0] != "C")
    # Leave room for extensions and disambiguation, on UTF-8 and Windows filesystems.
    name = _truncate(name, 120).strip().rstrip(". ") or "未命名卡牌"
    if _reserved(name):
        name = "_" + name
    validate_name(name)
    return name


def candidates(base: str, identifier: str) -> Iterator[str]:
    """Yield ``base``, then ``base [id]``, ``base [id-2]``, ... for collisions."""
    yield base
    yield f"{base} [{identifier}]"
    for attempt in itertools.count(2):
        yield f"{base} [{identifier}-{attempt}]"


def list_names(root: Path) -> dict[str, Path]:
    return {p.name.casefold(): p for p in root.iterdir()} if root.is_dir() else {}


def export_owner(folder: Path) -> str | None:
    try:
        data = json.loads((folder / EXPORT_INFO).read_text(encoding="utf-8"))
        return data.get("export_id") or data.get("card_id")
    except (OSError, ValueError, AttributeError):
        return None


def export_key(row: dict) -> str:
    return row.get("card_id") or row["resource_name"]


def export_names(rows: list[dict], all_cards: list[dict], root: Path) -> list[tuple[str, str]]:
    """Return (folder, model basename), stable even when downloading one duplicate."""
    titles = Counter(card_filename(r["name"]).casefold() for r in all_cards)
    same_character = Counter((card_filename(r["name"]).casefold(), r["character_id"]) for r in all_cards)
    existing = list_names(root)
    used = set()
    result = []
    for row in rows:
        owner = export_key(row)
        title = card_filename(row["name"])
        identifier = owner.removeprefix("card-").removeprefix("live2d_mdl_")
        base = title
        if same_character[title.casefold(), row["character_id"]] > 1:
            base = f"{title} [{identifier}]"
        elif titles[title.casefold()] > 1:
            who = card_filename(row.get("character") or row["character_id"])
            base = f"{title}（{_truncate(who, 60)}）"
        for folder in candidates(base, identifier):
            key = folder.casefold()
            path = existing.get(key)
            owned = path is not None and path.is_dir() and export_owner(path) == owner
            if key not in used and (owned or (path is None and key + ".zip" not in existing)):
                folder = path.name if owned else folder
                break
        validate_name(folder)
        used.add(folder.casefold())
        result.append((folder, title))
    return result
