"""Chọn thiết bị xử lý và chạy model.

Thứ tự tự động:  NVIDIA CUDA (PyTorch)  →  DirectML (AMD / Intel / NVIDIA đời cũ, qua ONNX Runtime)  →  CPU.
RTX Video Super Resolution chỉ chạy trên CUDA với card RTX (Turing trở lên).
"""
from __future__ import annotations

import os
import subprocess
import threading
from dataclasses import dataclass

import numpy as np
from PIL import Image

from .catalog import MODEL_CATALOG, onnx_path, weights_path

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

BACKEND_LABELS = {
    "auto": "Tự động",
    "cuda": "NVIDIA CUDA",
    "directml": "DirectML (AMD/Intel)",
    "cpu": "CPU (chậm)",
}


# ------------------------------------------------------------------------------------------ detect
def _torch():
    try:
        import torch
        return torch
    except Exception:
        return None


def _ort():
    try:
        import onnxruntime
        return onnxruntime
    except Exception:
        return None


@dataclass
class Detected:
    available: dict          # backend -> bool
    gpu_names: list
    cuda_name: str = ""
    cuda_vram: int = 0
    cuda_reason: str = ""
    rtx_vsr: bool = False    # có dùng được RTX Video Super Resolution không
    rtx_reason: str = ""


_detected: Detected | None = None
_det_lock = threading.Lock()


def _list_gpus() -> list[str]:
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_VideoController).Name"],
                           capture_output=True, text=True, timeout=15, creationflags=NO_WINDOW)
        names = [n.strip() for n in r.stdout.splitlines() if n.strip()]
        return [n for n in names if not any(t in n.lower() for t in ("basic", "virtual", "remote"))] or names
    except Exception:
        return []


def detect() -> Detected:
    global _detected
    with _det_lock:
        if _detected:
            return _detected
        avail = {"cuda": False, "directml": False, "cpu": True}
        d = Detected(available=avail, gpu_names=_list_gpus())
        torch = _torch()
        if torch is None:
            d.cuda_reason = "Chưa cài PyTorch CUDA"
        elif not torch.cuda.is_available():
            d.cuda_reason = "Không có card NVIDIA hoặc driver quá cũ"
        else:
            try:
                x = torch.zeros(1, 3, 8, 8, device="cuda", dtype=torch.float16)
                torch.nn.functional.conv2d(x, torch.zeros(3, 3, 3, 3, device="cuda", dtype=torch.float16))
                torch.cuda.synchronize()
                avail["cuda"] = True
                d.cuda_name = torch.cuda.get_device_name(0)
                d.cuda_vram = torch.cuda.get_device_properties(0).total_memory
            except Exception as e:
                d.cuda_reason = f"Card NVIDIA không tương thích bản PyTorch này ({e.__class__.__name__})"
        if avail["cuda"]:
            if torch.cuda.get_device_capability(0) < (7, 5):
                d.rtx_reason = "Cần card RTX 20xx trở lên"
            else:
                try:
                    import nvvfx  # noqa: F401
                    d.rtx_vsr = True
                except Exception:
                    d.rtx_reason = "Chưa cài gói nvidia-vfx"
        else:
            d.rtx_reason = "Cần card NVIDIA RTX"
        ort = _ort()
        if ort is not None and "DmlExecutionProvider" in ort.get_available_providers() and d.gpu_names:
            avail["directml"] = True
        if ort is None and torch is None:
            avail["cpu"] = False
        _detected = d
        return d


def resolve(pref: str) -> str:
    av = detect().available
    if pref in av and av[pref]:
        return pref
    for b in ("cuda", "directml", "cpu"):
        if av[b]:
            return b
    raise RuntimeError("Chưa cài thư viện xử lý. Hãy chạy cai_dat.bat")


def model_available(key: str, backend: str) -> tuple[bool, str]:
    """(dùng được?, lý do nếu không)."""
    spec = MODEL_CATALOG[key]
    d = detect()
    if spec.kind == "rtx":
        if backend != "cuda" or not d.rtx_vsr:
            return False, d.rtx_reason or "Chỉ chạy trên NVIDIA CUDA"
        return True, ""
    if backend == "cuda":
        return True, ""
    if spec.cuda_only:
        return False, "Quá nặng cho DirectML/CPU – chỉ chạy trên NVIDIA"
    if os.path.exists(onnx_path(key)) or _torch() is not None:
        return True, ""
    return False, "Thiếu file model .onnx"


def device_name(backend: str) -> str:
    d = detect()
    if backend == "cuda":
        return d.cuda_name.replace("NVIDIA ", "")
    if backend == "directml":
        return (d.gpu_names[0] if d.gpu_names else "GPU DirectX 12").replace("NVIDIA ", "")
    return "Bộ xử lý (CPU)"


