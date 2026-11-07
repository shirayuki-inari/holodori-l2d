"""Search official localized card/character names and find Live2D model IDs."""

from __future__ import annotations

import argparse
import json
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from . import master
from .naming import card_model_id
from .util import cache_dir, json_bytes, use_utf8_stdio, write_atomic


SCHEMAS = {
    "Card": {1: "id", 2: "character_id", 3: "name_lang_id", 18: "asset_id", 23: "reward_costume_id"},
    "Costume": {1: "id", 3: "name_lang_id", 5: "asset_id"},
    "Character": {1: "id", 2: "name_lang_id", 4: "name_eng"},
    "Lang": {1: "id", 1000: "text"},
}
LANGUAGES = {"chs": "Chs", "cht": "Cht"}
TABLES = ("Card", "Costume", "Character", "LangCard", "LangCharacter", "LangCostume")
QUERY_KEYS = ("name", "character", "character_id")
CHARACTER_KEYS = ("character", "character_id")


def downloadable(row: dict) -> bool:
    return bool(row.get("model_exists") and row.get("resource_name"))


def character_label(row: dict) -> str:
    return row.get("character") or row["character_id"]


def _by_id(rows: list[dict]) -> dict[str, dict]:
    return {row["id"]: row for row in rows}


def _character_names(tables: dict[str, list[dict]]) -> dict[str, str | None]:
    """Map character IDs to localized names, falling back to English."""
    texts = {row["id"]: row.get("text") for row in tables["LangCharacter"]}
    return {row["id"]: texts.get(row.get("name_lang_id")) or row.get("name_eng")
            for row in tables["Character"]}


def join_cards(tables: dict[str, list[dict]], models: set[str]) -> list[dict]:
    costumes = _by_id(tables["Costume"])
    characters = _character_names(tables)
    names = {row["id"]: row.get("text") for row in tables["LangCard"]}
    results = []
    for card in tables["Card"]:
        if card.get("reward_costume_id"):
            model_id = costumes.get(card["reward_costume_id"], {}).get("asset_id") or None
            source = "reward_costume"
        else:
            model_id = card_model_id(card.get("asset_id", ""))
            source = "card_asset_convention"
        resource = f"live2d_mdl_{model_id}" if model_id else None
        results.append({
            "name": names.get(card.get("name_lang_id")) or None,
            "character": characters.get(card.get("character_id")),
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
    characters = _character_names(tables)
    costume_names = {row["id"]: row.get("text") for row in tables["LangCostume"]}
    result = []
    for resource in sorted(models):
        if resource in by_resource:
            result.append(dict(by_resource[resource]))
            continue
        model_id = resource.removeprefix("live2d_mdl_")
        character_id = "chr-" + model_id.split("-", 1)[0]
        costume = costumes.get(model_id, {})
        result.append({
            "name": costume_names.get(costume.get("name_lang_id")) or model_id,
            "character": characters.get(character_id) or character_id,
            "character_id": character_id, "card_id": None, "model_id": model_id,
            "resource_name": resource, "model_exists": True, "mapping_source": "catalog_costume",
        })
    return result


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
    packs = {label: label + "_" + LANGUAGES[language] if label.startswith("Lang") else label
             for label in TABLES}
    missing = set(packs.values()) - manifest["packs"].keys()
    if missing:
        raise ValueError("官方主数据缺少所需表：" + ", ".join(sorted(missing)))
    with httpx.Client(http2=True, timeout=120, follow_redirects=True) as client:
        tables = {
            label: master.read_table(client, manifest["packs"][pack],
                                     SCHEMAS["Lang" if label.startswith("Lang") else label], cache_root)
            for label, pack in packs.items()
        }
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
    write_atomic(path, json_bytes(data))
    return data


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold().strip()


def _matches(row: dict, text: str, keys: tuple[str, ...], *, exact: bool = False) -> bool:
    values = (normalize(row.get(key) or "") for key in keys)
    return any(text == value if exact else text in value for value in values)


def browse_rows(index: dict, character: str | None = None) -> list[dict]:
    """All cards plus no-card costume models, optionally filtered by character."""
    rows = index["cards"] + [row for row in index.get("models", []) if row["card_id"] is None]
    character = normalize(character or "")
    return [row for row in rows if _matches(row, character, CHARACTER_KEYS)] if character else rows


def search_cards(index: dict, query: str, character: str | None = None) -> list[dict]:
    query = normalize(query)
    if not query:
        raise ValueError("搜索词不能为空")
    results = [row for row in browse_rows(index, character) if _matches(row, query, QUERY_KEYS)]
    return sorted(results, key=lambda row: (
        not _matches(row, query, QUERY_KEYS, exact=True), row["card_id"] or row["resource_name"],
    ))


def main() -> None:
    use_utf8_stdio()
    parser = argparse.ArgumentParser(description="使用官方主数据按卡牌名或角色名搜索 Live2D 模型")
    parser.add_argument("query", help="卡牌名、角色名或编号，支持部分名称")
    parser.add_argument("--character", help="同名卡牌可按角色中文名或编号筛选")
    parser.add_argument("--lang", choices=LANGUAGES, default="chs", help="chs 简中（默认）/ cht 繁中")
    parser.add_argument("--refresh", action="store_true", help="从官方接口刷新主数据和资源索引")
    parser.add_argument("--app-version", default=master.APP_VERSION, help="游戏客户端版本（用于官方接口）")
    parser.add_argument("--cache-root", type=Path, default=cache_dir() / "master")
    args = parser.parse_args()
    try:
        if not normalize(args.query):
            raise ValueError("搜索词不能为空")  # Fail before any network access.
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
