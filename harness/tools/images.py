"""Read an image file so ChatGPT can actually see it (screenshots, diagrams, UI
mockups). read_file dead-ends on binaries; this returns the bytes + format for
an MCP image content block. Path-gated and size-capped.
"""

from __future__ import annotations

from ..context import HarnessContext

_IMAGE_FORMATS = {
    ".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".gif": "gif",
    ".webp": "webp", ".bmp": "bmp",
}
_MAX_IMAGE_BYTES = 5_000_000  # 5 MB


def read_image_bytes(hc: HarnessContext, path: str) -> tuple[bytes, str]:
    real = hc.resolve_read(path)  # confinement + secret-file gate
    if not real.exists() or real.is_dir():
        raise FileNotFoundError(f"Image not found: {real}")
    fmt = _IMAGE_FORMATS.get(real.suffix.lower())
    if fmt is None:
        raise ValueError(f"Not a supported image type: {real.suffix}. Supported: {', '.join(_IMAGE_FORMATS)}")
    size = real.stat().st_size
    if size > _MAX_IMAGE_BYTES:
        raise ValueError(f"Image too large ({size} bytes; cap {_MAX_IMAGE_BYTES}).")
    hc.log("read_image", path=str(real), bytes=size)
    return real.read_bytes(), fmt