def vram_usage():
    torch = _torch()
    if torch is not None and detect().available["cuda"]:
        free, total = torch.cuda.mem_get_info()
        return total - free, total
    return None


def release():
    torch = _torch()
    if torch is not None and detect().available["cuda"]:
        torch.cuda.empty_cache()


# ------------------------------------------------------------------------------------------ runners
class _Runner:
    backend = ""
    multiple_of = 1
    minimum = 0

    def __init__(self, key):
        spec = MODEL_CATALOG[key]
        self.key, self.scale, self.heavy = key, spec.scale, spec.heavy

    def initial_tile(self, w: int, h: int) -> int:
        ct = MODEL_CATALOG[self.key].cuda_tile
        if self.backend == "cuda" and ct:
            return ct if w * h > ct * ct else 0
        if self.backend == "cuda":
            if self.heavy:
                return 512 if w * h > 512 * 512 else 0
            return 1024 if w * h > 1024 * 1024 * 2 else 0
        if self.heavy:  # DirectML / CPU: chưa biết VRAM → chia nhỏ an toàn
            return 256 if w * h > 256 * 256 else 0
        return 720 if w * h > 1280 * 720 else 0

    def _pad_amount(self, h, w):
        m, mn = self.multiple_of, self.minimum
        ph = max((-h) % m, mn - h if h < mn else 0)
        pw = max((-w) % m, mn - w if w < mn else 0)
        ph += (-(h + ph)) % m
        pw += (-(w + pw)) % m
        return ph, pw


def _tiles(h, w, tile, pad=16):
    for y0 in range(0, h, tile):
        for x0 in range(0, w, tile):
            y1, x1 = min(y0 + tile, h), min(x0 + tile, w)
            yield y0, y1, x0, x1, max(y0 - pad, 0), max(x0 - pad, 0), min(y1 + pad, h), min(x1 + pad, w)


class TorchRunner(_Runner):
    backend = "cuda"

    def __init__(self, key, status_cb=None):
        super().__init__(key)
        import torch
        from .models import load_torch
        self.torch = torch
        tm = load_torch(key, status_cb)
        if status_cb:
            status_cb("Đang nạp model lên GPU…")
        forced = MODEL_CATALOG[key].half
        self.half = tm.supports_half if forced is None else forced
        self.dtype = torch.float16 if self.half else torch.float32
        self.multiple_of, self.minimum = tm.multiple_of, tm.minimum
        net = tm.net.to("cuda")
        self.net = (net.half() if self.half else net).to(memory_format=torch.channels_last)
        self._tls = threading.local()

    def _net(self, x):
        h, w = x.shape[-2:]
        ph, pw = self._pad_amount(h, w)
        if ph or pw:
            mode = "reflect" if ph < h and pw < w else "replicate"
            x = self.torch.nn.functional.pad(x, (0, pw, 0, ph), mode=mode)
        y = self.net(x)
        return y[..., : h * self.scale, : w * self.scale]

    def _forward(self, x, tile, tile_cb):
        _, _, h, w = x.shape
        if tile <= 0 or (h <= tile and w <= tile):
            return self._net(x)
        s = self.scale
        out = x.new_empty((1, 3, h * s, w * s))
        tl = list(_tiles(h, w, tile))
        for k, (y0, y1, x0, x1, py0, px0, py1, px1) in enumerate(tl, 1):
            if tile_cb:
                tile_cb(k, len(tl))
            o = self._net(x[:, :, py0:py1, px0:px1])
            oy, ox = (y0 - py0) * s, (x0 - px0) * s
            out[:, :, y0 * s:y1 * s, x0 * s:x1 * s] = o[:, :, oy:oy + (y1 - y0) * s, ox:ox + (x1 - x0) * s]
        return out

    def upscale(self, rgb: np.ndarray, size, tile_state: list, tile_cb=None) -> np.ndarray:
        torch = self.torch
        stream = getattr(self._tls, "stream", None)
        if stream is None:
            stream = self._tls.stream = torch.cuda.Stream()
        tw, th = size
        with torch.inference_mode(), torch.cuda.stream(stream):
            x = torch.from_numpy(rgb).to("cuda", non_blocking=True)
            x = x.permute(2, 0, 1).unsqueeze(0).to(self.dtype).div_(255).contiguous(memory_format=torch.channels_last)
            while True:
                try:
                    y = self._forward(x, tile_state[0], tile_cb)
                    break
                except torch.OutOfMemoryError:
                    torch.cuda.empty_cache()
                    tile_state[0] = 512 if tile_state[0] == 0 else tile_state[0] // 2
                    if tile_state[0] < 64:
                        raise RuntimeError("Hết VRAM GPU – hãy giảm số tác vụ chạy cùng lúc")
            if y.shape[-2:] != (th, tw):
                y = torch.nn.functional.interpolate(y.float(), size=(th, tw), mode="bicubic", antialias=True,
                                                    align_corners=False)
            y = y.clamp_(0, 1).mul_(255).add_(0.5).to(torch.uint8)
            return y[0].permute(1, 2, 0).contiguous().cpu().numpy()


