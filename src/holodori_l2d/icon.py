"""Resolve game card thumbnails and export a real JPEG model icon."""

from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path

from .master import write_atomic


THUMB_PREFIX = "img_card_live_thumb_"
CARD_ASSET = re.compile(r"\d{5}-\d+-[a-z0-9]+-\d{4}-\d{2}")
MODEL_ASSET = re.compile(r"(\d{5})-([a-z0-9]+-\d{4}-\d{2})")


def card_thumbnail_name(value: str | None) -> str | None:
    if value is not None:
        card_id = value.removeprefix("card-")
        if CARD_ASSET.fullmatch(card_id):
            return THUMB_PREFIX + card_id
    return None


def select_thumbnail(names: set[str], value: str | None) -> str | None:
    """Prefer the exact card; never substitute another card for an explicit ID."""
    exact = card_thumbnail_name(value)
    if exact is not None:
        return exact if exact in names else None
    model = MODEL_ASSET.fullmatch((value or "").removeprefix("live2d_mdl_"))
    if model is None:
        return None
    pattern = re.compile(rf"{THUMB_PREFIX}{model[1]}-\d+-{re.escape(model[2])}")
    matches = sorted(name for name in names if pattern.fullmatch(name))
    return matches[0] if len(matches) == 1 else None


def save_icon(thumbnail_dir: Path, output_dir: Path, *, force: bool = False) -> Path:
    from PIL import Image

    source = thumbnail_dir / (thumbnail_dir.name + ".png")
    if not source.is_file():
        images = sorted(thumbnail_dir.glob("*.png"))
        if len(images) != 1:
            raise ValueError(f"卡牌缩略图应包含一张可识别的图片：{thumbnail_dir.name}")
        source = images[0]
    with Image.open(source) as image:
        rgba = image.convert("RGBA")
        # JPEG has no transparency: composite onto white rather than discard alpha.
        rgb = Image.new("RGB", rgba.size, "white")
        rgb.paste(rgba, mask=rgba.getchannel("A"))
        buffer = BytesIO()
        rgb.save(buffer, format="JPEG", quality=95, subsampling=0)
    destination = output_dir / "icon.jpg"
    data = buffer.getvalue()
    if destination.exists() and destination.read_bytes() != data and not force:
        raise ValueError(f"输出文件已存在且内容不同（可使用 --force）：{destination}")
    write_atomic(destination, data)
    return destination
