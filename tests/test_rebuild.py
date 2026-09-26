import json
import struct
import sys
import types
import zlib
from pathlib import Path

import pytest

from holodori_l2d.rebuild import _motion_json, _streamed_frames, rebuild


def test_streamed_frames_decode_float32_keys():
    raw = struct.pack("<fiiffff", 0.0, 1, 0, 0.0, 0.0, 1.0, 0.25)
    words = list(struct.unpack(f"<{len(raw) // 4}I", raw))
    frames = _streamed_frames(words)
    assert frames[0][0] == 0.0
    assert frames[0][1][0][0] == 0.25


def test_motion_conversion_from_synthetic_unity_clip(tmp_path, monkeypatch):
    path = tmp_path / "live2d_mot_idle-01_lv05_lp"
    path.write_bytes(b"synthetic bundle")
    raw = b"".join(
        [
            struct.pack("<fiiffff", 0.0, 1, 0, 0.0, 0.0, 1.0, 0.0),
            struct.pack("<fiiffff", 1.0, 1, 0, 0.0, 0.0, 0.0, 1.0),
        ]
    )
    clip = {
        "m_Name": path.name,
        "m_SampleRate": 30.0,
        "m_ClipBindingConstant": {
            "genericBindings": [
                {"path": zlib.crc32(b"Parameters/ParamAngleX")}
            ]
        },
        "m_MuscleClip": {
            "m_StartTime": 0.0,
            "m_StopTime": 1.0,
            "m_LoopTime": True,
            "m_Clip": {
                "data": {
                    "m_StreamedClip": {
                        "data": list(struct.unpack(f"<{len(raw) // 4}I", raw)),
                        "curveCount": 1,
                    },
                    "m_DenseClip": {
                        "m_CurveCount": 0,
                        "m_BeginTime": 0.0,
                        "m_SampleRate": 30.0,
                        "m_FrameCount": 0,
                        "m_SampleArray": [],
                    },
                    "m_ConstantClip": {"data": []},
                }
            },
        },
    }
    define = {
        "baseAnimation": {
            "bindings": [{"path": "Parameters/ParamAngleX", "name": "ParamAngleX"}]
        }
    }

    class FakeObject:
        def __init__(self, name, data):
            self.type = types.SimpleNamespace(name=name)
            self.data = data

        def read_typetree(self):
            return self.data

    env = types.SimpleNamespace(
        objects=[FakeObject("AnimationClip", clip), FakeObject("MonoBehaviour", define)]
    )
    fake_unity = types.ModuleType("UnityPy")
    fake_unity.config = types.SimpleNamespace(FALLBACK_UNITY_VERSION=None)
    fake_unity.load = lambda data: env
    fake_package = types.ModuleType("holodori_asset_tools")
    fake_package.crypto = types.SimpleNamespace(decrypt=lambda data, name: data)
    monkeypatch.setitem(sys.modules, "UnityPy", fake_unity)
    monkeypatch.setitem(sys.modules, "holodori_asset_tools", fake_package)

    name, motion = _motion_json(path)
    assert name == path.name
    assert motion["Meta"]["CurveCount"] == 1
    assert motion["Meta"]["Loop"] is True
    assert motion["Curves"][0]["Id"] == "ParamAngleX"
    assert motion["Curves"][0]["Segments"] == [
        0.0, 0.0, 1, 0.33333, 0.33333, 0.66667, 0.66667, 1.0, 1.0
    ]


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
