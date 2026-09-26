"""Rebuild a Cubism preview package from holodori-asset-tools' extracted files.

MOC3 and textures are copied; physics and expressions are converted to Cubism
JSON. Unity AnimationClips are reconstructed as approximate motion3.json files.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import struct
import warnings
import zlib
from pathlib import Path


BLENDS = {0: "Overwrite", 1: "Add", 2: "Multiply"}
COMPONENTS = {0: "X", 1: "Y", 2: "Angle"}


def _write(path: Path, data: bytes, *, force: bool) -> None:
    if path.exists() and not force and path.read_bytes() != data:
        raise ValueError(f"输出文件已存在且内容不同（可使用 --force）：{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_bytes() != data:
        path.write_bytes(data)


def _write_json(path: Path, value: object, *, force: bool) -> None:
    data = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _write(path, data, force=force)


def _vector(value: dict[str, float]) -> dict[str, float]:
    return {"X": value["x"], "Y": value["y"]}


def _physics_json(rig: dict) -> dict:
    subrigs = rig["SubRigs"]
    settings = []
    dictionary = []
    for index, subrig in enumerate(subrigs, 1):
        setting_id = f"PhysicsSetting{index}"
        name = subrig.get("Name") or setting_id
        if "\ufffd" in name:
            name = setting_id  # UnityPy could not decode the original label.
        dictionary.append({"Id": setting_id, "Name": name})
        inputs = [
            {
                "Source": {"Target": "Parameter", "Id": item["SourceId"]},
                "Weight": item["Weight"],
                "Type": COMPONENTS[item["SourceComponent"]],
                "Reflect": bool(item["IsInverted"]),
            }
            for item in subrig["Input"]
        ]
        outputs = []
        for item in subrig["Output"]:
            component = COMPONENTS[item["SourceComponent"]]
            scale = (
                item["AngleScale"]
                if component == "Angle"
                else item["TranslationScale"][component.lower()]
            )
            outputs.append(
                {
                    "Destination": {
                        "Target": "Parameter",
                        "Id": item["DestinationId"],
                    },
                    "VertexIndex": item["ParticleIndex"],
                    "Scale": scale,
                    "Weight": item["Weight"],
                    "Type": component,
                    "Reflect": bool(item["IsInverted"]),
                }
            )
        vertices = [
            {
                "Position": _vector(item["InitialPosition"]),
                "Mobility": item["Mobility"],
                "Delay": item["Delay"],
                "Acceleration": item["Acceleration"],
                "Radius": item["Radius"],
            }
            for item in subrig["Particles"]
        ]
        settings.append(
            {
                "Id": setting_id,
                "Input": inputs,
                "Output": outputs,
                "Vertices": vertices,
                "Normalization": subrig["Normalization"],
            }
        )
    return {
        "Version": 3,
        "Meta": {
            "PhysicsSettingCount": len(subrigs),
            "TotalInputCount": sum(len(x["Input"]) for x in subrigs),
            "TotalOutputCount": sum(len(x["Output"]) for x in subrigs),
            "VertexCount": sum(len(x["Particles"]) for x in subrigs),
            "EffectiveForces": {
                "Gravity": _vector(rig["Gravity"]),
                "Wind": _vector(rig["Wind"]),
            },
            "PhysicsDictionary": dictionary,
            "Fps": rig["Fps"],
        },
        "PhysicsSettings": settings,
    }


def _streamed_frames(words: list[int]) -> list[tuple[float, dict[int, tuple[float, tuple[float, ...]]]]]:
    """Read Unity's streamed keyframes from their little-endian uint32 words."""
    raw = struct.pack(f"<{len(words)}I", *words)
    position = 0
    frames = []
    while position < len(raw):
        time, count = struct.unpack_from("<fi", raw, position)
        position += 8
        keys = {}
        for _ in range(count):
            index, *coefficients = struct.unpack_from("<iffff", raw, position)
            position += 20
            keys[index] = (coefficients[3], tuple(coefficients))
        if math.isfinite(time):  # Unity adds -FLT_MAX and +INF sentinels.
            frames.append((time, keys))
    return frames


