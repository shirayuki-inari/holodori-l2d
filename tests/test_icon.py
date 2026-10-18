import json
import re
import types

import pytest
from PIL import Image

from holodori_l2d import cli, icon


def test_thumbnail_resolution_is_exact_and_unambiguous():
    names = {"img_card_live_thumb_00001-4-cmmn-0000-00",
             "img_card_live_thumb_00001-5-uniq-0099-00",
             "img_card_live_thumb_00001-4-uniq-0099-00"}
    assert icon.select_thumbnail(names, "card-00001-5-uniq-0099-00") == "img_card_live_thumb_00001-5-uniq-0099-00"
    assert icon.select_thumbnail(names, "00001-4-cmmn-0000-00") == "img_card_live_thumb_00001-4-cmmn-0000-00"
    assert icon.select_thumbnail(names, "live2d_mdl_00001-cmmn-0000-00") == "img_card_live_thumb_00001-4-cmmn-0000-00"
    assert icon.select_thumbnail(names, "00001-cmmn-0000-00") == "img_card_live_thumb_00001-4-cmmn-0000-00"
    assert icon.select_thumbnail(names, "00001-uniq-0099-00") is None  # Ambiguous rarity.
    assert icon.select_thumbnail(names, "card-00001-3-cmmn-0000-00") is None  # Never another card.
    assert icon.select_thumbnail(names, "00001-nrml-0001-00") is None
    assert icon.select_thumbnail(names, None) is None  # A known no-card costume.
    assert icon.select_thumbnail(names, "../00001-cmmn-0000-00") is None


def test_save_icon_jpeg_transparency_and_overwrite(tmp_path):
    thumbnail = tmp_path / "img_card_live_thumb_test"
    thumbnail.mkdir()
    source = thumbnail / (thumbnail.name + ".png")
    Image.new("RGBA", (16, 16), (255, 0, 0, 0)).save(source)
    output = tmp_path / "模型"
    destination = icon.save_icon(thumbnail, output)
    assert destination == output / "icon.jpg"
    with Image.open(destination) as image:
        assert image.format == "JPEG" and image.mode == "RGB" and image.size == (16, 16)
        assert image.getpixel((0, 0)) == (255, 255, 255)
    original = destination.read_bytes()
    assert icon.save_icon(thumbnail, output).read_bytes() == original
    Image.new("RGB", (16, 16), "red").save(source)
    with pytest.raises(ValueError, match="--force"):
        icon.save_icon(thumbnail, output)
    assert destination.read_bytes() == original
    assert icon.save_icon(thumbnail, output, force=True).read_bytes() != original


def test_save_icon_missing_ambiguous_and_invalid_images(tmp_path):
    thumbnail = tmp_path / "thumbnail"
    thumbnail.mkdir()
    output = tmp_path / "model"
    with pytest.raises(ValueError, match="缩略图"):
        icon.save_icon(thumbnail, output)
    (thumbnail / "a.png").write_bytes(b"not an image")
    with pytest.raises(OSError):
        icon.save_icon(thumbnail, output)
    assert not (output / "icon.jpg").exists()
    Image.new("RGB", (2, 2)).save(thumbnail / "a.png")
    assert icon.save_icon(thumbnail, output).is_file()  # Unique fallback filename.
    Image.new("RGB", (2, 2)).save(thumbnail / "b.png")
    with pytest.raises(ValueError, match="缩略图"):
        icon.save_icon(thumbnail, output)


def test_missing_exact_thumbnail_refreshes_default_catalog(tmp_path, monkeypatch):
    model = "live2d_mdl_00001-uniq-0001-00"
    thumbnail = "img_card_live_thumb_00001-5-uniq-0001-00"
    catalog = tmp_path / "octo_list.json"
    catalog.write_text(json.dumps({"assetBundles": [{"name": model}]}), encoding="utf-8")
    calls = []

    def save(path):
        calls.append("refresh")
        path.write_text(json.dumps({"assetBundles": [{"name": model}, {"name": thumbnail}]}), encoding="utf-8")

    import sys
    package = types.ModuleType("holodori_asset_tools")
    package.catalog = types.SimpleNamespace(get=lambda path: None, fetch=lambda: types.SimpleNamespace(save=save))
    monkeypatch.setitem(sys.modules, "holodori_asset_tools", package)
    monkeypatch.setattr(cli.importlib.util, "find_spec", lambda name: object())

    def download(*args, **kwargs):
        assert re.fullmatch(args[args.index("--filter") + 1], thumbnail)
        calls.append("download")
        raw = tmp_path / "raw" / "assetbundles"
        raw.mkdir(parents=True)
        (raw / model).write_bytes(b"synthetic bundle")
        # Leave only the thumbnail missing: a failed thumbnail download is reported.

    monkeypatch.setattr(cli, "_run_upstream", download)
    with pytest.raises(RuntimeError, match=f"下载后仍缺少资源：{thumbnail}"):
        cli.prepare("00001-5-uniq-0001-00", cache_root=tmp_path, motion_level=None)
    assert calls == ["refresh", "download"]


@pytest.mark.parametrize("card_id,expected", [
    ("card-00001-5-uniq-0099-00", "img_card_live_thumb_00001-5-uniq-0099-00"),
    (None, None),
])
def test_card_metadata_beats_model_filename(tmp_path, monkeypatch, card_id, expected):
    import sys

    model = "live2d_mdl_00001-uniq-0001-00"
    thumbnails = ["img_card_live_thumb_00001-5-uniq-0001-00", "img_card_live_thumb_00001-5-uniq-0099-00"]
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"assetBundles": [{"name": name} for name in [model, *thumbnails]]}), encoding="utf-8")
    package = types.ModuleType("holodori_asset_tools")
    package.catalog = types.SimpleNamespace(get=lambda path: None)
    monkeypatch.setitem(sys.modules, "holodori_asset_tools", package)
    monkeypatch.setattr(cli.importlib.util, "find_spec", lambda name: object())
    selected = []

    def download(*args, **kwargs):
        pattern = args[args.index("--filter") + 1]
        selected.extend(name for name in thumbnails if re.fullmatch(pattern, name))

    monkeypatch.setattr(cli, "_run_upstream", download)
    with pytest.raises(RuntimeError, match="下载后仍缺少资源"):
        cli.prepare(model, card_info={"card_id": card_id}, cache_root=tmp_path,
                    output_root=tmp_path / "output", catalog_path=catalog, motion_level=None)
    assert selected == ([expected] if expected else [])
