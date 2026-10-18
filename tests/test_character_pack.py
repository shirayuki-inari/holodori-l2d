import json
import sys
import zipfile
from pathlib import Path

import pytest
import httpx
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from holodori_l2d import character_pack, cli, interactive, search, vtube


@pytest.fixture
def index():
    rows = [
        {"name": "卡牌甲", "card_id": "card-00001-5-uniq-0001-00", "character_id": "chr-00001",
         "character": "角色甲", "model_id": "00001-uniq-0001-00", "resource_name": "live2d_mdl_00001-uniq-0001-00", "model_exists": True},
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
    return calls


def test_pack_contains_all_unique_models_not_just_search_matches(tmp_path, index, prepare):
    index["models"].append(dict(index["models"][0]))
    result = character_pack.download_character("chr-00001", index, output_root=tmp_path)
    assert result["total"] == 2 and result["failed"] == 0
    assert all(call[1]["make_zip"] is False for call in prepare)
    assert Path(result["zip"]).name == "角色甲.zip"
    with zipfile.ZipFile(result["zip"]) as archive:
        assert archive.testzip() is None
        manifest = json.loads(archive.read(character_pack.MANIFEST))
        assert {row["model_id"] for row in manifest["models"]} == {"00001-uniq-0001-00", "00001-nrml-0001-00"}
        assert not any("卡牌乙" in name for name in archive.namelist())
        assert "默认/默认.model3.json" in archive.namelist()
        assert archive.read("默认/默认.moc3") == b"MOC3synthetic"
        assert "卡牌甲/icon.jpg" in archive.namelist()
        assert "默认/icon.jpg" not in archive.namelist()
        assert json.loads(archive.read("卡牌甲/卡牌甲.vtube.json"))["FileReferences"]["Icon"] == "icon.jpg"
        assert json.loads(archive.read("默认/默认.vtube.json"))["FileReferences"]["Icon"] == ""
    # Reruns reuse model folders (including no-card models) and update the owned ZIP.
    again = character_pack.download_character("chr-00001", index, output_root=tmp_path)
    assert again["zip"] == result["zip"]
    assert [r["result"]["output_dir"] for r in again["results"]] == [r["result"]["output_dir"] for r in result["results"]]
    assert len(list(tmp_path.glob("*.zip"))) == 1


def test_partial_failure_preserves_previous_archive(tmp_path, index, prepare, monkeypatch):
    result = character_pack.download_character("chr-00001", index, output_root=tmp_path)
    archive = Path(result["zip"])
    original = archive.read_bytes()
    delegate = cli.prepare

    def fail_one(asset_id, **options):
        if "nrml" in asset_id:
            raise RuntimeError("download failed")
        return delegate(asset_id, **options)

    monkeypatch.setattr(cli, "prepare", fail_one)
    result = character_pack.download_character("chr-00001", index, output_root=tmp_path)
    assert result["failed"] == 1 and "zip" not in result
    assert archive.read_bytes() == original


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
    assert not list(tmp_path.glob("character-*.zip"))


def test_resolve_character_and_keyboard_shortcut(index):
    assert character_pack.resolve_character(index, "角色甲") == "chr-00001"
    assert character_pack.resolve_character(index, "００００１") == "chr-00001"
    with pytest.raises(ValueError, match="多个角色"):
        character_pack.resolve_character(index, "角色")
    with pytest.raises(ValueError, match="未找到"):
        character_pack.resolve_character(index, "不存在")
    with create_pipe_input() as pipe:
        pipe.send_text(" \x1b[Bp")
        chosen = interactive.select_cards(index["cards"], input=pipe, output=DummyOutput())
    # P acts on the focused character, not the previously checked card.
    assert chosen == interactive.CharacterPackRequest("chr-00002")


def test_default_ui_pack_expands_beyond_search_result(index, monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(search, "load_index", lambda *a, **kw: index)

    def choose(rows):
        assert len(rows) == 1
        return interactive.CharacterPackRequest(rows[0]["character_id"])

    monkeypatch.setattr(interactive, "select_cards", choose)
    monkeypatch.setattr(character_pack, "download_character", lambda cid, data, **kw: data["models"])
    result = interactive.run("卡牌甲", language="chs", character=None, refresh=False, app_version="1.2.1")
    assert result == index["models"]


def test_pack_cli_reports_failed_downloads(index, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["holodori-l2d", "--pack-character", "角色甲"])
    monkeypatch.setattr(search, "load_index", lambda *a, **kw: index)
    monkeypatch.setattr(character_pack, "download_character", lambda *a, **kw: {"failed": 1})
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 1


def test_pack_cli_network_failure_has_no_traceback(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["holodori-l2d", "--pack-character", "角色甲"])

    def unavailable(*args, **kwargs):
        raise httpx.ConnectError("synthetic network failure")

    monkeypatch.setattr(search, "load_index", unavailable)
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 1
    message = capsys.readouterr().err
    assert "synthetic network failure" in message and "Traceback" not in message
