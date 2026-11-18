"""Upscale ảnh tĩnh."""
from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageOps

from .engine import Cancelled, Job, default_out_path, target_size

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}

# key -> (nhãn, chế độ)
IMAGE_RESOLUTIONS = {
    "x2": ("Gấp 2", "x2"),
    "x3": ("Gấp 3", "x3"),
    "x4": ("Gấp 4", "x4"),
    "1440": ("2K", 1440),
    "2160": ("4K", 2160),
}

IMAGE_FORMATS = {
    "same": ("Giữ nguyên", None),
    "png": ("PNG", ".png"),
    "jpg": ("JPG", ".jpg"),
    "webp": ("WebP", ".webp"),
}


@dataclass
class ImageInfo:
    width: int
    height: int
    has_alpha: bool


@dataclass
class ImageSettings:
    resolution: object = "x4"
    fmt: str = "same"
    quality: int = 95
    out_dir: str = ""


def _has_alpha(im) -> bool:
    return im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info)


def probe_image(path: str) -> ImageInfo:
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)
        return ImageInfo(im.width, im.height, _has_alpha(im))


def upscale_image(job: Job, runner, settings: ImageSettings, progress_cb) -> str:
    with Image.open(job.path) as src:
        im = ImageOps.exif_transpose(src)
        im.load()
    alpha = im.convert("RGBA").getchannel("A") if _has_alpha(im) else None
    rgb = np.array(im.convert("RGB"))  # bản sao ghi được
    h, w = rgb.shape[:2]
    tw, th = target_size(w, h, settings.resolution)

    ext = IMAGE_FORMATS[settings.fmt][1] or os.path.splitext(job.path)[1].lower()
    ext = {".jpeg": ".jpg", ".tiff": ".tif"}.get(ext, ext)
    if ext not in (".png", ".jpg", ".webp", ".bmp", ".tif"):
        ext = ".png"
    out_path = job.out_path = default_out_path(job.path, settings.out_dir, tw, th, ext)

    if job.cancel.is_set():
        raise Cancelled()

    def tile_cb(k, n):
        if job.cancel.is_set():
            raise Cancelled()
        progress_cb(k - 1, n, 0)

    out = runner.upscale(rgb, (tw, th), [runner.initial_tile(w, h)], tile_cb)

    res = Image.fromarray(out, "RGB")
    if alpha is not None and ext in (".png", ".webp", ".tif"):
        res.putalpha(alpha.resize((tw, th), Image.LANCZOS))

    fmt = {".png": "PNG", ".jpg": "JPEG", ".webp": "WEBP", ".bmp": "BMP", ".tif": "TIFF"}[ext]
    kw = {"JPEG": dict(quality=settings.quality, subsampling=0, optimize=True),
          "WEBP": dict(quality=settings.quality, method=4),
          "PNG": dict(compress_level=4)}.get(fmt, {})
    tmp = out_path + ".part"
    res.save(tmp, format=fmt, **kw)
    os.replace(tmp, out_path)
    progress_cb(1, 1, 0)
    return out_path
