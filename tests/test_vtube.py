import json

from holodori_l2d import vtube


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
