import json

import pytest

from holodori_l2d import vtube


@pytest.mark.parametrize("name", ["卡牌♡模型 v1.0", "04016_004"])
@pytest.mark.parametrize("with_icon", [True, False])
def test_vtube_metadata_matches_actual_model_file(tmp_path, name, with_icon):
    model = tmp_path / (name + ".model3.json")
    model.write_text("{}", encoding="utf-8")
    if with_icon:
        (tmp_path / "icon.jpg").write_bytes(b"synthetic JPEG")
    result = vtube.ensure_config(model)
    assert result.name == name + ".vtube.json"
    config = json.loads(result.read_text(encoding="utf-8"))
    assert config["Version"] == 1 and config["Name"] == name and config["ModelID"] == ""
    assert config["FileReferences"] == {
        "Icon": "icon.jpg" if with_icon else "",
        "Model": model.name,
        "IdleAnimation": "", "IdleAnimationWhenTrackingLost": "",
    }
    original = result.read_bytes()
    assert vtube.ensure_config(model).read_bytes() == original


def test_existing_vtube_settings_are_never_replaced(tmp_path):
    model = tmp_path / "model.model3.json"
    model.write_text("{}", encoding="utf-8")
    config = tmp_path / "model.vtube.json"
    custom = {"Name": "用户模型名", "ModelID": "user-id", "FileReferences": {"Icon": "custom.png"},
              "Hotkeys": [{"Name": "用户热键"}], "ParameterSettings": {"Tracking": True}}
    config.write_text(json.dumps(custom, ensure_ascii=False), encoding="utf-8")
    original = config.read_bytes()
    (tmp_path / "icon.jpg").write_bytes(b"synthetic JPEG")
    assert vtube.ensure_config(model) == config
    assert config.read_bytes() == original


def test_invalid_model_and_occupied_config_path(tmp_path):
    model = tmp_path / "model.model3.json"
    with pytest.raises(ValueError, match="模型文件"):
        vtube.ensure_config(model)
    wrong = tmp_path / "other.json"
    wrong.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="模型文件"):
        vtube.ensure_config(wrong)
    model.write_text("{}", encoding="utf-8")
    (tmp_path / "model.vtube.json").mkdir()
    with pytest.raises(ValueError, match="不是文件"):
        vtube.ensure_config(model)
