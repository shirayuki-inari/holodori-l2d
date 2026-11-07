import json
import re
import sys
import types
import zipfile
from pathlib import Path

import pytest

from holodori_l2d import cli


@pytest.mark.parametrize(
    "value",
    [
        "04016-5-uniq-0079-00",
        "card-04016-5-uniq-0079-00",
        "04016-uniq-0079-00",
        "live2d_mdl_04016-uniq-0079-00",
    ],
)
def test_model_id_from_input(value):
    assert cli.model_id_from_input(value) == ("04016-uniq-0079-00", "04016")


@pytest.mark.parametrize("value", ["", "../04016-uniq-0079-00", "04016-uniq", "abc"])
def test_rejects_invalid_id(value):
    with pytest.raises(ValueError, match="ID 格式"):
        cli.model_id_from_input(value)


def test_selects_only_matching_assets():
    names = {
        "live2d_mdl_04016-uniq-0079-00",
        "live2d_exp_smile-01_04016_000",
        "live2d_exp_smile-01_00006_000",
        "live2d_mot_idle-01_lv05_lp",
        "live2d_mot_idle-01_lv04_lp",
    }
    expressions, motions = cli._selected_assets(
        names, "04016-uniq-0079-00", "04016", "lv05"
    )
    assert expressions == ["live2d_exp_smile-01_04016_000"]
    assert motions == ["live2d_mot_idle-01_lv05_lp"]


def test_extract_bundle_reports_upstream_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.platform, "system", lambda: "Linux")

    class FailingBundle:
        def __init__(self, source, name):
            pass

        def extract(self, destination):
            raise ValueError("broken texture")

    extract = types.ModuleType("holodori_asset_tools.entrypoint.extract")
    extract.AssetBundle = FailingBundle
    monkeypatch.setitem(sys.modules, "holodori_asset_tools.entrypoint.extract", extract)
    with pytest.raises(RuntimeError, match="资源包提取失败：live2d_mdl_test：broken texture"):
        cli._extract_bundle(tmp_path / "live2d_mdl_test", tmp_path)


def test_android_extract_does_not_require_fmod(tmp_path, monkeypatch):
    monkeypatch.setattr(cli.platform, "system", lambda: "Android")
    monkeypatch.delitem(sys.modules, "fmod_toolkit", raising=False)

    class Bundle:
        def __init__(self, source, name):
            pass

        def extract(self, destination):
            assert isinstance(sys.modules["fmod_toolkit"], types.ModuleType)

    extract = types.ModuleType("holodori_asset_tools.entrypoint.extract")
    extract.AssetBundle = Bundle
    monkeypatch.setitem(sys.modules, "holodori_asset_tools.entrypoint.extract", extract)
    cli._extract_bundle(tmp_path / "live2d_mdl_test", tmp_path)
    monkeypatch.delitem(sys.modules, "fmod_toolkit")


