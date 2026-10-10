"""Download every catalog model for one character into a named ZIP."""

from __future__ import annotations

import json
import tempfile
import zipfile
from pathlib import Path

from .naming import card_filename
from .search import _normalized


MANIFEST = "holodori-character.json"


def resolve_character(index: dict, query: str) -> str:
    query = _normalized(query)
    if not query:
        raise ValueError("角色名或编号不能为空")
    characters = {r["character_id"]: r.get("character") or r["character_id"] for r in index["models"]}
    exact = [cid for cid, name in characters.items()
             if query in {_normalized(name), _normalized(cid), cid.removeprefix("chr-")}]
    matches = exact or [cid for cid, name in characters.items()
                        if query in _normalized(name) or query in _normalized(cid)]
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
        if data.get("type") == "holodori-character-pack":
            return data.get("character_id")
    except (OSError, ValueError, KeyError, AttributeError, zipfile.BadZipFile):
        pass
    return None


def make_character_zip(root: Path, character_id: str, name: str,
                       results: list[dict], index: dict) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    basename = card_filename(name)
    existing = {p.name.casefold(): p for p in root.iterdir()}
    candidate, attempt = basename + ".zip", 0
    while candidate.casefold() in existing:
        path = existing[candidate.casefold()]
        if path.is_file() and _archive_owner(path) == character_id:
            candidate = path.name
            break
        attempt += 1
        suffix = character_id + (f"-{attempt}" if attempt > 1 else "")
        candidate = f"{basename} [{suffix}].zip"
    destination = root / candidate
    folders = [Path(item["result"]["output_dir"]) for item in results]
    if len({p.name.casefold() for p in folders}) != len(folders):
        raise ValueError("角色整包内的模型目录名重复")
    for folder in folders:
        if not folder.is_dir() or not list(folder.glob("*.model3.json")):
            raise ValueError(f"缺少已导出的模型：{folder}")
    manifest = {
        "type": "holodori-character-pack", "character_id": character_id, "character": name,
        "master_version": index.get("master_version"), "catalog_revision": index.get("catalog_revision"),
        "models": [{"name": item["name"], "model_id": item["result"]["asset_id"], "folder": folder.name}
                   for item, folder in zip(results, folders)],
    }
    with tempfile.NamedTemporaryFile(prefix="character-", suffix=".zip", dir=root, delete=False) as file:
        temporary = Path(file.name)
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
            for folder in folders:
                for path in sorted(folder.rglob("*")):
                    if path.is_file():
                        archive.write(path, folder.name + "/" + path.relative_to(folder).as_posix())
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def download_character(character_id: str, index: dict, **options) -> dict:
    from .interactive import download_cards

    # Models come from the full catalog, not the current search results.
    rows = list({r["resource_name"]: r for r in index["models"]
                 if r["character_id"] == character_id and r["model_exists"]}.values())
    if not rows:
        raise ValueError(f"资源目录中未找到此角色的模型：{character_id}")
    name = rows[0].get("character") or character_id
    print(f"角色全模型打包：{name}，共 {len(rows)} 个模型。", flush=True)
    result = download_cards(rows, index, **{**options, "make_zip": False})
    result.update(character_id=character_id, character=name)
    if result["failed"]:
        print("有模型下载失败，本次未生成角色整包；可重试以补齐。", flush=True)
        return result
    root = options.get("output_root") or Path.cwd() / "output"
    archive = make_character_zip(root, character_id, name, result["results"], index)
    result["zip"] = str(archive)
    print(f"角色整包已生成：{archive}", flush=True)
    return result
