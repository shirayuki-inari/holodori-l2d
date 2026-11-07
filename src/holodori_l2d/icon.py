"""Resolve game card thumbnails and export a real JPEG model icon."""

from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path

from .naming import CARD_ID, MODEL_ID
from .util import write_checked


THUMB_PREFIX = "img_card_live_thumb_"


def card_thumbnail_name(value: str | None) -> str | None:
    card_id = (value or "").removeprefix("card-")
    return THUMB_PREFIX + card_id if CARD_ID.fullmatch(card_id) else None


def select_thumbnail(names: set[str], value: str | None) -> str | None:
    """Prefer the exact card; never substitute another card for an explicit ID."""
    exact = card_thumbnail_name(value)
    if exact is not None:
        return exact if exact in names else None
    model = MODEL_ID.fullmatch((value or "").removeprefix("live2d_mdl_"))
    if model is None:
        return None
    pattern = re.compile(rf"{THUMB_PREFIX}{model[1]}-\d+-{re.escape(model[2])}")
    matches = [name for name in names if pattern.fullmatch(name)]
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
    return write_checked(output_dir / "icon.jpg", buffer.getvalue(), force=force)