@pytest.mark.parametrize(
    "card_id,output_name,model_title",
    [
        ("04016-5-uniq-0079-00", None, None),
        ("card-04016-5-uniq-0079-00", None, None),
        ("04016-uniq-0079-00", None, None),
        ("live2d_mdl_04016-uniq-0079-00", None, None),
        ("04016-5-uniq-0079-00", "Fubuki Live2D v1.0", None),
        ("04016-5-uniq-0079-00", "中文卡牌♡（角色）", "中文卡牌♡"),
    ],
)
@pytest.mark.parametrize("with_thumbnail", [True, False])
def test_prepare_offline_with_synthetic_assets(
    tmp_path, monkeypatch, card_id, output_name, model_title, with_thumbnail
):
    model_name = "live2d_mdl_04016-uniq-0079-00"
    expression_name = "live2d_exp_smile-01_04016_000"
    thumbnail_name = "img_card_live_thumb_04016-5-uniq-0079-00"
    selected = [model_name, expression_name] + ([thumbnail_name] if with_thumbnail else [])
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "octo_list.json").write_text(
        json.dumps({"assetBundles": [{"name": name} for name in selected]}),
        encoding="utf-8",
    )
    fake_catalog = types.SimpleNamespace(get=lambda path: None)
    fake_package = types.ModuleType("holodori_asset_tools")
    fake_package.catalog = fake_catalog
    monkeypatch.setitem(__import__("sys").modules, "holodori_asset_tools", fake_package)
    monkeypatch.setattr(cli.importlib.util, "find_spec", lambda name: object())

    calls = []

    def fake_upstream(*args):
        calls.append(args[0])
        import re
        pattern = args[args.index("--filter") + 1]
        assert all(re.fullmatch(pattern, name) for name in selected)
        raw = cache / "raw" / "assetbundles"
        raw.mkdir(parents=True)
        for name in selected:
            (raw / name).write_bytes(b"synthetic bundle")

    def fake_extract(source, destination):
        calls.append("extract")
        name = source.name
        folder = destination / name
        folder.mkdir(parents=True)
        if name == model_name:
            (folder / "model.json").write_text(
                json.dumps({"m_Name": "04016_004", "_bytes": list(b"MOC3synthetic")}),
                encoding="utf-8",
            )
            (folder / "texture.png").write_bytes(b"synthetic PNG bytes")
        elif name == thumbnail_name:
            from PIL import Image
            Image.new("RGBA", (8, 8), (255, 0, 0, 255)).save(folder / (name + ".png"))
        else:
            (folder / f"{name}.json").write_text(
                json.dumps(
                    {
                        "Type": "Live2D Expression",
                        "FadeInTime": 0.2,
                        "FadeOutTime": 0.3,
                        "Parameters": [
                            {"Id": "ParamAngleX", "Value": 0.5, "Blend": 1}
                        ],
                    }
                ),
                encoding="utf-8",
            )

    monkeypatch.setattr(cli, "_run_upstream", fake_upstream)
    monkeypatch.setattr(cli, "_extract_bundle", fake_extract)
    result = cli.prepare(
        card_id,
        output_name=output_name,
        model_name=model_title,
        card_info={"card_id": card_id, "card_name": model_title} if model_title else None,
        output_root=tmp_path / "output",
        cache_root=cache,
        catalog_path=None if with_thumbnail else cache / "octo_list.json",
        motion_level=None,
    )
    model = json.loads(Path(result["model"]).read_text(encoding="utf-8"))
    texture_ref = model["FileReferences"]["Textures"][0]
    basename = model_title or "04016_004"
    assert texture_ref == f"{basename}.4096/texture.png"
    assert Path(result["model"]).name == f"{basename}.model3.json"
    assert (Path(result["output_dir"]) / model["FileReferences"]["Moc"]).read_bytes() == b"MOC3synthetic"
    if model_title:
        assert cli.export_owner(Path(result["output_dir"])) == card_id
    assert (Path(result["output_dir"]) / texture_ref).read_bytes() == b"synthetic PNG bytes"
    assert result["expressions"] == 1
    assert result["motions"] == 0
    if output_name is not None:
        assert result["card_id"] == card_id
        assert result["output_name"] == output_name
    assert calls == ["download", "extract", "extract"] + (["extract"] if with_thumbnail else [])
    icon = Path(result["output_dir"]) / "icon.jpg"
    assert icon.is_file() == with_thumbnail
    if with_thumbnail:
        from PIL import Image
        assert result["icon"] == str(icon)
        assert result["icon_asset"] == thumbnail_name
        with Image.open(icon) as image:
            assert image.format == "JPEG" and image.size == (8, 8)
    else:
        assert "icon" not in result
    vtube_file = Path(result["vtube"])
    assert vtube_file == Path(result["output_dir"]) / f"{basename}.vtube.json"
    vtube = json.loads(vtube_file.read_text(encoding="utf-8"))
    assert vtube == {
        "Version": 1, "Name": basename, "ModelID": "",
        "FileReferences": {
            "Icon": "icon.jpg" if with_thumbnail else "",
            "Model": f"{basename}.model3.json",
            "IdleAnimation": "", "IdleAnimationWhenTrackingLost": "",
        },
    }
    info = json.loads((Path(result["output_dir"]) / ".holodori-model.json").read_text(encoding="utf-8"))
    assert f"{basename}.model3.json" in info["files"] and "files" not in result
    assert f"{basename}.vtube.json" not in info["files"]  # User settings are never cleaned up.
    folder_name = output_name or "live2d_04016-uniq-0079-00"
    assert Path(result["output_dir"]).name == folder_name
    assert Path(result["zip"]).name == folder_name + ".zip"
    with zipfile.ZipFile(result["zip"]) as archive:
        assert archive.testzip() is None
        assert f"{folder_name}/{basename}.model3.json" in archive.namelist()
        assert (f"{folder_name}/icon.jpg" in archive.namelist()) == with_thumbnail
        assert json.loads(archive.read(f"{folder_name}/{basename}.vtube.json")) == vtube