def _motion_json(bundle_path: Path) -> tuple[str, dict]:
    """Convert a Unity Cubism AnimationClip's parameter curves to motion3.json."""
    import UnityPy
    from holodori_asset_tools import crypto

    UnityPy.config.FALLBACK_UNITY_VERSION = "6000.3.15f1"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        env = UnityPy.load(crypto.decrypt(bundle_path.read_bytes(), bundle_path.name))
    clip = next((obj.read_typetree() for obj in env.objects if obj.type.name == "AnimationClip"), None)
    define = next(
        (
            data
            for obj in env.objects
            if obj.type.name == "MonoBehaviour"
            if (data := obj.read_typetree()).get("baseAnimation", {}).get("bindings")
        ),
        None,
    )
    if clip is None or define is None:
        raise ValueError(f"动作包缺少 AnimationClip 或参数映射：{bundle_path}")
    path_to_name = {
        zlib.crc32(binding["path"].encode("utf-8")): binding["name"]
        for binding in define["baseAnimation"]["bindings"]
        if binding["path"].startswith("Parameters/")
    }
    bindings = clip["m_ClipBindingConstant"]["genericBindings"]
    muscle = clip["m_MuscleClip"]
    data = muscle["m_Clip"]["data"]
    streamed = data["m_StreamedClip"]
    dense = data["m_DenseClip"]
    constants = data["m_ConstantClip"]["data"]
    duration = muscle["m_StopTime"] - muscle["m_StartTime"]
    if duration <= 0:
        raise ValueError(f"动作时长无效：{bundle_path}")
    keys_by_index: dict[int, list[tuple[float, float, tuple[float, ...]]]] = {}
    for time, keys in _streamed_frames(streamed["data"]):
        for index, (value, coefficients) in keys.items():
            keys_by_index.setdefault(index, []).append((time, value, coefficients))

    # Unity stores dense curves as consecutive samples, and constants after
    # streamed+dense binding indices. Most Holodori clips use all three kinds.
    dense_count = dense["m_CurveCount"]
    for index in range(dense_count):
        samples = [
            (
                dense["m_BeginTime"] + frame / dense["m_SampleRate"],
                dense["m_SampleArray"][frame * dense_count + index],
                None,
            )
            for frame in range(dense["m_FrameCount"])
        ]
        keys_by_index[streamed["curveCount"] + index] = samples
    for index, value in enumerate(constants):
        keys_by_index[streamed["curveCount"] + dense_count + index] = [
            (0.0, value, None),
            (duration, value, None),
        ]

    curves = []
    segment_count = 0
    point_count = 0
    for index, keyframes in sorted(keys_by_index.items()):
        if index >= len(bindings):
            raise ValueError(f"动作曲线索引超出绑定表：{index}")
        name = path_to_name.get(bindings[index]["path"])
        if name is None:
            raise ValueError(f"找不到动作参数名：{bundle_path.name} / {index}")
        keyframes = sorted((k for k in keyframes if 0 <= k[0] <= duration + 0.001), key=lambda k: k[0])
        if not keyframes:
            continue
        segments: list[float | int] = [keyframes[0][0], keyframes[0][1]]
        point_count += 1
        for left, right in zip(keyframes, keyframes[1:]):
            t0, v0, coeff = left
            t1, v1, _ = right
            dt = t1 - t0
            if dt <= 0:
                continue
            if coeff is None or (coeff[0] == coeff[1] == coeff[2] == 0):
                kind = 0 if coeff is None or v0 == v1 else 2
                segments.extend((kind, t1, v1))
                point_count += 1
            else:
                out_slope = coeff[2]
                inv_dt2 = 1.0 / (dt * dt)
                in_slope = (3 * (v1 - v0) - 2 * out_slope * dt - coeff[1] / inv_dt2) / dt
                control1 = v0 + out_slope * dt / 3
                control2 = v1 - in_slope * dt / 3
                if not all(math.isfinite(x) for x in (control1, control2)):
                    segments.extend((0, t1, v1))
                    point_count += 1
                else:
                    segments.extend(
                        (1, t0 + dt / 3, control1, t1 - dt / 3, control2, t1, v1)
                    )
                    point_count += 3
            segment_count += 1
        # Cubism's native JSON reader rejects tiny exponent-form numbers such
        # as 2e-09 even though standard JSON permits them.
        segments = [round(value, 5) if isinstance(value, float) else value for value in segments]
        curves.append({"Target": "Parameter", "Id": name, "Segments": segments})
    if not curves:
        raise ValueError(f"动作包没有可转换的参数曲线：{bundle_path}")
    motion = {
        "Version": 3,
        "Meta": {
            "Duration": duration,
            "Fps": clip["m_SampleRate"],
            "Loop": bool(muscle["m_LoopTime"]),
            "AreBeziersRestricted": True,
            "CurveCount": len(curves),
            "TotalSegmentCount": segment_count,
            "TotalPointCount": point_count,
            "UserDataCount": 0,
            "TotalUserDataSize": 0,
        },
        "Curves": curves,
    }
    return clip["m_Name"], motion


