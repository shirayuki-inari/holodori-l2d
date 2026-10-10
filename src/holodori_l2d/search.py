"""Search official localized card/character names and find Live2D model IDs."""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from . import master


SCHEMAS = {
    "Card": {1: "id", 2: "character_id", 3: "name_lang_id", 18: "asset_id", 23: "reward_costume_id"},
    "Costume": {1: "id", 3: "name_lang_id", 5: "asset_id"},
    "Character": {1: "id", 2: "name_lang_id", 4: "name_eng"},
    "Lang": {1: "id", 1000: "text"},
}
LANGUAGES = {"chs": "Chs", "cht": "Cht"}


def join_cards(tables: dict[str, list[dict]], models: set[str]) -> list[dict]:
    costumes = {row["id"]: row for row in tables["Costume"]}
    characters = {row["id"]: row for row in tables["Character"]}
    names = {row["id"]: row.get("text", "") for row in tables["LangCard"]}
    character_names = {row["id"]: row.get("text", "") for row in tables["LangCharacter"]}
    results = []
    for card in tables["Card"]:
        character = characters.get(card.get("character_id"), {})
        costume_id = card.get("reward_costume_id")
        model_id = None
        if costume_id:
            model_id = costumes.get(costume_id, {}).get("asset_id") or None
            source = "reward_costume"
        else:
            match = re.fullmatch(r"(\d{5})-\d+-([a-z0-9]+-\d{4}-\d{2})", card.get("asset_id", ""))
            if match:
                model_id = f"{match[1]}-{match[2]}"
            source = "card_asset_convention"
        resource = f"live2d_mdl_{model_id}" if model_id else None
        results.append({
            "name": names.get(card.get("name_lang_id")) or None,
            "character": character_names.get(character.get("name_lang_id")) or character.get("name_eng"),
            "character_id": card.get("character_id"),
            "card_id": card["id"],
            "model_id": model_id,
            "resource_name": resource,
            "model_exists": resource in models,
            "mapping_source": source,
        })
    return sorted(results, key=lambda row: row["card_id"])


def join_models(tables: dict[str, list[dict]], models: set[str], cards: list[dict]) -> list[dict]:
    """Include every catalog model, including costumes with no card record."""
    by_resource = {}
    for row in cards:
        by_resource.setdefault(row["resource_name"], row)
    costumes = {row["asset_id"]: row for row in tables["Costume"]}
    characters = {row["id"]: row for row in tables["Character"]}
    names = {row["id"]: row.get("text") for row in tables["LangCharacter"]}
    costume_names = {row["id"]: row.get("text") for row in tables["LangCostume"]}
    result = []
    for resource in sorted(models):
        if resource in by_resource:
            result.append(dict(by_resource[resource]))
            continue
        model_id = resource.removeprefix("live2d_mdl_")
        character_id = "chr-" + model_id.split("-", 1)[0]
        character = characters.get(character_id, {})
        costume = costumes.get(model_id, {})
        result.append({
            "name": costume_names.get(costume.get("name_lang_id")) or model_id,
            "character": names.get(character.get("name_lang_id")) or character.get("name_eng") or character_id,
            "character_id": character_id, "card_id": None, "model_id": model_id,
            "resource_name": resource, "model_exists": True, "mapping_source": "catalog_costume",
        })
    return result


def browse_rows(index: dict) -> list[dict]:
    return index["cards"] + [row for row in index.get("models", []) if row["card_id"] is None]


def load_index(cache_root: Path, *, language: str = "chs", refresh: bool = False,
               app_version: str = master.APP_VERSION) -> dict:
    if language not in LANGUAGES:
        raise ValueError("语言应为 chs 或 cht")
    path = cache_root / f"cards-{language}.json"
    if path.exists() and not refresh:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema_version") not in (1, 2) or data.get("language") != language:
            raise ValueError("卡牌索引缓存格式不兼容，请加 --refresh 重建")
        if data["schema_version"] == 2:
            return data
        # Upgrade the old card-only cache automatically; save only after success.
    import httpx

    manifest = master.fetch_master(language, app_version)
    suffix = LANGUAGES[language]
    required = {"Card": "Card", "Costume": "Costume", "Character": "Character",
                "LangCard": f"LangCard_{suffix}", "LangCharacter": f"LangCharacter_{suffix}",
                "LangCostume": f"LangCostume_{suffix}"}
    missing = set(required.values()) - manifest["packs"].keys()
    if missing:
        raise ValueError("官方主数据缺少所需表：" + ", ".join(sorted(missing)))
    tables = {}
    with httpx.Client(http2=True, timeout=120, follow_redirects=True) as client:
        for label, pack_type in required.items():
            tables[label] = master.read_table(
                client, manifest["packs"][pack_type],
                SCHEMAS["Lang" if label.startswith("Lang") else label], cache_root,
            )
        revision, models = master.fetch_models(client)
    rows = join_cards(tables, models)
    if not rows or any(row["name"] is None for row in rows):
        raise ValueError("卡牌名称表为空或有缺失，未更新缓存")
    data = {
        "schema_version": 2, "language": language,
        "master_version": manifest["version"], "catalog_revision": revision,
        "fetched_at": datetime.now(timezone.utc).isoformat(), "cards": rows,
        "models": join_models(tables, models, rows),
    }
    master.write_atomic(path, (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return data


def _normalized(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold().strip()


def search_cards(index: dict, query: str, character: str | None = None) -> list[dict]:
    query = _normalized(query)
    if not query:
        raise ValueError("搜索词不能为空")
    character = _normalized(character) if character else None
    results = [row for row in browse_rows(index)
               if any(query in _normalized(row.get(key) or "")
                      for key in ("name", "character", "character_id"))
               and (not character or any(character in _normalized(row.get(key) or "")
                                          for key in ("character", "character_id")))]
    return sorted(results, key=lambda row: (
        not any(_normalized(row.get(key) or "") == query for key in ("name", "character", "character_id")),
        row["card_id"] or row["resource_name"],
    ))


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="使用官方主数据按卡牌名或角色名搜索 Live2D 模型")
    parser.add_argument("query", help="卡牌名、角色名或编号，支持部分名称")
    parser.add_argument("--character", help="同名卡牌可按角色中文名或编号筛选")
    parser.add_argument("--lang", choices=LANGUAGES, default="chs", help="chs 简中（默认）/ cht 繁中")
    parser.add_argument("--refresh", action="store_true", help="从官方接口刷新主数据和资源索引")
    parser.add_argument("--app-version", default=master.APP_VERSION, help="游戏客户端版本（用于官方接口）")
    parser.add_argument("--cache-root", type=Path, default=Path("input/.holodori_assets/master"))
    args = parser.parse_args()
    try:
        if not args.query.strip():
            raise ValueError("搜索词不能为空")
        index = load_index(args.cache_root, language=args.lang, refresh=args.refresh, app_version=args.app_version)
        results = search_cards(index, args.query, args.character)
    except ImportError:
        parser.exit(1, '缺少查询依赖，请运行：python -m pip install -e .\n')
    except Exception as error:
        parser.exit(1, f"查询失败：{error}\n")
    print(json.dumps({
        "language": index["language"], "master_version": index["master_version"],
        "catalog_revision": index["catalog_revision"], "fetched_at": index["fetched_at"],
        "total": len(results), "results": results,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