def test_batch_accepts_spaces_and_continues_after_errors(tmp_path, monkeypatch):
    batch = tmp_path / "cards.txt"
    batch.write_text(
        "# 卡牌 ID 与保存文件夹名\n"
        "04016-5-uniq-0079-00 Fubuki Live2D v1.0\n"
        "bad This row fails\n"
        "04016-5-uniq-0080-00 Another Model #1\n",
        encoding="utf-8-sig",
    )
    calls = []

    def fake_prepare(card_id, **options):
        calls.append((card_id, options["output_name"]))
        return {"asset_id": cli.model_id_from_input(card_id)[0]}

    monkeypatch.setattr(cli, "prepare", fake_prepare)
    result = cli.prepare_batch(batch, make_zip=False)
    assert result["total"] == 3
    assert result["succeeded"] == 2
    assert result["failed"] == 1
    assert [item["status"] for item in result["results"]] == ["ok", "error", "ok"]
    assert [item["line"] for item in result["results"]] == [2, 3, 4]
    assert calls == [
        ("04016-5-uniq-0079-00", "Fubuki Live2D v1.0"),
        ("04016-5-uniq-0080-00", "Another Model #1"),
    ]


def test_batch_accepts_live2d_resource_names(tmp_path, monkeypatch):
    batch = tmp_path / "batch.txt"
    batch.write_text(
        "live2d_mdl_00009-nrml-0009-00 live2d_00009-nrml-0009-00\n"
        "live2d_mdl_00024-nrml-0020-00 live2d_00024-nrml-0020-00\n",
        encoding="utf-8",
    )
    calls = []
    monkeypatch.setattr(
        cli, "prepare", lambda asset_id, **options: calls.append(
            (asset_id, options["output_name"])
        ) or {},
    )
    result = cli.prepare_batch(batch)
    assert result["failed"] == 0
    assert calls == [
        ("live2d_mdl_00009-nrml-0009-00", "live2d_00009-nrml-0009-00"),
        ("live2d_mdl_00024-nrml-0020-00", "live2d_00024-nrml-0020-00"),
    ]


@pytest.mark.parametrize(
    "card_id,folder",
    [
        ("bad", "Some Model"),
        ("04016-5-uniq-0079-00", "../bad"),
        ("04016-5-uniq-0079-00", "A/B"),
        ("04016-5-uniq-0079-00", "CON"),
        ("04016-5-uniq-0079-00", "Some Model."),
        ("04016-5-uniq-0079-00", "A:Model"),
    ],
)
def test_batch_rejects_invalid_pairs(card_id, folder):
    with pytest.raises(ValueError):
        cli._batch_entry(card_id, folder)


def test_batch_rejects_duplicate_output_names(tmp_path, monkeypatch):
    batch = tmp_path / "cards.txt"
    batch.write_text(
        "04016-5-uniq-0079-00 Shared Model\n"
        "04016-5-uniq-0080-00 shared model\n",
        encoding="utf-8",
    )
    calls = []
    monkeypatch.setattr(
        cli, "prepare", lambda card_id, **options: calls.append(card_id) or {}
    )
    result = cli.prepare_batch(batch)
    assert result["failed"] == 1
    assert calls == ["04016-5-uniq-0079-00"]


