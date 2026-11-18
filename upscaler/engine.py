"""Pipeline upscale video: ffmpeg decode -> model AI (GPU/CPU) -> ffmpeg encode (NVENC/AMF/QSV/x264)."""
from __future__ import annotations

import collections
import glob
import json
import os
import queue
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field

import numpy as np

from .catalog import APP_DIR

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".wmv", ".flv", ".ts", ".gif"}

# key -> (nhãn, chế độ)
RESOLUTIONS = {
    "1080": ("Full HD 1080p", 1080),
    "1440": ("2K 1440p", 1440),
    "2160": ("4K 2160p", 2160),
    "x2": ("Gấp 2 lần", "x2"),
    "x4": ("Gấp 4 lần", "x4"),
}

CODECS = {"h264": "H.264", "hevc": "H.265"}


class Cancelled(Exception):
    pass


# ------------------------------------------------------------------------------------------ ffmpeg
def _find_tool(name: str) -> str:
    local = os.path.join(APP_DIR, "bin", name + ".exe")
    if os.path.exists(local):
        return local
    found = shutil.which(name)
    if found:
        return found
    # winget cài xong nhưng PATH chưa cập nhật
    pat = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\*FFmpeg*\*\bin\\" + name + ".exe")
    hits = glob.glob(pat)
    if hits:
        return hits[0]
    raise RuntimeError("Không tìm thấy ffmpeg. Hãy chạy cai_dat.bat")


_tools: dict = {}


def tool(name: str) -> str:
    if name not in _tools:
        _tools[name] = _find_tool(name)
    return _tools[name]


ENCODER_CANDIDATES = {
    "h264": ["h264_nvenc", "h264_amf", "h264_qsv", "libx264"],
    "hevc": ["hevc_nvenc", "hevc_amf", "hevc_qsv", "libx265"],
}
ENCODER_LABELS = {"nvenc": "NVIDIA NVENC", "amf": "AMD AMF", "qsv": "Intel QuickSync", "libx": "CPU (x264/x265)"}
_enc_ok: dict = {}
_enc_lock = threading.Lock()


def _encoder_works(name: str) -> bool:
    try:
        r = subprocess.run(
            [tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
             "color=c=black:s=640x360:r=24:d=0.25", "-pix_fmt", "yuv420p", "-c:v", name, "-f", "null", "-"],
            capture_output=True, timeout=30, creationflags=NO_WINDOW)
        return r.returncode == 0
    except Exception:
        return False


def pick_encoder(codec: str) -> str:
    with _enc_lock:
        for name in ENCODER_CANDIDATES[codec]:
            if name not in _enc_ok:
                _enc_ok[name] = _encoder_works(name)
            if _enc_ok[name]:
                return name
    return ENCODER_CANDIDATES[codec][-1]


def encoder_label(name: str) -> str:
    return next((v for k, v in ENCODER_LABELS.items() if k in name), name)


def encoder_args(name: str, q: int) -> list[str]:
    if "nvenc" in name:
        return ["-preset", "p5", "-tune", "hq", "-rc", "vbr", "-cq", str(q), "-b:v", "0"]
    if "amf" in name:
        return ["-quality", "quality", "-rc", "cqp", "-qp_i", str(q), "-qp_p", str(q + 2)] + (
            ["-qp_b", str(q + 4)] if "h264" in name else [])
    if "qsv" in name:
        return ["-preset", "slower", "-global_quality", str(q)]
    return ["-preset", "medium", "-crf", str(q)]


# ------------------------------------------------------------------------------------------ probe
@dataclass
class VideoInfo:
    width: int
    height: int
    fps: str
    fps_float: float
    frames: int
    has_audio: bool
    duration: float


def probe(path: str) -> VideoInfo:
    cmd = [
        tool("ffprobe"), "-v", "error", "-show_entries",
        "stream=codec_type,width,height,r_frame_rate,avg_frame_rate,nb_frames:format=duration",
        "-of", "json", path,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, creationflags=NO_WINDOW)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or "ffprobe lỗi")
    data = json.loads(res.stdout)
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    if v is None:
        raise RuntimeError("Không tìm thấy luồng video")
    fps = v.get("avg_frame_rate") or "0/0"
    if fps in ("0/0", "0/1"):
        fps = v.get("r_frame_rate") or "30/1"
    n, d = (int(x) for x in fps.split("/"))
    fps_f = n / d if d else 30.0
    duration = float(data.get("format", {}).get("duration") or 0)
    nb = v.get("nb_frames")
    frames = int(nb) if nb and str(nb).isdigit() else int(round(duration * fps_f))
    return VideoInfo(
        width=int(v["width"]), height=int(v["height"]), fps=fps, fps_float=fps_f,
        frames=max(frames, 1), has_audio=any(s.get("codec_type") == "audio" for s in streams),
        duration=duration,
    )


def target_size(w: int, h: int, mode) -> tuple[int, int]:
    if isinstance(mode, str) and mode.startswith("x"):
        f = float(mode[1:])
    else:
        f = int(mode) / min(w, h)
    return max(2, int(round(w * f / 2)) * 2), max(2, int(round(h * f / 2)) * 2)


@dataclass
class JobSettings:
    resolution: object = 1080
    codec: str = "h264"
    cq: int = 18
    out_dir: str = ""


@dataclass
class Job:
    path: str
    info: object = None
    out_path: str = ""
    cancel: threading.Event = field(default_factory=threading.Event)


