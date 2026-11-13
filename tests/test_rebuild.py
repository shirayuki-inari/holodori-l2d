import json
from pathlib import Path

import pytest

from holodori_l2d.rebuild import rebuild


def test_rebuild_keeps_texture_bytes_and_expressions(tmp_path):
    model_dir = tmp_path / "live2d_mdl_04016-uniq-0079-00"
    model_dir.mkdir()
    (model_dir / "model.json").write_text(
        json.dumps({"m_Name": "04016_004", "_bytes": list(b"MOC3synthetic")}),
        encoding="utf-8",
    )
    (model_dir / "texture.png").write_bytes(b"synthetic PNG bytes")
    expression_name = "live2d_exp_smile-01_04016_000"
    expression_dir = tmp_path / expression_name
    expression_dir.mkdir()
    (expression_dir / f"{expression_name}.json").write_text(
        json.dumps(
            {
                "Type": "Live2D Expression",
                "FadeInTime": 0.2,
                "FadeOutTime": 0.3,
                "Parameters": [{"Id": "ParamAngleX", "Value": 0.5, "Blend": 1}],
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "out"
    result = rebuild(model_dir, out)
    model = json.loads(Path(result["model"]).read_text(encoding="utf-8"))
    ref = model["FileReferences"]["Textures"][0]
    assert ref == "04016_004.4096/texture.png"
    assert (out / ref).read_bytes() == b"synthetic PNG bytes"
    assert (out / "04016_004.moc3").read_bytes() == b"MOC3synthetic"
    expression = json.loads((out / "expressions/smile-01.exp3.json").read_text(encoding="utf-8"))
    assert expression["Parameters"] == [
        {"Id": "ParamAngleX", "Value": 0.5, "Blend": "Add"}
    ]
    with pytest.raises(ValueError, match="--force"):
        (model_dir / "texture.png").write_bytes(b"changed")
        rebuild(model_dir, out)