def test_batch_cli_returns_failure_exit_code(tmp_path, monkeypatch, capsys):
    batch = tmp_path / "cards.txt"
    batch.write_text("invalid record\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["holodori-l2d", "--batch", str(batch)])
    monkeypatch.setattr(cli, "prepare", lambda *args, **kwargs: {"asset_id": "ignored"})
    with pytest.raises(SystemExit) as exit_info:
        cli.main()
    assert exit_info.value.code == 1
    assert '"failed": 1' in capsys.readouterr().out


def test_remove_stale_only_deletes_previously_generated_files(tmp_path):
    folder = tmp_path / "model"
    (folder / "motions").mkdir(parents=True)
    (folder / "motions" / "old.motion3.json").write_text("{}")
    (folder / "model.moc3").write_bytes(b"MOC3")
    (folder / "user-notes.txt").write_text("keep")
    (folder / "model.vtube.json").write_text("{}")
    (tmp_path / "outside.txt").write_text("keep")
    (folder / ".holodori-model.json").write_text(json.dumps({"files": [
        "model.moc3", "motions/old.motion3.json", "../outside.txt"]}))
    assert cli._remove_stale(folder, ["model.moc3"]) == ["../outside.txt", "motions/old.motion3.json"]
    assert not (folder / "motions").exists()  # Emptied generated folders are removed too.
    assert (folder / "model.moc3").exists() and (folder / "user-notes.txt").exists()
    assert (folder / "model.vtube.json").exists() and (tmp_path / "outside.txt").exists()
    # Exports from older versions carry no file list, so nothing is removed.
    (folder / ".holodori-model.json").write_text(json.dumps({"card_id": "card-x"}))
    assert cli._remove_stale(folder, []) == []


def test_download_skips_cached_bundles(tmp_path, monkeypatch):
    raw = tmp_path / "raw" / "assetbundles"
    raw.mkdir(parents=True)
    (raw / "cached").write_bytes(b"bundle")
    calls = []

    def upstream(*args):
        calls.append(args[args.index("--filter") + 1])
        (raw / "missing").write_bytes(b"bundle")

    monkeypatch.setattr(cli, "_run_upstream", upstream)
    cli._download(tmp_path, tmp_path / "catalog.json", ["cached"])
    assert calls == []
    cli._download(tmp_path, tmp_path / "catalog.json", ["cached", "missing"])
    assert calls == ["^(?:missing)$"]


def test_prefetch_downloads_several_models_in_one_call(tmp_path, monkeypatch, capsys):
    names = ["live2d_mdl_00001-uniq-0001-00", "live2d_mdl_00002-uniq-0002-00",
             "live2d_exp_smile_00001_000", "live2d_mot_idle-01_lv05",
             "img_card_live_thumb_00001-5-uniq-0001-00"]
    (tmp_path / "octo_list.json").write_text(json.dumps({"assetBundles": [{"name": n} for n in names]}))
    package = types.ModuleType("holodori_asset_tools")
    refreshed = []
    package.catalog = types.SimpleNamespace(
        get=lambda path: None,
        fetch=lambda: types.SimpleNamespace(save=lambda path: refreshed.append(path)),
    )
    monkeypatch.setitem(sys.modules, "holodori_asset_tools", package)
    monkeypatch.setattr(cli.importlib.util, "find_spec", lambda name: object())
    patterns = []

    def upstream(*args):
        patterns.append(args[args.index("--filter") + 1])
        raise RuntimeError("network down")

    monkeypatch.setattr(cli, "_run_upstream", upstream)
    models = [(names[0], "card-00001-5-uniq-0001-00"), (names[1], None),
              ("live2d_mdl_00009-uniq-0009-00", None)]  # Not in the catalog: left to prepare.
    cli.prefetch(models, cache_root=tmp_path, motion_level="lv05")
    assert refreshed == [tmp_path / "octo_list.json"]  # Unknown model: catalog refreshed once.
    assert len(patterns) == 1
    assert all(re.fullmatch(patterns[0], name) for name in names)
    assert "00009" not in patterns[0]
    assert "network down" in capsys.readouterr().out  # Reported, not raised.
    cli.prefetch(models[:1], cache_root=tmp_path)
    assert len(patterns) == 1  # A single model needs no separate prefetch.
