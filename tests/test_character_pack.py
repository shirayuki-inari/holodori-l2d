import json
import zipfile
from pathlib import Path

import pytest

from holodori_l2d import character_pack, cli, vtube


@pytest.fixture
def index():
    rows = [
        {"name": "卡牌甲", "card_id": "card-00001-5-uniq-0001-00", "character_id": "chr-00001",
         "character": "角色甲", "character_en": "Shirakami Fubuki", "model_id": "00001-uniq-0001-00", "resource_name": "live2d_mdl_00001-uniq-0001-00", "model_exists": True},
        {"name": "默认", "card_id": None, "character_id": "chr-00001",
         "character": "角色甲", "model_id": "00001-nrml-0001-00", "resource_name": "live2d_mdl_00001-nrml-0001-00", "model_exists": True},
        {"name": "卡牌乙", "card_id": "card-00002-5-uniq-0002-00", "character_id": "chr-00002",
         "character": "角色乙", "model_id": "00002-uniq-0002-00", "resource_name": "live2d_mdl_00002-uniq-0002-00", "model_exists": True},
    ]
    return {"cards": [rows[0], rows[2]], "models": rows, "master_version": "test", "catalog_revision": 99}


@pytest.fixture
def prepare(monkeypatch):
    calls = []

    def fake_prepare(asset_id, **options):
        calls.append((asset_id, options))
        folder = options["output_root"] / options["output_name"]
        folder.mkdir(parents=True, exist_ok=True)
        name = options["model_name"]
        (folder / (name + ".model3.json")).write_text(json.dumps({"FileReferences": {"Moc": name + ".moc3"}}))
        (folder / (name + ".moc3")).write_bytes(b"MOC3synthetic")
        if options["card_info"]["card_id"]:
            from PIL import Image
            Image.new("RGB", (8, 8)).save(folder / "icon.jpg")
        vtube.ensure_config(folder / (name + ".model3.json"))
        (folder / ".holodori-model.json").write_text(json.dumps(options["card_info"]))
        return {"output_dir": str(folder), "asset_id": asset_id.removeprefix("live2d_mdl_")}

    monkeypatch.setattr(cli, "prepare", fake_prepare)
    monkeypatch.setattr(cli, "prefetch", lambda models, **options: None)
    return calls


def test_pack_avoids_unrelated_zip_and_is_atomic(tmp_path, index, prepare, monkeypatch):
    unrelated = tmp_path / "角色甲.zip"
    unrelated.write_bytes(b"user archive")
    result = character_pack.download_character("chr-00001", index, output_root=tmp_path)
    assert Path(result["zip"]).name == "角色甲 [chr-00001].zip"
    assert unrelated.read_bytes() == b"user archive"
    original = Path(result["zip"]).read_bytes()

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(zipfile.ZipFile, "write", fail)
    with pytest.raises(OSError, match="disk full"):
        character_pack.download_character("chr-00001", index, output_root=tmp_path)
    assert Path(result["zip"]).read_bytes() == original
    assert not list(tmp_path.glob(".holodori-*"))