def default_out_path(src: str, out_dir: str, tw: int, th: int, ext: str = ".mp4") -> str:
    folder = out_dir or os.path.join(os.path.dirname(src), "upscaled")
    os.makedirs(folder, exist_ok=True)
    stem = os.path.splitext(os.path.basename(src))[0]
    base = os.path.join(folder, f"{stem}_{min(tw, th)}p")
    path, i = base + ext, 2
    while os.path.exists(path):
        path, i = f"{base}_{i}{ext}", i + 1
    return path


def _read_exact(stream, buf: memoryview) -> bool:
    n, total = 0, len(buf)
    while n < total:
        r = stream.readinto(buf[n:])
        if not r:
            return False
        n += r
    return True


class _StderrTail(threading.Thread):
    def __init__(self, stream):
        super().__init__(daemon=True)
        self.stream, self.lines = stream, collections.deque(maxlen=20)
        self.start()

    def run(self):
        for line in iter(self.stream.readline, b""):
            self.lines.append(line.decode("utf-8", "replace").rstrip())

    def text(self):
        return "\n".join(self.lines)


# ------------------------------------------------------------------------------------------ main
def upscale_video(job: Job, runner, settings: JobSettings, progress_cb) -> str:
    """progress_cb(done, total, fps). Trả về đường dẫn file kết quả."""
    info = job.info or probe(job.path)
    job.info = info
    w, h = info.width, info.height
    tw, th = target_size(w, h, settings.resolution)
    out_path = job.out_path = default_out_path(job.path, settings.out_dir, tw, th)
    tmp_path = out_path[:-4] + ".part.mp4"

    codec = "hevc" if settings.codec == "h264" and max(tw, th) > 4096 else settings.codec  # H.264 tối đa 4096px
    encoder = pick_encoder(codec)

    dec_cmd = [
        tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-noautorotate", "-i", job.path,
        "-map", "0:v:0", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
    ]
    enc_cmd = [
        tool("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{tw}x{th}", "-r", info.fps, "-i", "pipe:0",
        "-i", job.path, "-map", "0:v:0", "-map", "1:a?",
        "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
        "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
        "-c:v", encoder, *encoder_args(encoder, settings.cq),
        "-c:a", "copy", "-movflags", "+faststart", tmp_path,
    ]

    dec = subprocess.Popen(dec_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           creationflags=NO_WINDOW, bufsize=0)
    enc = subprocess.Popen(enc_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE,
                           creationflags=NO_WINDOW, bufsize=0)
    dec_err, enc_err = _StderrTail(dec.stderr), _StderrTail(enc.stderr)

    in_q: queue.Queue = queue.Queue(maxsize=8)
    out_q: queue.Queue = queue.Queue(maxsize=8)
    errors: list[BaseException] = []

    def reader():
        try:
            while not job.cancel.is_set():
                arr = np.empty((h, w, 3), dtype=np.uint8)
                if not _read_exact(dec.stdout, memoryview(arr).cast("B")):
                    break
                in_q.put(arr)
        except BaseException as e:  # noqa
            errors.append(e)
        finally:
            in_q.put(None)

    def writer():
        try:
            while True:
                arr = out_q.get()
                if arr is None:
                    break
                enc.stdin.write(memoryview(arr).cast("B"))
        except BaseException as e:  # noqa
            errors.append(e)
            job.cancel.set()
        finally:
            try:
                enc.stdin.close()
            except OSError:
                pass

    rt, wt = threading.Thread(target=reader, daemon=True), threading.Thread(target=writer, daemon=True)
    rt.start()
    wt.start()

    tile_state = [runner.initial_tile(w, h)]
    done, t0, last = 0, time.time(), 0.0
    try:
        while True:
            arr = in_q.get()
            if arr is None:
                break
            if job.cancel.is_set():
                raise Cancelled()
            out_q.put(runner.upscale(arr, (tw, th), tile_state))
            done += 1
            now = time.time()
            if now - last > 0.25:
                last = now
                progress_cb(done, max(info.frames, done), done / max(now - t0, 1e-6))
            if errors:
                raise errors[0]
    except BaseException:
        job.cancel.set()
        _kill(dec)
        out_q.put(None)
        wt.join(timeout=5)
        _kill(enc)
        _safe_remove(tmp_path)
        raise
    finally:
        while rt.is_alive():
            try:
                in_q.get_nowait()
            except queue.Empty:
                rt.join(timeout=0.1)

    out_q.put(None)
    wt.join()
    enc.wait()
    dec.wait()
    if errors:
        _safe_remove(tmp_path)
        raise errors[0]
    if enc.returncode != 0:
        _safe_remove(tmp_path)
        raise RuntimeError(f"Lỗi encoder {encoder}:\n" + enc_err.text())
    if done == 0:
        _safe_remove(tmp_path)
        raise RuntimeError("Không đọc được khung hình nào:\n" + dec_err.text())
    os.replace(tmp_path, out_path)
    progress_cb(done, done, done / max(time.time() - t0, 1e-6))
    return out_path


def _kill(p: subprocess.Popen):
    if p.poll() is None:
        try:
            p.kill()
        except OSError:
            pass
    try:
        p.wait(timeout=5)
    except Exception:
        pass


def _safe_remove(path):
    for _ in range(10):
        try:
            if os.path.exists(path):
                os.remove(path)
            return
        except OSError:
            time.sleep(0.2)
