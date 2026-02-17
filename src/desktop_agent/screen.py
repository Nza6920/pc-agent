from __future__ import annotations

import base64
from pathlib import Path

import mss
import mss.tools


def get_primary_resolution() -> tuple[int, int]:
    with mss.mss() as sct:
        mon = sct.monitors[1]
        return int(mon["width"]), int(mon["height"])


def capture_primary_png(path: str) -> str:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with mss.mss() as sct:
        mon = sct.monitors[1]
        shot = sct.grab(mon)
        mss.tools.to_png(shot.rgb, shot.size, output=str(output))
    return str(output)


def png_to_base64(path: str) -> str:
    data = Path(path).read_bytes()
    return base64.b64encode(data).decode("ascii")
