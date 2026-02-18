from __future__ import annotations

import base64
import ctypes
from pathlib import Path
from typing import Any

import mss
import pyautogui
from PIL import Image


def enable_windows_dpi_awareness() -> None:
    if not hasattr(ctypes, "windll"):
        return
    user32 = ctypes.windll.user32
    shcore = getattr(ctypes.windll, "shcore", None)
    try:
        # Windows 10+: Per-monitor DPI aware v2.
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    try:
        # Windows 8.1 fallback.
        if shcore is not None:
            shcore.SetProcessDpiAwareness(2)
            return
    except Exception:
        pass
    try:
        # Legacy fallback.
        user32.SetProcessDPIAware()
    except Exception:
        pass


def get_primary_resolution() -> tuple[int, int]:
    # Use pyautogui size for coordinate mapping because actions are executed by pyautogui.
    try:
        size = pyautogui.size()
        if int(size.width) > 0 and int(size.height) > 0:
            return int(size.width), int(size.height)
    except Exception:
        pass

    with mss.mss() as sct:
        mon = sct.monitors[1]
        return int(mon["width"]), int(mon["height"])


def get_resolution_diagnostics() -> dict[str, Any]:
    py_w = py_h = 0
    mss_w = mss_h = 0
    try:
        size = pyautogui.size()
        py_w, py_h = int(size.width), int(size.height)
    except Exception:
        pass
    try:
        with mss.mss() as sct:
            mon = sct.monitors[1]
            mss_w, mss_h = int(mon["width"]), int(mon["height"])
    except Exception:
        pass
    scale_x = (mss_w / py_w) if py_w > 0 and mss_w > 0 else None
    scale_y = (mss_h / py_h) if py_h > 0 and mss_h > 0 else None
    return {
        "pyautogui_width": py_w,
        "pyautogui_height": py_h,
        "mss_width": mss_w,
        "mss_height": mss_h,
        "scale_x": scale_x,
        "scale_y": scale_y,
    }


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
