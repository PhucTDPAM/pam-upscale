<p align="center"><img src="assets/logo_mark.png" width="96" alt="Pam Upscale"></p>

<h1 align="center">Pam Upscale</h1>
<p align="center">Upscale video &amp; ảnh AI (Flow, Veo, Kling…) ngay trên máy tính – by <b>PAM Media</b></p>

---

## Tải về & cài đặt

1. Vào mục **[Releases](../../releases/latest)** → tải file **`PamUpscale.zip`** (đã kèm sẵn mọi model).
2. Giải nén → nháy đúp **`cai_dat.bat`** (cần Internet, 2–20 phút tùy máy). Trình cài **tự động**:
   - cài Python 3.13 nếu máy chưa có,
   - nhận diện card đồ họa và cài đúng gói (NVIDIA / AMD / Intel / không card),
   - tải ffmpeg nếu chưa có,
   - tạo shortcut **Pam Upscale** trên Desktop.
3. Mở **Pam Upscale** trên Desktop → kéo thả video/ảnh → **Bắt đầu upscale**.

> Yêu cầu: Windows 10/11 64-bit. Có card NVIDIA RTX là nhanh nhất; AMD/Intel vẫn chạy được qua DirectML.

## Tính năng

- **Upscale Video** và **Upscale Ảnh**, chạy **nhiều file cùng lúc**, kéo thả cả thư mục.
- Giữ nguyên âm thanh; giữ nền trong suốt cho ảnh PNG/WebP.
- Tự chọn thiết bị tốt nhất: NVIDIA CUDA → DirectML (AMD/Intel) → CPU.
- Encode phần cứng: NVENC / AMD AMF / Intel QuickSync (hoặc x264 bằng CPU).

## Model

Tốc độ đo trên RTX 3060, video 720p → 1080p.

| Model | Tốc độ | Clip 8 giây | Dùng cho |
|---|---|---|---|
| RTX Video Super Resolution · Ultra / High / High bitrate | 🟢 Siêu nhanh | ~4 giây | Mọi video, nhất là 3D (chỉ NVIDIA RTX) |
| Real-ESRGAN Anime Video v3 | 🟢 Nhanh | ~24 giây | Hoạt hình 2D/3D |
| Real-ESRGAN General v3 | 🟡 Trung bình | ~45 giây | Cảnh thật |
| Real-CUGAN 2x · Conservative / Khử nhiễu mạnh | 🟡 Trung bình | ~40 giây | Hoạt hình 2D |
| Real-ESRGAN Anime 6B | 🟠 Chậm | ~4 phút | Hoạt hình, nét hơn |
| Nomos2 RealPLKSR | 🔴 Rất chậm | ~11 phút | Ảnh / 3D chân thực |
| Real-ESRGAN x4plus | 🔴 Rất chậm | ~12 phút | Ảnh chụp thật |
| Nomos2 DAT2 | 🔴 Rất chậm | chỉ cho ảnh | Ảnh cần nét tối đa (chỉ NVIDIA) |

Hướng dẫn chi tiết: [HUONG_DAN.md](HUONG_DAN.md) · Giấy phép model: [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)

## Chạy từ mã nguồn

```bat
git clone https://github.com/PhucTDPAM/pam-upscale.git
cd pam-upscale
cai_dat.bat
```
Bản clone không kèm file `.pth`; máy NVIDIA sẽ tự tải từ nguồn chính thức ở lần dùng đầu.

## Đóng gói lại

Chạy `dong_goi.bat` → tạo `PamUpscale.zip` cạnh thư mục app.
