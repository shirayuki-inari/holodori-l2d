import json
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


@pytest.mark.parametrize(
    "card_id,output_name",
    [
        ("04016-5-uniq-0079-00", None),
        ("04016-5-uniq-0079-00", "Fubuki Live2D v1.0"),
    ],
)
def test_prepare_offline_with_synthetic_assets(
    tmp_path, monkeypatch, card_id, output_name
):
    model_name = "live2d_mdl_04016-uniq-0079-00"
    expression_name = "live2d_exp_smile-01_04016_000"
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "octo_list.json").write_text(
        json.dumps({"assetBundles": [{"name": model_name}, {"name": expression_name}]}),
        encoding="utf-8",
    )
    fake_catalog = types.SimpleNamespace(get=lambda path: None)
    fake_package = types.ModuleType("holodori_asset_tools")
    fake_package.catalog = fake_catalog
    monkeypatch.setitem(__import__("sys").modules, "holodori_asset_tools", fake_package)
    monkeypatch.setattr(cli.importlib.util, "find_spec", lambda name: object())

    calls = []

    def fake_upstream(*args, quiet=False):
        calls.append(args[0])
        if args[0] == "download":
            raw = cache / "raw" / "assetbundles"
            raw.mkdir(parents=True)
            for name in (model_name, expression_name):
                (raw / name).write_bytes(b"synthetic bundle")
        elif args[0] == "extract":
            name = Path(args[1]).name
            folder = Path(args[2]) / name
            folder.mkdir(parents=True)
            if name == model_name:
                (folder / "model.json").write_text(
                    json.dumps({"m_Name": "04016_004", "_bytes": list(b"MOC3synthetic")}),
                    encoding="utf-8",
                )
                (folder / "texture.png").write_bytes(b"synthetic PNG bytes")
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
    result = cli.prepare(
        card_id,
        output_name=output_name,
        output_root=tmp_path / "output",
        cache_root=cache,
        motion_level=None,
    )
    model = json.loads(Path(result["model"]).read_text(encoding="utf-8"))
    texture_ref = model["FileReferences"]["Textures"][0]
    assert texture_ref == "04016_004.4096/texture.png"
    assert (Path(result["output_dir"]) / texture_ref).read_bytes() == b"synthetic PNG bytes"
    assert result["expressions"] == 1
    assert result["motions"] == 0
    if output_name is not None:
        assert result["card_id"] == card_id
        assert result["output_name"] == output_name
    assert calls == ["download", "extract", "extract"]
    folder_name = output_name or "live2d_04016-uniq-0079-00"
    assert Path(result["output_dir"]).name == folder_name
    assert Path(result["zip"]).name == folder_name + ".zip"
    with zipfile.ZipFile(result["zip"]) as archive:
        assert archive.testzip() is None
        assert f"{folder_name}/04016_004.model3.json" in archive.namelist()


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
