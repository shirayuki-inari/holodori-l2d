"""Shared filesystem, path and reporting helpers."""

from __future__ import annotations

import json
import sys
import tempfile
import zipfile
from collections.abc import Iterable
from pathlib import Path


def cache_dir(root: Path | None = None) -> Path:
    return root or Path.cwd() / "input" / ".holodori_assets"


def output_dir(root: Path | None = None) -> Path:
    return root or Path.cwd() / "output"


def use_utf8_stdio() -> None:
    # PowerShell pipes expect UTF-8 even when Python inherited a legacy code page.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _temporary(directory: Path, suffix: str = "") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=".holodori-", suffix=suffix, dir=directory, delete=False) as file:
        return Path(file.name)


def write_atomic(path: Path, data: bytes) -> None:
    temporary = _temporary(path.parent)
    try:
        temporary.write_bytes(data)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def write_checked(path: Path, data: bytes, *, force: bool) -> Path:
    """Write ``data`` unless a different file already exists and ``force`` is off."""
    if path.exists():
        if path.read_bytes() == data:
            return path
        if not force:
            raise ValueError(f"输出文件已存在且内容不同（可使用 --force）：{path}")
    write_atomic(path, data)
    return path


def write_zip(destination: Path, folders: Iterable[Path], extra: dict[str, bytes] | None = None) -> Path:
    """Atomically archive each folder under its own name, plus extra root files."""
    temporary = _temporary(destination.parent, ".zip")
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in (extra or {}).items():
                archive.writestr(name, data)
            for folder in folders:
                for path in sorted(folder.rglob("*")):
                    if path.is_file():
                        archive.write(path, f"{folder.name}/{path.relative_to(folder).as_posix()}")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def summarize(results: list[dict]) -> dict:
    failed = sum(item["status"] == "error" for item in results)
    return {"total": len(results), "succeeded": len(results) - failed, "failed": failed, "results": results}
