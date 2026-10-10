import json

import pytest

from holodori_l2d import master, search


@pytest.fixture
def tables():
    return {
        "Card": [
            {"id": "card-a", "character_id": "chr-00001", "name_lang_id": "name-a",
             "asset_id": "00001-5-uniq-0001-00", "reward_costume_id": "costume-a"},
            {"id": "card-b", "character_id": "chr-00002", "name_lang_id": "name-b",
             "asset_id": "00002-3-nrml-0002-00"},
            {"id": "card-c", "character_id": "chr-00001", "name_lang_id": "name-c",
             "asset_id": "00001-5-uniq-0003-00", "reward_costume_id": "costume-missing"},
            {"id": "card-d", "character_id": "chr-00001", "name_lang_id": "name-d",
             "asset_id": "00001-3-nrml-0099-00"},
        ],
        "Costume": [{"id": "costume-a", "asset_id": "00001-uniq-0123-00"}],
        "Character": [{"id": "chr-00001", "name_lang_id": "chr-name-a"},
                      {"id": "chr-00002", "name_lang_id": "chr-name-b"}],
        "LangCard": [{"id": "name-a", "text": "共享的卡名"}, {"id": "name-b", "text": "共享的卡名"},
                     {"id": "name-c", "text": "特別なＣａｒｄ"}, {"id": "name-d", "text": "候选卡牌"}],
        "LangCharacter": [{"id": "chr-name-a", "text": "角色甲"}, {"id": "chr-name-b", "text": "角色乙"}],
        "LangCostume": [],
    }


def test_mapping_uses_costume_and_preserves_missing_models(tables):
    rows = search.join_cards(tables, {"live2d_mdl_00001-uniq-0123-00", "live2d_mdl_00002-nrml-0002-00"})
    assert rows[0]["model_id"] == "00001-uniq-0123-00"  # Actual relation beats card filename.
    assert rows[0]["mapping_source"] == "reward_costume"
    assert rows[0]["model_exists"] is True
    assert rows[1]["model_id"] == "00002-nrml-0002-00"
    assert rows[1]["mapping_source"] == "card_asset_convention"
    assert rows[1]["model_exists"] is True
    assert rows[2]["model_id"] is None  # A broken explicit reference is not guessed away.
    assert rows[2]["model_exists"] is False
    assert rows[3]["model_id"] == "00001-nrml-0099-00"
    assert rows[3]["model_exists"] is False


def test_search_keeps_duplicates_filters_and_normalizes(tables):
    index = {"cards": search.join_cards(tables, set())}
    assert len(search.search_cards(index, "共享")) == 2
    assert search.search_cards(index, "共享", "00002")[0]["card_id"] == "card-b"
    assert search.search_cards(index, "共享", "角色甲")[0]["card_id"] == "card-a"
    assert search.search_cards(index, "card")[0]["card_id"] == "card-c"
    assert [r["card_id"] for r in search.search_cards(index, "角色甲")] == ["card-a", "card-c", "card-d"]
    assert len(search.search_cards(index, "角色")) == 4
    assert search.search_cards(index, "００００２")[0]["card_id"] == "card-b"
    assert search.search_cards(index, "角色甲", "00002") == []
    # Matching both the card name and the character must not duplicate a result.
    index["cards"][0]["name"] = "角色甲的卡牌"
    assert len(search.search_cards(index, "角色甲")) == 3
    assert search.search_cards(index, "不存在") == []
    with pytest.raises(ValueError, match="不能为空"):
        search.search_cards(index, "  ")


def test_official_refresh_then_offline_cache_and_failed_refresh(tmp_path, monkeypatch, tables):
    required = {"Card": "Card", "Costume": "Costume", "Character": "Character",
                "LangCard_Chs": "LangCard", "LangCharacter_Chs": "LangCharacter",
                "LangCostume_Chs": "LangCostume"}
    manifest = {"version": "synthetic", "packs": {name: {"type": name} for name in required}}
    monkeypatch.setattr(master, "fetch_master", lambda *args: manifest)
    monkeypatch.setattr(master, "read_table", lambda client, pack, schema, root: tables[required[pack["type"]]])
    monkeypatch.setattr(master, "fetch_models", lambda client: (99, set()))
    # Existing card-only caches are upgraded automatically.
    (tmp_path / "cards-chs.json").write_text(
        json.dumps({"schema_version": 1, "language": "chs", "cards": []}), encoding="utf-8",
    )
    index = search.load_index(tmp_path)
    assert index["schema_version"] == 2
    assert index["models"] == []
    assert index["master_version"] == "synthetic"
    assert index["catalog_revision"] == 99
    assert len(index["cards"]) == 4

    def fail(*args):
        raise RuntimeError("offline")

    monkeypatch.setattr(master, "fetch_master", fail)
    assert search.load_index(tmp_path) == index
    with pytest.raises(RuntimeError, match="offline"):
        search.load_index(tmp_path, refresh=True)
    assert json.loads((tmp_path / "cards-chs.json").read_text(encoding="utf-8")) == index
    with pytest.raises(RuntimeError, match="offline"):
        search.load_index(tmp_path, language="cht")  # Never reuse the wrong language.


def test_catalog_models_include_costumes_without_cards(tables):
    tables["Costume"].append({"id": "costume-extra", "asset_id": "00002-cmmn-0000-00", "name_lang_id": "extra"})
    tables["LangCostume"] = [{"id": "extra", "text": "特别服装"}]
    models = {"live2d_mdl_00001-uniq-0123-00", "live2d_mdl_00002-cmmn-0000-00",
              "live2d_mdl_00003-nrml-0003-00"}
    cards = search.join_cards(tables, models)
    # Two cards referencing one costume still produce only one model in the pack.
    cards.append({**cards[0], "card_id": "card-duplicate"})
    rows = search.join_models(tables, models, cards)
    assert len(rows) == 3
    assert rows[0]["card_id"] == "card-a"
    assert rows[1]["card_id"] is None
    assert rows[1]["name"] == "特别服装"
    assert rows[1]["character"] == "角色乙"
    assert rows[2]["name"] == "00003-nrml-0003-00"
    index = {"cards": cards, "models": rows}
    assert search.search_cards(index, "特别服装") == [rows[1]]
    assert search.search_cards(index, "00003") == [rows[2]]
