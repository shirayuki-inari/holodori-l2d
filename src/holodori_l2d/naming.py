"""Portable card-based export names and stable collision handling."""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from pathlib import Path


INVALID_FOLDER_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
RESERVED_FOLDER_NAMES = {
    "CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
EXPORT_INFO = ".holodori-model.json"


def validate_name(name: str) -> None:
    if (not name or name in {".", ".."} or name.endswith((" ", "."))
            or INVALID_FOLDER_CHARS.search(name)
            or name.split(".", 1)[0].upper() in RESERVED_FOLDER_NAMES):
        raise ValueError(f"无效或不安全的保存文件名：{name!r}")


def card_filename(name: str) -> str:
    name = unicodedata.normalize("NFC", name)
    replacements = dict(zip('<>:"/\\|?*', '＜＞：＂／＼｜？＊'))
    name = "".join(replacements.get(c, c) for c in name if unicodedata.category(c)[0] != "C")
    # Leave room for extensions and disambiguation, on UTF-8 and Windows filesystems.
    name = name.encode("utf-8")[:120].decode("utf-8", errors="ignore").strip().rstrip(". ") or "未命名卡牌"
    if name.split(".", 1)[0].upper() in RESERVED_FOLDER_NAMES:
        name = "_" + name
    validate_name(name)
    return name


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
    counts = Counter(card_filename(r["name"]).casefold() for r in all_cards)
    existing = {p.name.casefold(): p for p in root.iterdir()} if root.is_dir() else {}
    used = set()
    result = []
    for row in rows:
        owner = export_key(row)
        identifier = owner.removeprefix("card-").removeprefix("live2d_mdl_")
        title = card_filename(row["name"])
        folder = title
        if counts[title.casefold()] > 1:
            who = card_filename(row.get("character") or row["character_id"])
            who = who.encode("utf-8")[:60].decode("utf-8", errors="ignore")
            folder = f"{title}（{who}）"
            # Include ID if multiple cards have the same title AND character.
            if sum(card_filename(r["name"]).casefold() == title.casefold()
                   and r["character_id"] == row["character_id"] for r in all_cards) > 1:
                folder = f"{title} [{identifier}]"
        base, attempt = folder, 0
        while True:
            key = folder.casefold()
            path = existing.get(key)
            owned = path is not None and path.is_dir() and export_owner(path) == owner
            occupied = path is not None or key + ".zip" in existing
            if key not in used and (not occupied or owned):
                if owned:
                    folder = path.name
                break
            attempt += 1
            suffix = identifier + (f"-{attempt}" if attempt > 1 else "")
            folder = f"{base} [{suffix}]"
        validate_name(folder)
        used.add(folder.casefold())
        result.append((folder, title))
    return result
