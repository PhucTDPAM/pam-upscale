# Giấy phép bên thứ ba / Third-party licenses

Pam Upscale dùng các model và thư viện dưới đây. Trọng số model thuộc về tác giả gốc; file `.onnx` trong
thư mục `models/` là bản **chuyển đổi định dạng** (PyTorch → ONNX, một số có thêm bản FP16) từ trọng số gốc,
không huấn luyện lại.

## Model

| Model | Tác giả | Giấy phép | Nguồn gốc |
|---|---|---|---|
| Real-ESRGAN (animevideov3, general-x4v3, x4plus, x4plus_anime_6B) | Xintao Wang và cộng sự (Tencent ARC) | BSD-3-Clause | https://github.com/xinntao/Real-ESRGAN |
| Real-CUGAN (up2x-latest-conservative, up2x-latest-denoise3x) | Bilibili AI Lab | GPL-3.0 | https://github.com/bilibili/ailab/tree/main/Real-CUGAN |
| 4xNomos2_realplksr_dysample | Philip Hofmann (Phhofm) | CC-BY-4.0 | https://github.com/Phhofm/models/releases/tag/4xNomos2_realplksr_dysample |
| 4xNomos2_hq_dat2 | Philip Hofmann (Phhofm) | CC-BY-4.0 | https://github.com/Phhofm/models/releases/tag/4xNomos2_hq_dat2 |

**Ghi công CC-BY-4.0:** model *4xNomos2_realplksr_dysample* và *4xNomos2_hq_dat2* của Philip Hofmann,
giấy phép https://creativecommons.org/licenses/by/4.0/ . Thay đổi: chuyển sang định dạng ONNX.

**Real-CUGAN (GPL-3.0):** các file `up2x-latest-*.onnx` là bản chuyển đổi từ trọng số Real-CUGAN chính thức
(https://github.com/bilibili/ailab/releases/tag/Real-CUGAN). Toàn văn giấy phép: https://www.gnu.org/licenses/gpl-3.0.html .
Mã nguồn chuyển đổi nằm trong `upscaler/models.py` (hàm `export_onnx`).

## Không phân phối kèm

- **NVIDIA RTX Video Super Resolution** (gói `nvidia-vfx`): trình cài tải từ PyPI theo điều khoản của NVIDIA,
  không có trong repo này.
- **PyTorch, ONNX Runtime, spandrel, customtkinter, tkinterdnd2, Pillow, NumPy**: cài qua pip theo giấy phép
  riêng của từng dự án.
- **FFmpeg**: trình cài tải bản build của gyan.dev (https://www.gyan.dev/ffmpeg/builds/), giấy phép GPL.

## Không dùng

- AnimeJaNai (CC-BY-NC-SA-4.0, cấm thương mại) và AnimeSR (cần thỏa thuận giấy phép riêng với Tencent).