class RtxVsrRunner(_Runner):
    """NVIDIA RTX Video Super Resolution – phóng thẳng tới kích thước đích, không cần tile."""
    backend = "cuda"

    def __init__(self, key, status_cb=None):
        super().__init__(key)
        import nvvfx
        import torch
        self.torch, self.nvvfx = torch, nvvfx
        self.quality = nvvfx.QualityLevel[MODEL_CATALOG[key].rtx_quality]
        self._tls = threading.local()
        if status_cb:
            status_cb("Đang khởi tạo RTX Video Super Resolution…")

    def initial_tile(self, w, h):
        return 0

    def _effect(self, tw, th):
        tls = self._tls
        if getattr(tls, "size", None) != (tw, th):
            if getattr(tls, "sr", None) is not None:
                tls.sr.close()
            sr = self.nvvfx.VideoSuperRes(quality=self.quality)
            sr.output_width, sr.output_height = tw, th
            sr.load()
            tls.sr, tls.size = sr, (tw, th)
            tls.stream = self.torch.cuda.Stream()
        return tls.sr, tls.stream

    def upscale(self, rgb: np.ndarray, size, tile_state: list, tile_cb=None) -> np.ndarray:
        torch = self.torch
        tw, th = size
        sr, stream = self._effect(tw, th)
        with torch.inference_mode(), torch.cuda.stream(stream):
            x = torch.from_numpy(rgb).to("cuda", non_blocking=True).permute(2, 0, 1).float().div_(255).contiguous()
            stream.synchronize()
            y = torch.from_dlpack(sr.run(x).image).clone()
            y = y.clamp_(0, 1).mul_(255).add_(0.5).to(torch.uint8)
            return y.permute(1, 2, 0).contiguous().cpu().numpy()


