import pytest

from holodori_l2d import search


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
        "Character": [{"id": "chr-00001", "name_lang_id": "chr-name-a", "name_eng": "Alpha Idol"},
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
