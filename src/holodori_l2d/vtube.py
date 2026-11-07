"""Create minimal VTube Studio metadata without replacing user settings."""

from __future__ import annotations

from pathlib import Path

from .naming import validate_name
from .util import json_bytes, write_atomic


def ensure_config(model_file: Path) -> Path:
    if not model_file.name.endswith(".model3.json") or not model_file.is_file():
        raise ValueError(f"找不到有效的模型文件：{model_file}")
    name = model_file.name.removesuffix(".model3.json")
    validate_name(name)
    destination = model_file.with_name(name + ".vtube.json")
    if destination.exists():
        if not destination.is_file():
            raise ValueError(f"VTube Studio 配置路径不是文件：{destination}")
        print(f"已保留现有 VTube Studio 配置：{destination}", flush=True)
        return destination
    config = {
        "Version": 1,
        "Name": name,
        "ModelID": "",
        "FileReferences": {
            "Icon": "icon.jpg" if (model_file.parent / "icon.jpg").is_file() else "",
            "Model": model_file.name,
            "IdleAnimation": "",
            "IdleAnimationWhenTrackingLost": "",
        },
    }
    write_atomic(destination, json_bytes(config))
    return destination