class OrtRunner(_Runner):
    def __init__(self, key, backend, status_cb=None):
        super().__init__(key)
        self.backend = backend
        import onnxruntime as ort
        path = onnx_path(key)
        if not os.path.exists(path):
            if _torch() is None:
                raise RuntimeError(f"Thiếu file model {os.path.basename(path)} trong thư mục models")
            from .models import export_onnx
            export_onnx(key, status_cb)
        self.fixed = MODEL_CATALOG[key].onnx_tile
        if MODEL_CATALOG[key].kind == "spandrel" and not self.fixed:
            self.multiple_of, self.minimum = _spandrel_req(key)
        if status_cb:
            status_cb("Đang nạp model…" + (" (lần đầu trên DirectML có thể mất 1 phút)" if backend == "directml" else ""))
        so = ort.SessionOptions()
        so.log_severity_level = 3
        if backend == "directml":
            so.enable_mem_pattern = False
            so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            providers = [("DmlExecutionProvider", {"device_id": 0}), "CPUExecutionProvider"]
        else:
            providers = ["CPUExecutionProvider"]
        self.sess = None
        fp16 = path[:-5] + ".fp16.onnx"
        if backend == "directml" and os.path.exists(fp16):
            try:  # FP16 nhanh hơn ~1.5x; card nào không hỗ trợ thì quay về FP32
                sess = ort.InferenceSession(fp16, so, providers=providers)
                sess.run(None, {"input": np.zeros((1, 3, 64, 64), np.float32)})
                self.sess = sess
            except Exception:
                self.sess = None
        if self.sess is None:
            self.sess = ort.InferenceSession(path, so, providers=providers)
        self.lock = threading.Lock() if backend == "directml" else None

    def _run(self, x):
        h, w = x.shape[-2:]
        ph, pw = self._pad_amount(h, w)
        if ph or pw:
            x = np.pad(x, ((0, 0), (0, 0), (0, ph), (0, pw)), mode="reflect" if ph < h and pw < w else "edge")
        if self.lock:
            with self.lock:
                y = self.sess.run(None, {"input": x})[0]
        else:
            y = self.sess.run(None, {"input": x})[0]
        return y[..., : h * self.scale, : w * self.scale]

    def _fixed_forward(self, x, T, tile_cb, ov=16):
        """Model ONNX kích thước cố định T×T: trượt cửa sổ T×T chồng mép `ov` px, ghép phần giữa."""
        _, _, h, w = x.shape
        ph, pw = max(0, T - h), max(0, T - w)
        if ph or pw:
            x = np.pad(x, ((0, 0), (0, 0), (0, ph), (0, pw)), mode="reflect" if ph < h and pw < w else "edge")
        H, W = x.shape[-2:]
        step = T - 2 * ov

        def starts(n):
            st = list(range(0, n - T + 1, step))
            if st[-1] != n - T:
                st.append(n - T)
            return st

        s = self.scale
        out = np.empty((1, 3, H * s, W * s), np.float32)
        wins = [(y0, x0) for y0 in starts(H) for x0 in starts(W)]
        for k, (y0, x0) in enumerate(wins, 1):
            if tile_cb:
                tile_cb(k, len(wins))
            o = self._run(np.ascontiguousarray(x[:, :, y0:y0 + T, x0:x0 + T]))
            top, bot = (y0 + ov if y0 > 0 else 0), (y0 + T - ov if y0 + T < H else H)
            left, right = (x0 + ov if x0 > 0 else 0), (x0 + T - ov if x0 + T < W else W)
            out[:, :, top * s:bot * s, left * s:right * s] = \
                o[:, :, (top - y0) * s:(bot - y0) * s, (left - x0) * s:(right - x0) * s]
        return out[..., : h * s, : w * s]

    def _forward(self, x, tile, tile_cb):
        if self.fixed:
            return self._fixed_forward(x, self.fixed, tile_cb)
        _, _, h, w = x.shape
        if tile <= 0 or (h <= tile and w <= tile):
            return self._run(x)
        s = self.scale
        out = np.empty((1, 3, h * s, w * s), np.float32)
        tl = list(_tiles(h, w, tile))
        for k, (y0, y1, x0, x1, py0, px0, py1, px1) in enumerate(tl, 1):
            if tile_cb:
                tile_cb(k, len(tl))
            o = self._run(np.ascontiguousarray(x[:, :, py0:py1, px0:px1]))
            oy, ox = (y0 - py0) * s, (x0 - px0) * s
            out[:, :, y0 * s:y1 * s, x0 * s:x1 * s] = o[:, :, oy:oy + (y1 - y0) * s, ox:ox + (x1 - x0) * s]
        return out

    def upscale(self, rgb: np.ndarray, size, tile_state: list, tile_cb=None) -> np.ndarray:
        x = np.ascontiguousarray(rgb.transpose(2, 0, 1)[None], dtype=np.float32)
        x *= 1 / 255
        while True:
            try:
                y = self._forward(x, tile_state[0], tile_cb)
                break
            except Exception as e:
                msg = str(e).lower()
                if not any(t in msg for t in ("memory", "e_outofmemory", "887a0005", "allocate")):
                    raise
                tile_state[0] = 512 if tile_state[0] == 0 else tile_state[0] // 2
                if tile_state[0] < 64:
                    raise RuntimeError("Hết bộ nhớ GPU – hãy giảm số tác vụ chạy cùng lúc")
        out = np.clip(y[0].transpose(1, 2, 0) * 255 + 0.5, 0, 255).astype(np.uint8)
        tw, th = size
        if out.shape[1] != tw or out.shape[0] != th:
            out = np.asarray(Image.fromarray(out).resize((tw, th), Image.LANCZOS, reducing_gap=3.0))
        return out


# yêu cầu kích thước của các model spandrel (đo sẵn, dùng khi máy không có PyTorch)
# Real-CUGAN: bản ONNX cần cạnh chẵn (code cắt viền cho cạnh lẻ không xuất được sang ONNX)
_SPANDREL_REQ = {"cugan_cons": (2, 32), "cugan_dn3": (2, 32), "nomos_plksr": (1, 0), "nomos_dat2": (1, 16)}


def _spandrel_req(key):
    return _SPANDREL_REQ.get(key, (8, 32))


_runners: dict = {}
_run_lock = threading.Lock()


def get_runner(key: str, backend: str, status_cb=None):
    ok, why = model_available(key, backend)
    if not ok:
        raise RuntimeError(f"{MODEL_CATALOG[key].label}: {why}")
    with _run_lock:
        r = _runners.get((backend, key))
        if r is None:
            kind = MODEL_CATALOG[key].kind
            if kind == "rtx":
                r = RtxVsrRunner(key, status_cb)
            elif backend == "cuda":
                r = TorchRunner(key, status_cb)
            else:
                r = OrtRunner(key, backend, status_cb)
            _runners[(backend, key)] = r
        return r


__all__ = ["BACKEND_LABELS", "detect", "resolve", "model_available", "device_name", "vram_usage", "release",
           "get_runner", "weights_path"]
