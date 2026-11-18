"""Danh mục model (không phụ thuộc PyTorch).

Tốc độ ghi trong `speed` là số đo thật trên RTX 3060 12GB: 1 khung 720p → 1080p (gồm cả chép dữ liệu & resize),
chạy 1 tác vụ. Thang: Siêu nhanh ≥ 50 fps · Nhanh ≥ 7 · Trung bình ≥ 2 · Chậm ≥ 0.5 · Rất chậm < 0.5.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(APP_DIR, "models")


@dataclass(frozen=True)
class ModelSpec:
    key: str
    label: str            # tên ngắn trong menu
    speed_tag: str        # Siêu nhanh / Nhanh / Trung bình / Chậm / Rất chậm
    speed: str            # số đo tốc độ
    desc: str             # dùng cho nội dung gì
    license: str
    kind: str             # "native" (code riêng) | "spandrel" | "rtx"
    scale: int = 4
    heavy: bool = False
    file: str = ""
    url: str = ""
    zip_member: str = ""  # nếu url là file .zip
    rtx_quality: str = ""
    half: bool | None = None  # ép FP16 bật/tắt (None = theo spandrel)
    cuda_tile: int = 0        # kích thước tile tối ưu trên CUDA (0 = mặc định)
    cuda_only: bool = False   # quá nặng cho DirectML/CPU
    video: bool = True        # hiện ở trang Video không
    onnx_tile: int = 0        # >0: file ONNX kích thước cố định (DirectML lỗi với kích thước động của model này)
    clip_note: str = ""       # thời gian thực tế cho clip 8 giây (khi khâu đọc/ghi video mới là giới hạn)


SPEED_COLORS = {"Siêu nhanh": "#22c55e", "Nhanh": "#84cc16", "Trung bình": "#f5a524", "Chậm": "#f97316",
                "Rất chậm": "#f05252"}

_CUGAN_ZIP = "https://github.com/bilibili/ailab/releases/download/Real-CUGAN/updated_weights.zip"

MODELS: list[ModelSpec] = [
    # ---------------------------------------------------------------- NVIDIA RTX VSR
    ModelSpec("rtx_ultra", "RTX Video Super Resolution · Ultra", "Siêu nhanh", "~130 fps",
              "Giữ đúng hình gốc, không nhấp nháy khi chuyển động, ra được 4K. Hợp mọi loại video, "
              "đặc biệt 3D. Chỉ có trên card NVIDIA RTX.", "NVIDIA RTX Video SDK", "rtx", rtx_quality="ULTRA",
              clip_note="clip Flow 8 giây ≈ 4 giây (1080p) · 7 giây (4K)"),
    ModelSpec("rtx_highbitrate", "RTX Video Super Resolution · High bitrate", "Siêu nhanh", "~95 fps",
              "Cho nguồn sạch, ít nén – giữ chi tiết mịn hơn Ultra.", "NVIDIA RTX Video SDK", "rtx",
              rtx_quality="HIGHBITRATE_ULTRA", clip_note="clip Flow 8 giây ≈ 5 giây (1080p) · 8 giây (4K)"),
    ModelSpec("rtx_high", "RTX Video Super Resolution · High", "Siêu nhanh", "~145 fps",
              "Nhanh hơn Ultra một chút, chi tiết nhẹ hơn.", "NVIDIA RTX Video SDK", "rtx", rtx_quality="HIGH",
              clip_note="clip Flow 8 giây ≈ 4 giây (1080p) · 7 giây (4K)"),
    # ---------------------------------------------------------------- Real-ESRGAN
    ModelSpec("anime_video", "Real-ESRGAN Anime Video v3", "Nhanh", "~8 fps",
              "Hoạt hình 2D/3D, video AI. Làm nét mạnh, nét vẽ rõ.", "BSD-3 (thương mại OK)", "native",
              file="realesr-animevideov3.pth",
              url="https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-animevideov3.pth"),
    ModelSpec("general", "Real-ESRGAN General v3", "Trung bình", "~4.5 fps",
              "Cảnh thật, người thật, phong cảnh.", "BSD-3 (thương mại OK)", "native",
              file="realesr-general-x4v3.pth",
              url="https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-x4v3.pth"),
    # ---------------------------------------------------------------- Real-CUGAN (2D)
    ModelSpec("cugan_cons", "Real-CUGAN 2x · Conservative", "Trung bình", "~5 fps",
              "Hoạt hình 2D: nét vẽ sạch, giữ chi tiết gốc, ít bệt hơn Real-ESRGAN. AI phóng 2x, "
              "phần còn lại phóng bằng bicubic.", "GPL-3.0 (thương mại OK)", "spandrel", scale=2, onnx_tile=720,
              file="up2x-latest-conservative.pth", url=_CUGAN_ZIP,
              zip_member="updated_weights/up2x-latest-conservative.pth"),
    ModelSpec("cugan_dn3", "Real-CUGAN 2x · Khử nhiễu mạnh", "Trung bình", "~5 fps",
              "Hoạt hình 2D bị nén nhiều, vỡ khối: khử nhiễu mạnh nhất, mảng màu phẳng sạch.",
              "GPL-3.0 (thương mại OK)", "spandrel", scale=2, onnx_tile=720,
              file="up2x-latest-denoise3x.pth", url=_CUGAN_ZIP,
              zip_member="updated_weights/up2x-latest-denoise3x.pth"),
    # ---------------------------------------------------------------- Chất lượng cao
    ModelSpec("anime_hq", "Real-ESRGAN Anime 6B", "Chậm", "~0.8 fps",
              "Hoạt hình: nét hơn bản Anime Video, chậm hơn ~10 lần.", "BSD-3 (thương mại OK)", "native",
              heavy=True, file="RealESRGAN_x4plus_anime_6B.pth",
              url="https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth"),
    ModelSpec("nomos_plksr", "Nomos2 RealPLKSR", "Rất chậm", "~0.3 fps",
              "Ảnh thật / 3D chân thực: chi tiết tự nhiên, ít bệt kiểu tranh vẽ. Tác giả Philip Hofmann.",
              "CC-BY-4.0 (thương mại OK, ghi công)", "spandrel", heavy=True, half=False, cuda_tile=256, onnx_tile=256,
              file="4xNomos2_realplksr_dysample.pth",
              url="https://huggingface.co/Phips/4xNomos2_realplksr_dysample/resolve/main/4xNomos2_realplksr_dysample.pth"),
    ModelSpec("general_hq", "Real-ESRGAN x4plus", "Rất chậm", "~0.27 fps",
              "Ảnh chụp thật: model gốc nặng nhất của Real-ESRGAN.", "BSD-3 (thương mại OK)", "native",
              heavy=True, file="RealESRGAN_x4plus.pth",
              url="https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth"),
    ModelSpec("nomos_dat2", "Nomos2 DAT2 (nét nhất)", "Rất chậm", "~0.05 fps",
              "Nét và chi tiết nhất – transformer DAT. Chỉ dùng cho ẢNH (video 8 giây sẽ mất ~1 giờ). "
              "Chỉ chạy trên NVIDIA.",
              "CC-BY-4.0 (thương mại OK, ghi công)", "spandrel", heavy=True, half=True, cuda_tile=128,
              cuda_only=True, video=False,
              file="4xNomos2_hq_dat2.safetensors",
              url="https://huggingface.co/Phips/4xNomos2_hq_dat2/resolve/main/4xNomos2_hq_dat2.safetensors"),
]

MODEL_CATALOG: dict[str, ModelSpec] = {m.key: m for m in MODELS}


def weights_path(key: str) -> str:
    return os.path.join(MODELS_DIR, MODEL_CATALOG[key].file)


def onnx_path(key: str) -> str:
    m = MODEL_CATALOG[key]
    suffix = f".t{m.onnx_tile}.onnx" if m.onnx_tile else ".onnx"
    return os.path.join(MODELS_DIR, os.path.splitext(m.file)[0] + suffix)


def ensure_weights(key: str, status_cb=None) -> str:
    import io
    import urllib.request
    import zipfile

    m = MODEL_CATALOG[key]
    os.makedirs(MODELS_DIR, exist_ok=True)
    path = weights_path(key)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    if status_cb:
        status_cb(f"Đang tải model {m.label}…")
    req = urllib.request.Request(m.url, headers={"User-Agent": "PamUpscale/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        total = int(r.headers.get("Content-Length") or 0)
        buf, last = io.BytesIO(), -1
        while chunk := r.read(1 << 20):
            buf.write(chunk)
            if status_cb and total:
                pct = buf.tell() * 100 // total
                if pct != last:
                    last = pct
                    status_cb(f"Đang tải model {m.label}: {pct}%")
    data = buf.getvalue()
    if m.zip_member:
        data = zipfile.ZipFile(io.BytesIO(data)).read(m.zip_member)
    tmp = path + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    return path
