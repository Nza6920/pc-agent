from __future__ import annotations

import base64
from pathlib import Path

import mss
from PIL import Image


def get_primary_resolution() -> tuple[int, int]:
    with mss.mss() as sct:
        mon = sct.monitors[1]
        return int(mon["width"]), int(mon["height"])


def capture_primary_image(
    path: str,
    image_format: str = "jpeg",
    max_long_edge: int = 1280,
    jpeg_quality: int = 70,
) -> str:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fmt = image_format.lower()
    if fmt not in {"jpeg", "png"}:
        raise ValueError("image_format must be jpeg or png")

    if fmt == "jpeg" and output.suffix.lower() not in {".jpg", ".jpeg"}:
        output = output.with_suffix(".jpg")
    if fmt == "png" and output.suffix.lower() != ".png":
        output = output.with_suffix(".png")

    with mss.mss() as sct:
        mon = sct.monitors[1]
        shot = sct.grab(mon)
        img = Image.frombytes("RGB", shot.size, shot.rgb)
        w, h = img.size
        long_edge = max(w, h)
        if long_edge > max_long_edge:
            scale = float(max_long_edge) / float(long_edge)
            new_size = (max(1, round(w * scale)), max(1, round(h * scale)))
            img = img.resize(new_size, Image.Resampling.LANCZOS)

        if fmt == "jpeg":
            img.save(str(output), format="JPEG", quality=jpeg_quality, optimize=True)
        else:
            img.save(str(output), format="PNG", optimize=True)
    return str(output)


def file_to_base64(path: str) -> str:
    data = Path(path).read_bytes()
    return base64.b64encode(data).decode("ascii")
