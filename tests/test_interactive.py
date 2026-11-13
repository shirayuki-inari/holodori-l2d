import zipfile
from pathlib import Path

from holodori_l2d import cli, interactive, naming


def card(number, name="同名卡牌"):
    return {"card_id": f"card-{number:05d}-5-uniq-0001-00", "name": name,
            "character": f"角色{number}", "character_id": f"chr-{number:05d}",
            "resource_name": f"live2d_mdl_{number:05d}-uniq-0001-00", "model_exists": True}


def test_illegal_names_collisions_and_zip_only(tmp_path):
    rows = [card(1, 'a/b:*?'), card(2, 'a／b：＊？')]
    names = naming.export_names(rows, rows, tmp_path)
    assert names[0][0] != names[1][0]
    assert names[0][1] == 'a／b：＊？'
    assert naming.card_filename('CON') == '_CON'
    for name in ('.', '..', '\x00', '长' * 200):
        sanitized = naming.card_filename(name)
        naming.validate_name(sanitized)
        assert len(sanitized.encode()) <= 120
    one = card(1, "独立卡牌")
    (tmp_path / "独立卡牌.zip").write_bytes(b"existing archive")
    assert naming.export_names([one], [one], tmp_path)[0][0] != "独立卡牌"


def test_selected_downloads_share_one_zip(tmp_path, monkeypatch):
    rows = [card(1, "第一张卡"), card(2, "第二张卡")]

    def prepare(asset_id, **options):
        assert options["make_zip"] is False  # No per-model archives.
        folder = tmp_path / options["output_name"]
        folder.mkdir()
        (folder / "m.model3.json").write_text("{}")
        return {"output_dir": str(folder)}

    monkeypatch.setattr(cli, "prepare", prepare)
    monkeypatch.setattr(cli, "prefetch", lambda models, **options: None)
    result = interactive.download_cards(rows, {"cards": rows}, output_root=tmp_path, make_zip=True)
    assert list(tmp_path.glob("*.zip")) == [Path(result["zip"])]
    with zipfile.ZipFile(result["zip"]) as archive:
        assert sorted(archive.namelist()) == ["第一张卡/m.model3.json", "第二张卡/m.model3.json"]
