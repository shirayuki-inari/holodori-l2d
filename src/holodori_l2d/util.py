"""Shared filesystem, path and reporting helpers."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unicodedata
import zipfile
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path


def _width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def _clip(text: str, columns: int) -> str:
    if _width(text) <= columns:
        return text
    while text and _width(text) > columns - 1:
        text = text[:-1]
    return text + "…"


class StatusLine:
    """One terminal line rewritten in place for progress; finished lines are kept.

    When stdout is not a terminal, progress updates are dropped and only
    finished lines are printed, so logs and pipes stay clean.
    """

    def __init__(self) -> None:
        self.prefix = ""
        self._shown = 0

    @staticmethod
    def _stream():
        return sys.stdout

    def _live(self) -> bool:
        try:
            return self._stream().isatty()
        except (AttributeError, ValueError):
            return False

    def update(self, text: str) -> None:
        if not self._live():
            return
        text = _clip(self.prefix + text, shutil.get_terminal_size().columns - 1)
        width = _width(text)
        self._stream().write("\r" + text + " " * max(self._shown - width, 0))
        self._stream().flush()
        self._shown = width

    def clear(self) -> None:
        if self._shown and self._live():
            self._stream().write("\r" + " " * self._shown + "\r")
            self._stream().flush()
        self._shown = 0

    def print(self, text: str = "") -> None:
        """Replace the progress line with a permanent one."""
        self.clear()
        print(text, file=self._stream(), flush=True)

    @contextmanager
    def scope(self, prefix: str) -> Iterator[None]:
        """Show ``prefix`` before every update made inside the block."""
        old, self.prefix = self.prefix, prefix + "  "
        try:
            yield
        finally:
            self.prefix = old
            self.clear()


status = StatusLine()


def format_size(size: int) -> str:
    return f"{size / 1024 / 1024:.1f} MB"


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


def display_path(path: str | Path) -> str:
    """Show paths under the working directory relative to it, others in full."""
    path = Path(path)
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def report_item(label: str, item: dict) -> None:
    """Print one finished download as a single line."""
    if item["status"] == "ok":
        result = item.get("result") or {}
        notes = "；".join(result.get("notes", []))
        where = display_path(result["output_dir"]) if "output_dir" in result else ""
        status.print(f"{label}  已保存 {where}" + (f"（{notes}）" if notes else ""))
    else:
        status.print(f"{label}  失败：{item['error']}")


def report_summary(summary: dict) -> None:
    if summary["total"] > 1:
        status.print(f"完成：成功 {summary['succeeded']}，失败 {summary['failed']}。")
