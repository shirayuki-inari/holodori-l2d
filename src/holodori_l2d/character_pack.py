"""Download every catalog model for one character into a named ZIP."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from .naming import candidates, card_filename, list_names
from .search import character_label, normalize
from .util import display_path, json_bytes, output_dir, status, write_zip


MANIFEST = "holodori-character.json"
PACK_TYPE = "holodori-character-pack"


def resolve_character(index: dict, query: str) -> str:
    query = normalize(query)
    if not query:
        raise ValueError("角色名或编号不能为空")
    characters = {r["character_id"]: character_label(r) for r in index["models"]}
    keys = {}  # Normalized localized/English names and IDs of each character.
    for row in index["models"]:
        cid = row["character_id"]
        keys.setdefault(cid, {normalize(cid), cid.removeprefix("chr-")})
        keys[cid].update(normalize(name) for name in (row.get("character"), row.get("character_en")) if name)
    exact = [cid for cid, names in keys.items() if query in names]
    matches = exact or [cid for cid, names in keys.items() if any(query in name for name in names)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ValueError(f"未找到有模型的角色：{query}")
    raise ValueError("匹配到多个角色，请使用完整角色名或编号：" + "、".join(
        f"{characters[cid]} ({cid})" for cid in sorted(matches)))


def _archive_owner(path: Path) -> str | None:
    try:
        with zipfile.ZipFile(path) as archive:
            data = json.loads(archive.read(MANIFEST))
        return data.get("character_id") if data.get("type") == PACK_TYPE else None
    except (OSError, ValueError, KeyError, AttributeError, zipfile.BadZipFile):
        return None


def _archive_path(root: Path, character_id: str, name: str) -> Path:
    """Reuse this character's previous archive; never replace an unrelated ZIP."""
    existing = list_names(root)
    for stem in candidates(card_filename(name), character_id):
        path = existing.get((stem + ".zip").casefold())
        if path is None:
            return root / (stem + ".zip")
        if path.is_file() and _archive_owner(path) == character_id:
            return path
    raise AssertionError("unreachable")


def make_character_zip(root: Path, character_id: str, name: str,
                       results: list[dict], index: dict) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    folders = [Path(item["result"]["output_dir"]) for item in results]
    if len({p.name.casefold() for p in folders}) != len(folders):
        raise ValueError("角色整包内的模型目录名重复")
    for folder in folders:
        if not folder.is_dir() or not list(folder.glob("*.model3.json")):
            raise ValueError(f"缺少已导出的模型：{folder}")
    manifest = {
        "type": PACK_TYPE, "character_id": character_id, "character": name,
        "master_version": index.get("master_version"), "catalog_revision": index.get("catalog_revision"),
        "models": [{"name": item["name"], "model_id": item["result"]["asset_id"], "folder": folder.name}
                   for item, folder in zip(results, folders)],
    }
    return write_zip(_archive_path(root, character_id, name), folders, {MANIFEST: json_bytes(manifest)})


def character_models(index: dict, character_id: str) -> list[dict]:
    """Every catalog model of a character, unique by resource, not just search matches."""
    return list({r["resource_name"]: r for r in index["models"]
                 if r["character_id"] == character_id and r["model_exists"]}.values())


def download_character(character_id: str, index: dict, **options) -> dict:
    from .interactive import download_cards

    rows = character_models(index, character_id)
    if not rows:
        raise ValueError(f"资源目录中未找到此角色的模型：{character_id}")
    name = character_label(rows[0])
    status.print(f"角色全模型打包：{name}，共 {len(rows)} 个模型。")
    result = download_cards(rows, index, **{**options, "make_zip": False})
    result.update(character_id=character_id, character=name)
    if result["failed"]:
        status.print("有模型下载失败，本次未生成角色整包；可重试以补齐。")
        return result
    status.update("打包角色 ZIP……")
    archive = make_character_zip(output_dir(options.get("output_root")), character_id, name,
                                 result["results"], index)
    result["zip"] = str(archive)
    status.print(f"角色整包：{display_path(archive)}")
    return result
