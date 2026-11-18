# Pam Upscale – by PAM Media

Upscale **video** và **ảnh** AI (Flow/Veo, ảnh bìa…) bằng Real-ESRGAN, chạy nhiều tác vụ cùng lúc.

## Chạy
Mở **Pam Upscale** (shortcut) hoặc `Pam Upscale.bat`.

1. Chọn **Upscale Video** hoặc **Upscale Ảnh** ở thanh bên trái.
2. Kéo thả file/thư mục vào cửa sổ – video tự vào trang Video, ảnh tự vào trang Ảnh.
3. Chỉnh thiết lập bên phải → **Bắt đầu upscale**.
4. Kết quả nằm trong thư mục `upscaled` cạnh file gốc (hoặc thư mục bạn chọn).

## Chạy trên máy khác
1. Trên máy này: chạy **`dong_goi.bat`** → tạo `PamUpscale.zip` (cạnh thư mục app).
2. Trên máy kia: giải nén → chạy **`cai_dat.bat`** (cần Internet). Trình cài tự:
   - cài Python nếu chưa có,
   - nhận diện card đồ họa và cài đúng gói,
   - tải ffmpeg nếu chưa có,
   - tạo shortcut **Pam Upscale** trên Desktop.

App tự chọn thiết bị tốt nhất (đổi được ở ô **Thiết bị** góc dưới trái):

| Máy | Xử lý AI | Encode video | Tốc độ tương đối |
|---|---|---|---|
| NVIDIA RTX 20xx trở lên | CUDA | NVENC | nhanh nhất (100%) |
| NVIDIA GTX 9xx/10xx/16xx | CUDA 12.6 (hoặc DirectML) | NVENC | khá |
| AMD Radeon | DirectML | AMD AMF | ~30–60% |
| Intel Arc / Iris / UHD | DirectML | Intel QuickSync | chậm hơn (card onboard) |
| Không có GPU | CPU | x264 (CPU) | rất chậm – chỉ nên dùng cho ảnh |

## Chọn model
Tốc độ đo thật trên **RTX 3060**, video 720p → 1080p, 1 tác vụ. Card AMD/Intel (DirectML) chậm hơn 2–5 lần.

| Model | Tốc độ | Clip Flow 8 giây | Dùng cho | Chạy trên |
|---|---|---|---|---|
| **RTX VSR · Ultra** (mặc định video) | 🟢 Siêu nhanh ~130 fps | ~4 giây (1080p) · ~7 giây (4K) | Mọi video, đặc biệt 3D. Giữ đúng hình gốc, không nhấp nháy | Chỉ NVIDIA RTX 20xx+ |
| RTX VSR · High bitrate | 🟢 Siêu nhanh ~95 fps | ~5 giây | Nguồn sạch, ít nén | Chỉ NVIDIA RTX |
| RTX VSR · High | 🟢 Siêu nhanh ~145 fps | ~4 giây | Nhanh hơn Ultra, chi tiết nhẹ hơn | Chỉ NVIDIA RTX |
| Real-ESRGAN Anime Video v3 | 🟢 Nhanh ~8 fps | ~24 giây | Hoạt hình 2D/3D, làm nét mạnh | Mọi máy |
| Real-ESRGAN General v3 | 🟡 Trung bình ~4.5 fps | ~45 giây | Cảnh thật, người thật | Mọi máy |
| Real-CUGAN 2x · Conservative | 🟡 Trung bình ~5 fps | ~40 giây | Hoạt hình 2D: nét vẽ sạch, giữ chi tiết | Mọi máy |
| Real-CUGAN 2x · Khử nhiễu mạnh | 🟡 Trung bình ~5 fps | ~40 giây | Hoạt hình 2D bị nén, vỡ khối | Mọi máy |
| Real-ESRGAN Anime 6B | 🟠 Chậm ~0.8 fps | ~4 phút | Hoạt hình, nét hơn bản Video | Mọi máy |
| Nomos2 RealPLKSR (mặc định ảnh) | 🔴 Rất chậm ~0.3 fps | ~11 phút | Ảnh thật / 3D chân thực, chi tiết tự nhiên | Mọi máy |
| Real-ESRGAN x4plus | 🔴 Rất chậm ~0.27 fps | ~12 phút | Ảnh chụp thật | Mọi máy |
| Nomos2 DAT2 (nét nhất) | 🔴 Rất chậm ~20 giây/ảnh | (chỉ cho ảnh) | Ảnh cần nét tối đa | Chỉ NVIDIA |

**Gợi ý nhanh:** video 3D/AI → *RTX VSR Ultra*; hoạt hình 2D → *Real-CUGAN Conservative*; ảnh bìa → *Nomos2 RealPLKSR* hoặc *DAT2*.

### Giấy phép (đều dùng thương mại được)
- Real-ESRGAN: BSD-3 · Real-CUGAN: GPL-3.0 · RTX VSR: NVIDIA RTX Video SDK
- Nomos2 RealPLKSR / DAT2: CC-BY-4.0 – tác giả **Philip Hofmann (Phhofm)**, cần ghi công nếu công bố.
- *Không đưa vào:* AnimeJaNai (CC-BY-NC-SA – cấm thương mại), AnimeSR (cần ký thỏa thuận với Tencent).

## Mẹo
- 2 tác vụ cùng lúc là hợp lý; tăng thêm không nhanh hơn tổng thể.
- Ảnh PNG/WebP trong suốt được giữ nền trong suốt.
- Video > 4096px tự chuyển sang H.265. Âm thanh gốc được giữ nguyên.
