import json
import sys
import types
import zipfile
from pathlib import Path

import pytest

from holodori_l2d import cli


def test_prepare_offline_with_synthetic_assets(tmp_path, monkeypatch):
    card_id, folder_name, title = "04016-5-uniq-0079-00", "中文卡牌♡（角色）", "中文卡牌♡"
    model_name = "live2d_mdl_04016-uniq-0079-00"
    expression_name = "live2d_exp_smile-01_04016_000"
    thumbnail_name = "img_card_live_thumb_04016-5-uniq-0079-00"
    selected = [model_name, expression_name, thumbnail_name]
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "octo_list.json").write_text(
        json.dumps({"assetBundles": [{"name": name} for name in selected]}), encoding="utf-8")
    package = types.ModuleType("holodori_asset_tools")
    package.catalog = types.SimpleNamespace(get=lambda path: None)
    monkeypatch.setitem(sys.modules, "holodori_asset_tools", package)
    monkeypatch.setattr(cli.importlib.util, "find_spec", lambda name: object())

    def fake_fetch(catalog, names, directory):
        assert sorted(names) == sorted(selected)
        directory.mkdir(parents=True)
        for name in names:
            (directory / name).write_bytes(b"synthetic bundle")

    def fake_extract(source, destination):
        folder = destination / source.name
        folder.mkdir(parents=True)
        if source.name == model_name:
            (folder / "model.json").write_text(
                json.dumps({"m_Name": "04016_004", "_bytes": list(b"MOC3synthetic")}), encoding="utf-8")
            (folder / "texture.png").write_bytes(b"synthetic PNG bytes")
        elif source.name == thumbnail_name:
            from PIL import Image
            Image.new("RGBA", (8, 8), (255, 0, 0, 255)).save(folder / (source.name + ".png"))
        else:
            (folder / f"{source.name}.json").write_text(json.dumps({
                "Type": "Live2D Expression", "FadeInTime": 0.2, "FadeOutTime": 0.3,
                "Parameters": [{"Id": "ParamAngleX", "Value": 0.5, "Blend": 1}],
            }), encoding="utf-8")

    monkeypatch.setattr(cli, "_fetch_bundles", fake_fetch)
    monkeypatch.setattr(cli, "_extract_bundle", fake_extract)
    result = cli.prepare(card_id, output_name=folder_name, model_name=title,
                         card_info={"card_id": card_id, "card_name": title},
                         output_root=tmp_path / "output", cache_root=cache, make_zip=True)
    out = Path(result["output_dir"])
    assert out.name == folder_name
    model = json.loads(Path(result["model"]).read_text(encoding="utf-8"))
    assert model["FileReferences"]["Textures"] == [f"{title}.4096/texture.png"]
    assert (out / f"{title}.4096/texture.png").read_bytes() == b"synthetic PNG bytes"
    assert (out / model["FileReferences"]["Moc"]).read_bytes() == b"MOC3synthetic"
    assert result["expressions"] == 1 and result["motions"] == 0
    assert cli.export_owner(out) == card_id
    vtube = json.loads(Path(result["vtube"]).read_text(encoding="utf-8"))
    assert vtube["FileReferences"]["Icon"] == "icon.jpg" and (out / "icon.jpg").is_file()
    info = json.loads((out / ".holodori-model.json").read_text(encoding="utf-8"))
    assert f"{title}.model3.json" in info["files"]
    assert f"{title}.vtube.json" not in info["files"]  # User settings are never cleaned up.
    with zipfile.ZipFile(result["zip"]) as archive:
        assert f"{folder_name}/{title}.model3.json" in archive.namelist()


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


def test_fetch_bundles_downloads_in_process_with_retry(tmp_path, monkeypatch):
    import httpx

    entries = [types.SimpleNamespace(name=name, url=f"https://cdn.test/{name}", size=4)
               for name in ("bundle_a", "bundle_b", "bundle_broken")]
    package = types.ModuleType("holodori_asset_tools")
    package.catalog = types.SimpleNamespace(
        Catalog=types.SimpleNamespace(load=lambda path: types.SimpleNamespace(assetBundles=entries)))
    package.crypto = types.SimpleNamespace(decrypt=lambda data, name: data.upper())
    monkeypatch.setitem(sys.modules, "holodori_asset_tools", package)
    attempts = []

    def handler(request):
        name = request.url.path.lstrip("/")
        attempts.append(name)
        if name == "bundle_broken" or attempts.count(name) == 1 and name == "bundle_b":
            return httpx.Response(503)  # bundle_b recovers on retry; bundle_broken never does.
        return httpx.Response(200, content=b"data")

    real_client = httpx.Client
    monkeypatch.setattr(cli.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler)))
    raw = tmp_path / "raw"
    cli._fetch_bundles(tmp_path / "catalog.json", ["bundle_a", "bundle_b"], raw, workers=2)
    assert (raw / "bundle_a").read_bytes() == (raw / "bundle_b").read_bytes() == b"DATA"
    assert attempts.count("bundle_b") == 2
    with pytest.raises(RuntimeError, match="下载失败：bundle_broken"):
        cli._fetch_bundles(tmp_path / "catalog.json", ["bundle_broken", "not_in_catalog"], raw)
    assert attempts.count("bundle_broken") == 3
    assert not (raw / "bundle_broken").exists()