def rebuild(
    model_dir: Path,
    output_dir: Path,
    *,
    motion_bundles: list[Path] | None = None,
    motion_directory: Path | None = None,
    motion_pattern: str = "live2d_mot_*",
    force: bool = False,
) -> dict:
    if not model_dir.is_dir():
        raise ValueError(f"找不到已提取的模型目录：{model_dir}")
    match = re.fullmatch(r"live2d_mdl_(\d{5})-.+", model_dir.name)
    if not match:
        raise ValueError("模型目录名应为 live2d_mdl_<角色编号>-... 格式")
    char_id = match.group(1)

    model_source = None
    rig = None
    for path in model_dir.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        if "_bytes" in data and data["_bytes"][:4] == [77, 79, 67, 51]:
            if model_source is not None:
                raise ValueError("模型包内发现多个 MOC3，无法自动选择")
            model_source = data
        if "_rig" in data:
            rig = data["_rig"]
    if model_source is None:
        raise ValueError("模型包内未找到 MOC3 数据")
    model_name = model_source["m_Name"]
    if not re.fullmatch(r"[\w.-]+", model_name):
        raise ValueError(f"不安全的模型文件名：{model_name!r}")
    moc_name = model_name + ".moc3"
    _write(output_dir / moc_name, bytes(model_source["_bytes"]), force=force)

    textures = sorted(model_dir.glob("*.png"))
    if not textures:
        raise ValueError("模型包内未找到纹理 PNG")
    texture_folder = model_name + ".4096"
    for source in textures:
        destination = output_dir / texture_folder / source.name
        _write(destination, source.read_bytes(), force=force)

    references: dict[str, object] = {
        "Moc": moc_name,
        "Textures": [f"{texture_folder}/{path.name}" for path in textures],
    }
    if rig is not None:
        physics_name = model_name + ".physics3.json"
        _write_json(output_dir / physics_name, _physics_json(rig), force=force)
        references["Physics"] = physics_name

    expressions = []
    expression_ids = set()
    for folder in sorted(model_dir.parent.glob(f"live2d_exp_*_{char_id}_000")):
        source = folder / f"{folder.name}.json"
        if not source.is_file():
            continue
        data = json.loads(source.read_text(encoding="utf-8"))
        if data.get("Type") != "Live2D Expression":
            continue
        label = folder.name[len("live2d_exp_") : -len(f"_{char_id}_000")]
        target_name = label + ".exp3.json"
        params = [
            {"Id": x["Id"], "Value": x["Value"], "Blend": BLENDS[x["Blend"]]}
            for x in data["Parameters"]
        ]
        expression_ids.update(x["Id"] for x in params)
        converted = {
            "Type": "Live2D Expression",
            "FadeInTime": data["FadeInTime"],
            "FadeOutTime": data["FadeOutTime"],
            "Parameters": params,
        }
        _write_json(output_dir / "expressions" / target_name, converted, force=force)
        expressions.append({"Name": label, "File": "expressions/" + target_name})
    if expressions:
        references["Expressions"] = expressions

    motions: dict[str, list[dict]] = {}
    motion_sources = list(motion_bundles or [])
    if motion_directory is not None:
        motion_sources.extend(sorted(motion_directory.glob(motion_pattern)))
    for bundle in dict.fromkeys(motion_sources):
        motion_name, motion = _motion_json(bundle)
        if not re.fullmatch(r"[\w.-]+", motion_name):
            raise ValueError(f"不安全的动作文件名：{motion_name!r}")
        motion_file = motion_name + ".motion3.json"
        _write_json(output_dir / "motions" / motion_file, motion, force=force)
        group = (
            "Idle"
            if "_idle-" in motion_name
            else motion_name.removeprefix("live2d_mot_").split("-", 1)[0].capitalize()
        )
        motions.setdefault(group, []).append(
            {"File": "motions/" + motion_file, "FadeInTime": 0.5, "FadeOutTime": 0.5}
        )
    if motions:
        references["Motions"] = motions

    groups = []
    eye_ids = [x for x in ("ParamEyeLOpen", "ParamEyeROpen") if x in expression_ids]
    if eye_ids:
        groups.append({"Target": "Parameter", "Name": "EyeBlink", "Ids": eye_ids})
    if "ParamMouthOpenY" in expression_ids:
        groups.append(
            {"Target": "Parameter", "Name": "LipSync", "Ids": ["ParamMouthOpenY"]}
        )
    model_json = {
        "Version": 3,
        "FileReferences": references,
        "Groups": groups,
        "HitAreas": [],
    }
    model_json_path = output_dir / (model_name + ".model3.json")
    _write_json(model_json_path, model_json, force=force)
    return {
        "model": str(model_json_path),
        "textures": len(textures),
        "physics_groups": len(rig["SubRigs"]) if rig is not None else 0,
        "expressions": len(expressions),
        "motions": sum(map(len, motions.values())),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_dir", type=Path, help="holodori extract 生成的 live2d_mdl_* 目录")
    parser.add_argument("-o", "--output-dir", type=Path, required=True)
    parser.add_argument(
        "--motion-bundle", type=Path, action="append", default=[],
        help="原始 live2d_mot_* Unity 包；可重复指定",
    )
    parser.add_argument("--motion-dir", type=Path, help="包含原始 live2d_mot_* Unity 包的目录")
    parser.add_argument(
        "--motion-pattern", default="live2d_mot_*",
        help="--motion-dir 下要转换的文件名模式；例如 live2d_mot_*_lv05*",
    )
    parser.add_argument("--force", action="store_true", help="覆盖输出目录中同名文件")
    args = parser.parse_args()
    summary = rebuild(
        args.model_dir,
        args.output_dir,
        motion_bundles=args.motion_bundle,
        motion_directory=args.motion_dir,
        motion_pattern=args.motion_pattern,
        force=args.force,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
