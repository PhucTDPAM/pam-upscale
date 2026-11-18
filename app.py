"""Pam Upscale – upscale video & ảnh AI bằng GPU (NVIDIA / AMD / Intel), chạy nhiều tác vụ cùng lúc."""
from __future__ import annotations

import io
import itertools
import json
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
from tkinter import filedialog, messagebox

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import customtkinter as ctk  # noqa: E402
from PIL import Image, ImageDraw, ImageOps  # noqa: E402

from upscaler.engine import (  # noqa: E402
    NO_WINDOW, RESOLUTIONS, VIDEO_EXTS, Cancelled, Job, JobSettings, probe, target_size, upscale_video,
)
from upscaler.image import (  # noqa: E402
    IMAGE_EXTS, IMAGE_RESOLUTIONS, ImageSettings, probe_image, upscale_image,
)
from upscaler import backend  # noqa: E402
from upscaler.catalog import MODEL_CATALOG, SPEED_COLORS  # noqa: E402
from upscaler.engine import encoder_label, pick_encoder  # noqa: E402

APP_NAME = "Pam Upscale"

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:
    TkinterDnD = None

SETTINGS_FILE = os.path.join(ROOT, "settings.json")
ASSETS = os.path.join(ROOT, "assets")

# ------------------------------------------------------------------------------------------ theme
C = dict(
    bg="#0c0e13", side="#11141b", card="#161a23", card2="#1d2230", hover="#232938", border="#262d3d",
    # màu thương hiệu PAM Media
    accent="#F46F22", accent_h="#DB5E15", accent_soft="#2C1A10", accent_txt="#FFA463", cyan="#F7941D",
    text="#e9ebf1", muted="#8a91a6", dim="#5d6478", ok="#22c55e", ok_soft="#10291b", err="#f05252",
    err_soft="#2e1418", warn="#f5a524", warn_soft="#2e2310",
)
ctk.set_appearance_mode("dark")

MODEL_GROUPS = [
    ("NVIDIA RTX VIDEO  ·  SIÊU NHANH", ["rtx_ultra", "rtx_highbitrate", "rtx_high"]),
    ("REAL-ESRGAN  ·  HOẠT HÌNH & ĐA NĂNG", ["anime_video", "general"]),
    ("REAL-CUGAN  ·  HOẠT HÌNH 2D", ["cugan_cons", "cugan_dn3"]),
    ("CHẤT LƯỢNG CAO  ·  CHẬM", ["anime_hq", "nomos_plksr", "general_hq", "nomos_dat2"]),
]


def speed_hint(m, kind: str) -> str:
    """'~10 fps (RTX 3060, 720p) · clip Flow 8 giây ≈ 20 giây'."""
    if kind == "video" and m.clip_note:
        return f"{m.speed} → {m.clip_note}"
    try:
        fps = float(m.speed.strip("~ fps"))
    except ValueError:
        return m.speed
    if kind == "image":
        per = 1 / fps
        return f"{m.speed} → ảnh 720p ≈ {'<1' if per < 1 else f'{per:.0f}'} giây"
    sec = 192 / fps  # clip 8 giây × 24 fps
    est = f"{sec:.0f} giây" if sec < 90 else f"{sec / 60:.0f} phút" if sec < 5400 else f"{sec / 3600:.1f} giờ"
    return f"{m.speed} → clip Flow 8 giây ≈ {est}"

PAGES = {
    "video": dict(
        title="Upscale Video", subtitle="Làm nét video AI từ Flow, Veo, Kling… bằng GPU",
        exts=VIDEO_EXTS, noun="video",
        res=[("1080", "1080p"), ("1440", "2K"), ("2160", "4K"), ("x2", "×2"), ("x4", "×4")],
        fmt_title="ĐỊNH DẠNG", fmt=[("h264", "H.264"), ("hevc", "H.265")],
        q_title="CHẤT LƯỢNG (CQ)", q_range=(12, 30), q_hint="Càng thấp càng nét, file nặng hơn",
        defaults=dict(model="rtx_ultra", res="1080", fmt="h264", q=18, parallel=2, out_dir=""),
        prefer=["rtx_ultra", "anime_video", "general"],
    ),
    "image": dict(
        title="Upscale Ảnh", subtitle="Phóng to ảnh, ảnh bìa, khung hình AI mà vẫn sắc nét",
        exts=IMAGE_EXTS, noun="ảnh",
        res=[(k, v[0]) for k, v in IMAGE_RESOLUTIONS.items()],
        fmt_title="ĐỊNH DẠNG LƯU", fmt=[("same", "Gốc"), ("png", "PNG"), ("jpg", "JPG"), ("webp", "WebP")],
        q_title="CHẤT LƯỢNG JPG/WEBP", q_range=(60, 100), q_hint="Áp dụng khi lưu JPG hoặc WebP",
        defaults=dict(model="nomos_plksr", res="x4", fmt="same", q=95, parallel=2, out_dir=""),
        prefer=["nomos_plksr", "general_hq", "anime_hq"],
    ),
}


# ------------------------------------------------------------------------------------------ icons
def _canvas(s=96):
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def draw_icon(name: str, color: str, size: int, pil_only=False):
    s = 96
    img, d = _canvas(s)
    w = 7
    if name == "video":
        d.rounded_rectangle((8, 18, 88, 78), 14, outline=color, width=w)
        d.polygon([(40, 34), (40, 62), (64, 48)], fill=color)
    elif name == "image":
        d.rounded_rectangle((8, 14, 88, 82), 14, outline=color, width=w)
        d.ellipse((58, 26, 72, 40), fill=color)
        d.polygon([(14, 76), (38, 44), (56, 66), (66, 56), (84, 76)], fill=color)
    elif name == "folder":
        d.rounded_rectangle((8, 26, 88, 80), 10, outline=color, width=w)
        d.rounded_rectangle((8, 16, 44, 34), 8, fill=color)
    elif name == "plus":
        d.rounded_rectangle((44, 14, 52, 82), 4, fill=color)
        d.rounded_rectangle((14, 44, 82, 52), 4, fill=color)
    elif name == "close":
        d.line((24, 24, 72, 72), fill=color, width=9)
        d.line((72, 24, 24, 72), fill=color, width=9)
    elif name == "play":
        d.polygon([(26, 14), (26, 82), (82, 48)], fill=color)
    elif name == "stop":
        d.rounded_rectangle((20, 20, 76, 76), 10, fill=color)
    elif name == "broom":
        d.line((20, 20, 60, 60), fill=color, width=8)
        d.polygon([(50, 58), (66, 42), (88, 76), (76, 88)], fill=color)
    elif name == "upload":
        d.line((48, 16, 48, 60), fill=color, width=8)
        d.polygon([(28, 34), (48, 12), (68, 34)], fill=color)
        d.line((14, 58, 14, 82, 82, 82, 82, 58), fill=color, width=8, joint="curve")
    elif name == "chip":
        d.rounded_rectangle((22, 22, 74, 74), 8, outline=color, width=w)
        d.rounded_rectangle((36, 36, 60, 60), 4, fill=color)
        for p in (34, 48, 62):
            d.line((p, 8, p, 22), fill=color, width=5)
            d.line((p, 74, p, 88), fill=color, width=5)
            d.line((8, p, 22, p), fill=color, width=5)
            d.line((74, p, 88, p), fill=color, width=5)
    if pil_only:
        return img
    img = img.resize((size * 2, size * 2), Image.LANCZOS)
    return ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))


def rounded_thumb(pil: Image.Image, w=128, h=72, r=10) -> Image.Image:
    W, H = w * 2, h * 2
    if pil.mode in ("RGBA", "LA", "PA") or (pil.mode == "P" and "transparency" in pil.info):
        pil = pil.convert("RGBA")
        pil.thumbnail((W, H), Image.LANCZOS)
        checker = Image.new("RGBA", pil.size, "#3a4052")
        dc = ImageDraw.Draw(checker)
        for yy in range(0, pil.height, 12):
            for xx in range((yy // 12) % 2 * 12, pil.width, 24):
                dc.rectangle((xx, yy, xx + 11, yy + 11), fill="#2a2f3d")
        pil = Image.alpha_composite(checker, pil).convert("RGB")
    else:
        pil = pil.convert("RGB")
        pil.thumbnail((W, H), Image.LANCZOS)
    canvas = Image.new("RGB", (W, H), C["card2"])
    canvas.paste(pil, ((W - pil.width) // 2, (H - pil.height) // 2))
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, W - 1, H - 1), r * 2, fill=255)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out.paste(canvas, (0, 0), mask)
    return out


def make_thumb(path: str, kind: str) -> Image.Image | None:
    try:
        if kind == "image":
            with Image.open(path) as im:
                im = ImageOps.exif_transpose(im)
                im.draft("RGB", (512, 512))
                return rounded_thumb(im.copy())
        for ss in ("0.5", None):
            cmd = ["ffmpeg", "-v", "error"] + (["-ss", ss] if ss else []) + [
                "-i", path, "-frames:v", "1", "-vf", "scale=320:-2", "-f", "image2pipe", "-vcodec", "png", "pipe:1"]
            r = subprocess.run(cmd, capture_output=True, creationflags=NO_WINDOW, timeout=30)
            if r.stdout:
                return rounded_thumb(Image.open(io.BytesIO(r.stdout)))
    except Exception:
        pass
    return None


def fmt_time(sec: float) -> str:
    if not sec or sec <= 0 or sec != sec:
        return ""
    sec = int(sec)
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60}:{sec % 60:02d}"


def short(name: str, n=58) -> str:
    return name if len(name) <= n else name[: n - 12] + "…" + name[-11:]


# ------------------------------------------------------------------------------------------ job card
STATE_STYLE = {
    "wait": ("Chờ", C["muted"], C["card2"]),
    "run": ("Đang xử lý", C["accent_txt"], C["accent_soft"]),
    "done": ("Hoàn tất", C["ok"], C["ok_soft"]),
    "error": ("Lỗi", C["err"], C["err_soft"]),
    "stopped": ("Đã dừng", C["warn"], C["warn_soft"]),
}


class ModelPicker(ctk.CTkFrame):
    """Nút chọn model + bảng danh sách có tên, tốc độ, mô tả (thay cho dropdown đơn giản)."""

    def __init__(self, master, app, key, on_change, kind="video"):
        super().__init__(master, fg_color=C["card2"], corner_radius=10, border_width=1, border_color=C["border"])
        self.app, self.key, self.on_change, self.kind = app, key, on_change, kind
        self.avail: dict = {}
        self.popup = None
        self.grid_columnconfigure(0, weight=1)
        self.name = ctk.CTkLabel(self, text="", font=app.f["b13"], text_color=C["text"], anchor="w",
                                 justify="left", wraplength=220)
        self.name.grid(row=0, column=0, sticky="w", padx=(12, 4), pady=(8, 0))
        self.tag = ctk.CTkLabel(self, text="", font=app.f["b11"], anchor="w")
        self.tag.grid(row=1, column=0, sticky="w", padx=12, pady=(0, 8))
        self.chev = ctk.CTkLabel(self, text="▾", font=app.f["b16"], text_color=C["muted"])
        self.chev.grid(row=0, column=1, rowspan=2, padx=(0, 12))
        for w in (self, self.name, self.tag, self.chev):
            w.bind("<Button-1>", lambda _e: self.toggle())
            w.bind("<Enter>", lambda _e: self.configure(border_color=C["accent"]))
            w.bind("<Leave>", lambda _e: self.configure(border_color=C["border"]))
            w.configure(cursor="hand2")
        self._render()

    def _render(self):
        m = MODEL_CATALOG[self.key]
        self.name.configure(text=m.label)
        self.tag.configure(text=f"●  {m.speed_tag}  ·  {m.speed}", text_color=SPEED_COLORS[m.speed_tag])

    def set(self, key):
        self.key = key
        self._render()
        self.on_change(key)

    def set_available(self, avail: dict):
        self.avail = avail

    # -------------------------------------------------------------- popup
    def toggle(self):
        if self.popup is not None:
            self.close()
        else:
            self.open()

    def close(self):
        if self.popup is not None:
            try:
                self.popup.grab_release()
                self.popup.destroy()
            except Exception:
                pass
            self.popup = None

    def open(self):
        app = self.app
        scale = ctk.ScalingTracker.get_window_scaling(self)
        W, H = 470, 560
        top = ctk.CTkToplevel(self)
        top.withdraw()
        top.overrideredirect(True)
        top.configure(fg_color=C["border"])
        x = self.winfo_rootx() + self.winfo_width() - int(W * scale)
        y = self.winfo_rooty() + self.winfo_height() + 4
        screen_h = self.winfo_screenheight()
        if y + H * scale > screen_h - 40:
            H = max(260, int((screen_h - 40 - y) / scale))
        top.geometry(f"{W}x{H}+{max(0, x)}+{y}")
        body = ctk.CTkScrollableFrame(top, fg_color=C["card"], corner_radius=12,
                                      scrollbar_button_color=C["card2"], scrollbar_button_hover_color=C["hover"])
        body.pack(fill="both", expand=True, padx=1, pady=1)
        ctk.CTkLabel(body, text="Tốc độ đo trên RTX 3060, video 720p → 1080p. Card AMD/Intel sẽ chậm hơn 2–5 lần.",
                     font=app.f["11"], text_color=C["muted"], anchor="w").pack(fill="x", padx=14, pady=(10, 0))

        for title, keys in MODEL_GROUPS:
            keys = [k for k in keys if self.kind == "image" or MODEL_CATALOG[k].video]
            if not keys:
                continue
            ctk.CTkLabel(body, text=title, font=app.f["b11"], text_color=C["dim"], anchor="w").pack(
                fill="x", padx=14, pady=(12, 4))
            for k in keys:
                self._item(body, top, k)

        self.popup = top
        top.transient(self.winfo_toplevel())
        top.deiconify()
        top.attributes("-topmost", True)
        top.lift()
        top.focus_force()
        top.grab_set()
        top.bind("<Escape>", lambda _e: self.close())

        def outside(e):
            px, py = top.winfo_rootx(), top.winfo_rooty()
            if not (px <= e.x_root < px + top.winfo_width() and py <= e.y_root < py + top.winfo_height()):
                self.close()
        top.bind("<Button-1>", outside, add="+")

    def _item(self, body, top, k):
        app = self.app
        m = MODEL_CATALOG[k]
        ok, why = self.avail.get(k, (True, ""))
        sel = k == self.key
        row = ctk.CTkFrame(body, fg_color=C["accent_soft"] if sel else "transparent", corner_radius=10)
        row.pack(fill="x", padx=6, pady=1)
        row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(row, text=m.label, font=app.f["b13"], text_color=C["text"] if ok else C["dim"],
                     anchor="w").grid(row=0, column=0, sticky="w", padx=(12, 6), pady=(8, 0))
        ctk.CTkLabel(row, text=f"{m.speed_tag} · {m.speed}", font=app.f["b11"],
                     text_color=SPEED_COLORS[m.speed_tag] if ok else C["dim"]).grid(
            row=0, column=1, sticky="e", padx=(0, 6), pady=(8, 0))
        ctk.CTkLabel(row, text="✓" if sel else " ", font=app.f["b15"], text_color=C["accent_txt"], width=18).grid(
            row=0, column=2, rowspan=2, padx=(0, 10))
        ctk.CTkLabel(row, text=m.desc, font=app.f["12"], text_color=C["muted"] if ok else C["dim"], anchor="w",
                     justify="left", wraplength=380).grid(row=1, column=0, columnspan=2, sticky="w", padx=12,
                                                         pady=(0, 2 if not ok else 8))
        if not ok:
            ctk.CTkLabel(row, text=f"Không dùng được trên máy này: {why}", font=app.f["11"], text_color=C["warn"],
                         anchor="w").grid(row=2, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 8))

        def enter(_e):
            if not sel:
                row.configure(fg_color=C["hover"])

        def leave(_e):
            if not sel:
                row.configure(fg_color="transparent")

        def pick(_e):
            if ok:
                self.close()
                self.set(k)

        for w in [row, *row.winfo_children()]:
            w.bind("<Enter>", enter, add="+")
            w.bind("<Leave>", leave, add="+")
            w.bind("<Button-1>", pick, add="+")
            if ok:
                w.configure(cursor="hand2")


class JobCard(ctk.CTkFrame):
    def __init__(self, master, app, page, jid, job: Job):
        super().__init__(master, fg_color=C["card"], corner_radius=14, border_width=1, border_color=C["border"])
        self.app, self.page, self.jid, self.job = app, page, jid, job
        self.grid_columnconfigure(1, weight=1)

        ph = Image.new("RGBA", (256, 144), (0, 0, 0, 0))
        ImageDraw.Draw(ph).rounded_rectangle((0, 0, 255, 143), 20, fill=C["card2"])
        self.thumb = ctk.CTkLabel(self, text="", image=ctk.CTkImage(ph, ph, size=(128, 72)))
        self.thumb.grid(row=0, column=0, rowspan=3, padx=(12, 14), pady=12)

        self.name = ctk.CTkLabel(self, text=short(os.path.basename(job.path)), font=app.f["b13"],
                                 text_color=C["text"], anchor="w")
        self.name.grid(row=0, column=1, sticky="sw", pady=(14, 0))
        self.meta = ctk.CTkLabel(self, text="Đang đọc thông tin…", font=app.f["12"], text_color=C["muted"],
                                 anchor="w", justify="left")
        self.meta.grid(row=1, column=1, sticky="nw")

        self.bar = ctk.CTkProgressBar(self, height=6, corner_radius=3, fg_color=C["card2"],
                                      progress_color=C["accent"])
        self.bar.set(0)
        self.bar.grid(row=2, column=1, columnspan=2, sticky="ew", pady=(4, 14))

        right = ctk.CTkFrame(self, fg_color="transparent")
        right.grid(row=0, column=2, rowspan=2, sticky="ne", padx=(8, 0), pady=(12, 0))
        self.badge = ctk.CTkLabel(right, text="", font=app.f["b11"], corner_radius=10, height=24, padx=10)
        self.badge.pack(side="right")
        self.detail = ctk.CTkLabel(self, text="", font=app.f["12"], text_color=C["muted"], anchor="e")
        self.detail.grid(row=1, column=2, sticky="ne", padx=(8, 0))

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.grid(row=0, column=3, rowspan=3, padx=(10, 12))
        self.open_btn = ctk.CTkButton(btns, text="", image=app.icons["folder_m"], width=34, height=34,
                                      corner_radius=10, fg_color=C["card2"], hover_color=C["hover"],
                                      command=self.open_result)
        self.rm_btn = ctk.CTkButton(btns, text="", image=app.icons["close_m"], width=34, height=34,
                                    corner_radius=10, fg_color="transparent", hover_color=C["err_soft"],
                                    command=lambda: page.remove_job(jid))
        self.rm_btn.pack(side="right")
        self.state = None
        self.set_state("wait")

    def set_thumb(self, pil):
        self.thumb.configure(image=ctk.CTkImage(pil, pil, size=(128, 72)))

    def set_meta(self, text, color=None):
        self.meta.configure(text=text, text_color=color or C["muted"])

    def set_state(self, state, detail=""):
        self.state = state
        label, fg, bg = STATE_STYLE[state]
        self.badge.configure(text=label, text_color=fg, fg_color=bg)
        self.detail.configure(text=detail)
        self.bar.configure(progress_color={"done": C["ok"], "error": C["err"], "stopped": C["warn"]}.get(
            state, C["accent"]))
        if state == "done":
            self.bar.set(1)
            self.open_btn.pack(side="right", padx=(0, 6))
        else:
            self.open_btn.pack_forget()
        if state == "wait":
            self.bar.set(0)

    def set_progress(self, frac, detail=""):
        self.bar.set(max(0.0, min(1.0, frac)))
        self.detail.configure(text=detail)

    def open_result(self):
        if self.job.out_path and os.path.exists(self.job.out_path):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(self.job.out_path)])


# ------------------------------------------------------------------------------------------ page
class Page(ctk.CTkFrame):
    def __init__(self, master, app, kind: str, cfg: dict):
        super().__init__(master, fg_color="transparent")
        self.app, self.kind, self.spec = app, kind, PAGES[kind]
        self.cfg = {**self.spec["defaults"], **(cfg or {})}
        self.jobs: dict[int, Job] = {}
        self.cards: dict[int, JobCard] = {}
        self.state: dict[int, str] = {}
        self.progress: dict[int, float] = {}
        self.ids = itertools.count(1)
        self.running = False
        self.active = 0
        self.stop_flag = threading.Event()
        self.work_q: queue.Queue = queue.Queue()
        self.batch: list[int] = []

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._build_header()
        self._build_list()
        self._build_panel()
        self._refresh_empty()

    # -------------------------------------------------------------- build
    def _build_header(self):
        app, sp = self.app, self.spec
        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=(28, 16), pady=(24, 0))
        ctk.CTkLabel(head, text=sp["title"], font=app.f["b24"], text_color=C["text"], anchor="w").pack(fill="x")
        ctk.CTkLabel(head, text=sp["subtitle"], font=app.f["13"], text_color=C["muted"], anchor="w").pack(fill="x")
        self.toolbar = bt = ctk.CTkFrame(self, fg_color="transparent")
        ctk.CTkButton(bt, text="Dọn mục xong", image=app.icons["broom"], font=app.f["13"], height=38, width=0,
                      corner_radius=10, fg_color="transparent", hover_color=C["hover"], text_color=C["muted"],
                      command=self.clear_done).pack(side="left", padx=(0, 8))
        ctk.CTkButton(bt, text="Thư mục", image=app.icons["folder"], font=app.f["13"], height=38, width=0,
                      corner_radius=10, fg_color=C["card2"], hover_color=C["hover"], border_width=1,
                      border_color=C["border"], command=self.add_folder).pack(side="left", padx=(0, 8))
        ctk.CTkButton(bt, text=f"Thêm {sp['noun']}", image=app.icons["plus"], font=app.f["b13"], height=38,
                      width=0, corner_radius=10, fg_color=C["accent"], hover_color=C["accent_h"],
                      command=self.add_files).pack(side="left")

    def _build_list(self):
        app, sp = self.app, self.spec
        box = ctk.CTkFrame(self, fg_color="transparent")
        box.grid(row=1, column=0, sticky="nsew", padx=(28, 16), pady=(0, 24))
        box.grid_columnconfigure(0, weight=1)
        box.grid_rowconfigure(1, weight=1)
        bar = ctk.CTkFrame(box, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", pady=(16, 12))
        self.summary = ctk.CTkLabel(bar, text="", font=app.f["13"], text_color=C["muted"], anchor="w")
        self.summary.pack(side="left")
        self.toolbar.pack(in_=bar, side="right")
        self.toolbar.lift()

        self.drop = ctk.CTkFrame(box, fg_color=C["card"], corner_radius=18, border_width=2,
                                 border_color=C["border"])
        inner = ctk.CTkFrame(self.drop, fg_color="transparent")
        inner.place(relx=0.5, rely=0.5, anchor="center")
        circle = ctk.CTkFrame(inner, width=88, height=88, corner_radius=44, fg_color=C["accent_soft"])
        circle.pack()
        circle.pack_propagate(False)
        ctk.CTkLabel(circle, text="", image=app.icons["upload_xl"]).place(relx=0.5, rely=0.5, anchor="center")
        ctk.CTkLabel(inner, text=f"Kéo & thả {sp['noun']} vào đây", font=app.f["b18"],
                     text_color=C["text"]).pack(pady=(18, 4))
        exts = ", ".join(sorted(e[1:].upper() for e in sp["exts"] if e not in (".jpeg", ".tiff", ".m4v")))
        ctk.CTkLabel(inner, text=f"Hỗ trợ {exts} · thả cả thư mục cũng được", font=app.f["12"],
                     text_color=C["muted"]).pack()
        ctk.CTkButton(inner, text=f"Chọn {sp['noun']} từ máy", font=app.f["b13"], height=40, corner_radius=10,
                      fg_color=C["accent"], hover_color=C["accent_h"], command=self.add_files).pack(pady=(18, 0))

        self.list = ctk.CTkScrollableFrame(box, fg_color="transparent", scrollbar_button_color=C["card2"],
                                           scrollbar_button_hover_color=C["hover"])
        self.list.grid_columnconfigure(0, weight=1)

    def _section(self, parent, title):
        ctk.CTkLabel(parent, text=title, font=self.app.f["b11"], text_color=C["dim"], anchor="w").pack(
            fill="x", padx=20, pady=(16, 6))

    def _build_panel(self):
        app, sp, cfg = self.app, self.spec, self.cfg
        p = ctk.CTkFrame(self, fg_color=C["card"], corner_radius=18, width=330, border_width=1,
                         border_color=C["border"])
        p.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=(0, 24), pady=24)
        p.pack_propagate(False)
        ctk.CTkLabel(p, text="Thiết lập", font=app.f["b16"], text_color=C["text"], anchor="w").pack(
            fill="x", padx=20, pady=(18, 4))
        outer = p
        run = ctk.CTkFrame(outer, fg_color="transparent")
        run.pack(side="bottom", fill="x", padx=20, pady=20)
        p = ctk.CTkScrollableFrame(outer, fg_color="transparent", scrollbar_button_color=C["card2"],
                                   scrollbar_button_hover_color=C["hover"])
        p.pack(fill="both", expand=True, padx=(0, 4))

        # model
        self._section(p, "MODEL AI")
        key = cfg["model"]
        if key not in MODEL_CATALOG or (self.kind == "video" and not MODEL_CATALOG[key].video):
            key = sp["defaults"]["model"]
        self.picker = ModelPicker(p, app, key, on_change=lambda _k: self._on_model(), kind=self.kind)
        self.picker.pack(fill="x", padx=20)
        self.model_desc = ctk.CTkLabel(p, text="", font=app.f["12"], text_color=C["muted"], anchor="w",
                                       justify="left", wraplength=270)
        self.model_desc.pack(fill="x", padx=20, pady=(8, 0))
        self.model_speed = ctk.CTkLabel(p, text="", font=app.f["b12"], anchor="w", justify="left", wraplength=270)
        self.model_speed.pack(fill="x", padx=20, pady=(4, 0))
        self.model_lic = ctk.CTkLabel(p, text="", font=app.f["11"], text_color=C["dim"], anchor="w",
                                      justify="left", wraplength=270)
        self.model_lic.pack(fill="x", padx=20, pady=(2, 0))
        self._on_model()

        # resolution
        self._section(p, "ĐỘ PHÂN GIẢI ĐẦU RA")
        self.res_by_label = {lbl: k for k, lbl in sp["res"]}
        self.res_var = ctk.StringVar(value=dict(sp["res"]).get(cfg["res"], sp["res"][0][1]))
        self._seg(p, self.res_var, [lbl for _, lbl in sp["res"]], lambda _v: self._refresh_meta())

        # format
        self._section(p, sp["fmt_title"])
        self.fmt_by_label = {lbl: k for k, lbl in sp["fmt"]}
        self.fmt_var = ctk.StringVar(value=dict(sp["fmt"]).get(cfg["fmt"], sp["fmt"][0][1]))
        self._seg(p, self.fmt_var, [lbl for _, lbl in sp["fmt"]])

        # quality
        lo, hi = sp["q_range"]
        self.q_var = ctk.IntVar(value=int(cfg["q"]))
        self._slider(p, sp["q_title"], self.q_var, lo, hi, sp["q_hint"])

        # parallel
        self.par_var = ctk.IntVar(value=int(cfg["parallel"]))
        self._slider(p, "CHẠY CÙNG LÚC", self.par_var, 1, 6, f"Số {self.spec['noun']} xử lý song song trên GPU")

        # output
        self._section(p, "LƯU VÀO")
        row = ctk.CTkFrame(p, fg_color="transparent")
        row.pack(fill="x", padx=20)
        self.out_var = ctk.StringVar(value=cfg["out_dir"])
        ctk.CTkEntry(row, textvariable=self.out_var, height=36, corner_radius=10, font=app.f["12"],
                     fg_color=C["card2"], border_color=C["border"],
                     placeholder_text="Thư mục “upscaled” cạnh file gốc").pack(side="left", fill="x", expand=True)
        ctk.CTkButton(row, text="", image=app.icons["folder"], width=36, height=36, corner_radius=10,
                      fg_color=C["card2"], hover_color=C["hover"], command=self.pick_out).pack(side="left", padx=(6, 0))

        # run area
        self.overall = ctk.CTkProgressBar(run, height=8, corner_radius=4, fg_color=C["card2"],
                                          progress_color=C["cyan"])
        self.overall.set(0)
        self.run_status = ctk.CTkLabel(run, text="Sẵn sàng", font=app.f["12"], text_color=C["muted"], anchor="w")
        self.run_status.pack(fill="x", pady=(6, 12))
        self.start_btn = ctk.CTkButton(run, text="  Bắt đầu upscale", image=app.icons["play"], font=app.f["b15"],
                                       height=48, corner_radius=12, fg_color=C["accent"],
                                       hover_color=C["accent_h"], command=self.start)
        self.start_btn.pack(fill="x")
        self.stop_btn = ctk.CTkButton(run, text="  Dừng lại", image=app.icons["stop"], font=app.f["b15"],
                                      height=48, corner_radius=12, fg_color=C["err_soft"], hover_color="#3d1a1f",
                                      text_color=C["err"], border_width=1, border_color="#5a2229",
                                      command=self.stop)

    def _seg(self, parent, var, values, command=None):
        ctk.CTkSegmentedButton(parent, variable=var, values=values, height=34, corner_radius=10,
                               font=self.app.f["12"], fg_color=C["card2"], selected_color=C["accent"],
                               selected_hover_color=C["accent_h"], unselected_color=C["card2"],
                               unselected_hover_color=C["hover"], command=command).pack(fill="x", padx=20)

    def _slider(self, parent, title, var, lo, hi, hint):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=(16, 2))
        ctk.CTkLabel(row, text=title, font=self.app.f["b11"], text_color=C["dim"]).pack(side="left")
        val = ctk.CTkLabel(row, text=str(var.get()), font=self.app.f["b13"], text_color=C["accent_txt"])
        val.pack(side="right")
        ctk.CTkSlider(parent, from_=lo, to=hi, number_of_steps=hi - lo, variable=var, height=16,
                      button_color=C["accent"], button_hover_color=C["accent_txt"], progress_color=C["accent"],
                      fg_color=C["card2"], command=lambda v: val.configure(text=str(int(v)))).pack(
            fill="x", padx=14)
        ctk.CTkLabel(parent, text=hint, font=self.app.f["11"], text_color=C["dim"], anchor="w").pack(
            fill="x", padx=20)

    # -------------------------------------------------------------- settings
    def _on_model(self):
        m = MODEL_CATALOG[self.picker.key]
        self.model_desc.configure(text=m.desc)
        self.model_speed.configure(text=f"Tốc độ: {m.speed_tag} · {speed_hint(m, self.kind)}",
                                   text_color=SPEED_COLORS[m.speed_tag])
        self.model_lic.configure(text=f"Giấy phép: {m.license}")

    def refresh_models(self, be: str):
        """Cập nhật model nào dùng được trên thiết bị hiện tại."""
        avail = {k: backend.model_available(k, be) for k in MODEL_CATALOG}
        self.picker.set_available(avail)
        if not avail[self.picker.key][0]:
            for k in self.spec["prefer"]:
                if avail[k][0]:
                    self.picker.set(k)
                    break

    def model_key(self):
        return self.picker.key

    def res_mode(self):
        key = self.res_by_label.get(self.res_var.get(), self.spec["defaults"]["res"])
        return key, (RESOLUTIONS if self.kind == "video" else IMAGE_RESOLUTIONS)[key][1]

    def fmt_key(self):
        return self.fmt_by_label.get(self.fmt_var.get(), self.spec["defaults"]["fmt"])

    def export_cfg(self):
        return dict(model=self.model_key(), res=self.res_mode()[0], fmt=self.fmt_key(), q=int(self.q_var.get()),
                    parallel=int(self.par_var.get()), out_dir=self.out_var.get().strip())

    def make_settings(self):
        mode = self.res_mode()[1]
        if self.kind == "video":
            return JobSettings(resolution=mode, codec=self.fmt_key(), cq=int(self.q_var.get()),
                               out_dir=self.out_var.get().strip())
        return ImageSettings(resolution=mode, fmt=self.fmt_key(), quality=int(self.q_var.get()),
                             out_dir=self.out_var.get().strip())

    def pick_out(self):
        d = filedialog.askdirectory(title="Chọn thư mục lưu")
        if d:
            self.out_var.set(os.path.normpath(d))

    # -------------------------------------------------------------- add / remove
    def add_files(self):
        exts = " ".join("*" + e for e in sorted(self.spec["exts"]))
        paths = filedialog.askopenfilenames(title=f"Chọn {self.spec['noun']}",
                                            filetypes=[(self.spec["noun"].capitalize(), exts), ("Tất cả", "*.*")])
        self.add_paths(paths)

    def add_folder(self):
        d = filedialog.askdirectory(title="Chọn thư mục")
        if d:
            self.add_paths([os.path.join(d, f) for f in sorted(os.listdir(d))])

    def accepts(self, path):
        return os.path.splitext(path)[1].lower() in self.spec["exts"]

    def add_paths(self, paths) -> int:
        existing = {os.path.normcase(j.path) for j in self.jobs.values()}
        added = 0
        for p in paths:
            if not os.path.isfile(p) or not self.accepts(p):
                continue
            p = os.path.abspath(p)
            if os.path.normcase(p) in existing:
                continue
            existing.add(os.path.normcase(p))
            jid = next(self.ids)
            job = Job(path=p)
            self.jobs[jid] = job
            self.state[jid] = "wait"
            card = JobCard(self.list, self.app, self, jid, job)
            card.pack(fill="x", pady=(0, 8), padx=(0, 6))
            self.cards[jid] = card
            self.app.thumb_pool.submit(self._load_info, jid, job)
            if self.running:
                self.work_q.put(jid)
                self.batch.append(jid)
            added += 1
        self._refresh_empty()
        return added

    def _load_info(self, jid, job):
        try:
            job.info = probe(job.path) if self.kind == "video" else probe_image(job.path)
            self.app.post(self, "info", jid, None)
        except Exception as e:
            self.app.post(self, "info_err", jid, str(e))
            return
        thumb = make_thumb(job.path, self.kind)
        if thumb is not None:
            self.app.post(self, "thumb", jid, thumb)

    def remove_job(self, jid):
        if self.state.get(jid) == "run":
            self.jobs[jid].cancel.set()
            return
        card = self.cards.pop(jid, None)
        if card:
            card.destroy()
        self.jobs.pop(jid, None)
        self.state.pop(jid, None)
        self._refresh_empty()

    def clear_done(self):
        for jid in [j for j, s in self.state.items() if s == "done"]:
            self.remove_job(jid)

    def _refresh_empty(self):
        if self.jobs:
            self.drop.grid_forget()
            self.list.grid(row=1, column=0, sticky="nsew")
        else:
            self.list.grid_forget()
            self.drop.grid(row=1, column=0, sticky="nsew")
        self._refresh_summary()

    def _refresh_summary(self):
        n = len(self.jobs)
        cnt = {k: sum(1 for s in self.state.values() if s == k) for k in ("run", "done", "error")}
        parts = [f"{n} {self.spec['noun']}"] if n else []
        if cnt["run"]:
            parts.append(f"{cnt['run']} đang xử lý")
        if cnt["done"]:
            parts.append(f"{cnt['done']} hoàn tất")
        if cnt["error"]:
            parts.append(f"{cnt['error']} lỗi")
        self.summary.configure(text="  ·  ".join(parts))
        self.app.update_nav_badge(self.kind, cnt["run"])

    def _meta_text(self, job):
        i = job.info
        if i is None:
            return ""
        tw, th = target_size(i.width, i.height, self.res_mode()[1])
        if self.kind == "video":
            extra = f"  ·  {fmt_time(i.duration) or '?'}  ·  {i.fps_float:.0f} fps"
        else:
            extra = f"  ·  {os.path.splitext(job.path)[1][1:].upper()}" + ("  ·  trong suốt" if i.has_alpha else "")
        return f"{i.width}×{i.height}  →  {tw}×{th}{extra}"

    def _refresh_meta(self):
        for jid, job in self.jobs.items():
            if self.state.get(jid) in ("wait", "stopped") and job.info:
                self.cards[jid].set_meta(self._meta_text(job))

    # -------------------------------------------------------------- run
    def start(self):
        todo = [jid for jid in self.cards if self.state.get(jid) in ("wait", "error", "stopped")]
        if not todo:
            messagebox.showinfo(APP_NAME, f"Chưa có {self.spec['noun']} nào cần xử lý.")
            return
        try:
            self.run_backend = backend.resolve(self.app.device_pref())
        except Exception as e:
            messagebox.showerror(APP_NAME, str(e))
            return
        if self.run_backend == "cpu" and self.kind == "video" and not messagebox.askyesno(
                APP_NAME, "Máy không có GPU dùng được – xử lý video bằng CPU sẽ RẤT chậm "
                          "(vài giây mỗi khung hình).\n\nVẫn tiếp tục?"):
            return
        self.app.save_cfg()
        self.running = True
        self.stop_flag.clear()
        self.run_settings = self.make_settings()
        self.run_model = self.model_key()
        self.work_q = queue.Queue()
        self.batch = list(todo)
        for jid in todo:
            self.jobs[jid].cancel.clear()
            self.state[jid] = "wait"
            self.progress[jid] = 0.0
            self.cards[jid].set_state("wait")
            if self.jobs[jid].info:
                self.cards[jid].set_meta(self._meta_text(self.jobs[jid]))
            self.work_q.put(jid)
        self.start_btn.pack_forget()
        self.stop_btn.pack(fill="x")
        self.overall.set(0)
        if not self.overall.winfo_ismapped():
            self.overall.pack(fill="x", before=self.run_status)
        self.run_status.configure(text="Đang chuẩn bị…")
        self.t_start = time.time()
        n = max(1, int(self.par_var.get()))
        self.active = n
        for _ in range(n):
            threading.Thread(target=self._worker, daemon=True).start()

    def stop(self):
        self.stop_flag.set()
        for jid, job in self.jobs.items():
            if self.state.get(jid) == "run":
                job.cancel.set()
        self.run_status.configure(text="Đang dừng…")

    def _worker(self):
        post = self.app.post
        try:
            model = backend.get_runner(self.run_model, self.run_backend, lambda s: post(self, "status", None, s))
        except Exception as e:
            post(self, "fatal", None, f"Không nạp được model: {e}")
            post(self, "worker_done", None, None)
            return
        post(self, "status", None, "Đang xử lý…")
        while not self.stop_flag.is_set():
            try:
                jid = self.work_q.get_nowait()
            except queue.Empty:
                break
            job = self.jobs.get(jid)
            if job is None or self.state.get(jid) != "wait":
                continue
            self.state[jid] = "run"
            post(self, "run", jid, None)
            t0 = time.time()
            try:
                if self.kind == "video":
                    if job.info is None:
                        job.info = probe(job.path)
                    upscale_video(job, model, self.run_settings,
                                  lambda d, t, f, _j=jid: post(self, "prog_v", _j, (d, t, f)))
                else:
                    if job.info is None:
                        job.info = probe_image(job.path)
                    upscale_image(job, model, self.run_settings,
                                  lambda k, n, _f, _j=jid: post(self, "prog_i", _j, (k, n)))
                self.state[jid] = "done"
                post(self, "done", jid, time.time() - t0)
            except Cancelled:
                self.state[jid] = "stopped"
                post(self, "stopped", jid, None)
            except Exception as e:
                if job.cancel.is_set():
                    self.state[jid] = "stopped"
                    post(self, "stopped", jid, None)
                else:
                    traceback.print_exc()
                    self.state[jid] = "error"
                    post(self, "error", jid, str(e))
        post(self, "worker_done", None, None)

    def handle(self, kind, jid, data):
        card = self.cards.get(jid) if jid is not None else None
        if jid is not None and card is None:
            if kind != "worker_done":
                return
        if kind == "info":
            card.set_meta(self._meta_text(self.jobs[jid]))
        elif kind == "info_err":
            self.state[jid] = "error"
            card.set_state("error")
            card.set_meta("Không đọc được file: " + data.splitlines()[0][:90], C["err"])
        elif kind == "thumb":
            card.set_thumb(data)
        elif kind == "status":
            self.run_status.configure(text=data)
        elif kind == "run":
            card.set_state("run", "0%")
        elif kind == "prog_v":
            d, t, f = data
            frac = d / t
            self.progress[jid] = frac
            eta = fmt_time((t - d) / f) if f else ""
            card.set_progress(frac, f"{frac * 100:.0f}%  ·  {f:.1f} fps" + (f"  ·  còn {eta}" if eta else ""))
        elif kind == "prog_i":
            k, n = data
            frac = k / n if n else 0
            self.progress[jid] = frac
            card.set_progress(frac, f"{frac * 100:.0f}%")
        elif kind == "done":
            self.progress[jid] = 1.0
            card.set_state("done", f"xong trong {fmt_time(data) or '<1s'}" if data >= 1 else "xong trong <1s")
            card.set_meta("Đã lưu: " + short(os.path.basename(self.jobs[jid].out_path), 64), C["ok"])
        elif kind == "stopped":
            card.set_state("stopped")
        elif kind == "error":
            card.set_state("error")
            card.set_meta(short((data or "Lỗi").splitlines()[0], 90), C["err"])
        elif kind == "fatal":
            messagebox.showerror(APP_NAME, data)
        elif kind == "worker_done":
            self.active -= 1
            if self.active <= 0:
                self.running = False
                self.stop_btn.pack_forget()
                self.start_btn.pack(fill="x")
                ok = sum(1 for j in self.batch if self.state.get(j) == "done")
                err = sum(1 for j in self.batch if self.state.get(j) == "error")
                took = fmt_time(time.time() - self.t_start)
                self.run_status.configure(
                    text=f"Hoàn tất {ok}/{len(self.batch)}" + (f" · {err} lỗi" if err else "") +
                         (f" · {took}" if took else ""))
                backend.release()
        if self.running and self.batch:
            fr = sum(self.progress.get(j, 0) if self.state.get(j) != "done" else 1 for j in self.batch)
            self.overall.set(fr / len(self.batch))
        if kind in ("run", "done", "error", "stopped", "info_err", "worker_done"):
            self._refresh_summary()


# ------------------------------------------------------------------------------------------ app
class _ThumbPool:
    def __init__(self, n=3):
        self.q: queue.Queue = queue.Queue()
        for _ in range(n):
            threading.Thread(target=self._run, daemon=True).start()

    def submit(self, fn, *a):
        self.q.put((fn, a))

    def _run(self):
        while True:
            fn, a = self.q.get()
            try:
                fn(*a)
            except Exception:
                traceback.print_exc()


_Base = (ctk.CTk, TkinterDnD.DnDWrapper) if TkinterDnD is not None else (ctk.CTk,)


class App(*_Base):
    def __init__(self):
        super().__init__()
        if TkinterDnD is not None:
            try:
                self.TkdndVersion = TkinterDnD._require(self)
                self.drop_target_register(DND_FILES)
                self.dnd_bind("<<Drop>>", self._on_drop)
            except Exception:
                pass
        self.title(APP_NAME)
        self.geometry("1280x800")
        self.minsize(1080, 680)
        self.configure(fg_color=C["bg"])
        self._set_icon()
        cfg = self._load_cfg()
        self.device_var = ctk.StringVar(value=backend.BACKEND_LABELS.get(cfg.get("device", "auto"), "Tự động"))

        fam = "Segoe UI"
        self.f = {
            "11": ctk.CTkFont(fam, 11), "12": ctk.CTkFont(fam, 12), "13": ctk.CTkFont(fam, 13),
            "b11": ctk.CTkFont(fam, 11, "bold"), "b12": ctk.CTkFont(fam, 12, "bold"),
            "b13": ctk.CTkFont(fam, 13, "bold"),
            "b15": ctk.CTkFont(fam, 15, "bold"), "b16": ctk.CTkFont(fam, 16, "bold"),
            "b18": ctk.CTkFont(fam, 18, "bold"), "b20": ctk.CTkFont(fam, 20, "bold"),
            "b24": ctk.CTkFont(fam, 24, "bold"),
        }
        self.icons = {
            "video": draw_icon("video", C["muted"], 20), "video_on": draw_icon("video", C["accent_txt"], 20),
            "image": draw_icon("image", C["muted"], 20), "image_on": draw_icon("image", C["accent_txt"], 20),
            "folder": draw_icon("folder", C["text"], 16), "folder_m": draw_icon("folder", C["text"], 16),
            "plus": draw_icon("plus", "#ffffff", 14), "close_m": draw_icon("close", C["muted"], 12),
            "play": draw_icon("play", "#ffffff", 16), "stop": draw_icon("stop", C["err"], 14),
            "broom": draw_icon("broom", C["muted"], 16), "upload_xl": draw_icon("upload", C["accent_txt"], 38),
            "chip": draw_icon("chip", C["cyan"], 18),
        }
        mark = Image.open(os.path.join(ASSETS, "logo_mark.png"))
        self.icons["logo"] = ctk.CTkImage(mark, mark, size=(38, 38))
        self.events: queue.Queue = queue.Queue()
        self.thumb_pool = _ThumbPool()

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        body = ctk.CTkFrame(self, fg_color=C["bg"], corner_radius=0)
        body.grid(row=0, column=1, sticky="nsew")
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(0, weight=1)
        self.pages = {k: Page(body, self, k, cfg.get(k)) for k in PAGES}
        self.current = None
        self.show(cfg.get("page", "video") if cfg.get("page") in self.pages else "video")

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(120, self._poll)
        self.det = None
        self.encoder = ""
        threading.Thread(target=self._detect, daemon=True).start()

    def _set_icon(self):
        ico = os.path.join(ASSETS, "icon.ico")
        if os.path.exists(ico):
            try:
                # Windows: tách app khỏi nhóm "python" trên taskbar để hiện đúng icon
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PAMMedia.PamUpscale")
            except Exception:
                pass
            self.after(300, lambda: self.iconbitmap(ico))

    def _detect(self):
        det = backend.detect()
        try:
            enc = encoder_label(pick_encoder("h264"))
        except Exception:
            enc = "chưa có ffmpeg"
        self.after(0, lambda: self._on_detected(det, enc))

    def _on_detected(self, det, enc):
        self.det, self.encoder = det, enc
        opts = [backend.BACKEND_LABELS["auto"]] + [backend.BACKEND_LABELS[b] for b in ("cuda", "directml", "cpu")
                                                   if det.available[b]]
        self.device_menu.configure(values=opts, state="normal")
        if self.device_var.get() not in opts:
            self.device_var.set(opts[0])
        self._refresh_models()
        self._gpu_tick()

    def _refresh_models(self):
        try:
            be = backend.resolve(self.device_pref())
        except Exception:
            return
        for p in self.pages.values():
            p.refresh_models(be)

    def _on_device_change(self):
        self._refresh_models()
        self._gpu_tick(once=True)
        self.save_cfg()

    def device_pref(self) -> str:
        lbl = self.device_var.get()
        return next((k for k, v in backend.BACKEND_LABELS.items() if v == lbl), "auto")

    # -------------------------------------------------------------- sidebar
    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, fg_color=C["side"], corner_radius=0, width=232)
        sb.grid(row=0, column=0, sticky="nsw")
        sb.pack_propagate(False)

        logo = ctk.CTkFrame(sb, fg_color="transparent")
        logo.pack(fill="x", padx=18, pady=(24, 30))
        ctk.CTkLabel(logo, text="", image=self.icons["logo"]).pack(side="left")
        t = ctk.CTkFrame(logo, fg_color="transparent")
        t.pack(side="left", padx=10)
        ctk.CTkLabel(t, text=APP_NAME, font=self.f["b18"], text_color=C["text"], anchor="w").pack(fill="x")
        ctk.CTkLabel(t, text="by PAM Media", font=self.f["11"], text_color=C["accent_txt"], anchor="w").pack(fill="x")

        ctk.CTkLabel(sb, text="CÔNG CỤ", font=self.f["b11"], text_color=C["dim"], anchor="w").pack(
            fill="x", padx=24, pady=(0, 6))
        self.nav = {}
        for key, label in (("video", "Upscale Video"), ("image", "Upscale Ảnh")):
            row = ctk.CTkFrame(sb, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=2)
            btn = ctk.CTkButton(row, text="  " + label, image=self.icons[key], anchor="w", height=42,
                                corner_radius=10, font=self.f["b13"], fg_color="transparent",
                                hover_color=C["hover"], text_color=C["muted"], command=lambda k=key: self.show(k))
            btn.pack(fill="x")
            badge = ctk.CTkLabel(row, text="", font=self.f["b11"], width=22, height=20, corner_radius=10,
                                 fg_color=C["accent"], text_color="#ffffff")
            self.nav[key] = (btn, badge)

        # GPU card
        g = ctk.CTkFrame(sb, fg_color=C["card"], corner_radius=14, border_width=1, border_color=C["border"])
        g.pack(side="bottom", fill="x", padx=14, pady=16)
        top = ctk.CTkFrame(g, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(12, 0))
        ctk.CTkLabel(top, text="", image=self.icons["chip"]).pack(side="left")
        self.gpu_state = ctk.CTkLabel(top, text="", font=self.f["b11"], text_color=C["ok"])
        self.gpu_state.pack(side="right")
        ctk.CTkLabel(top, text=" THIẾT BỊ", font=self.f["b11"], text_color=C["dim"]).pack(side="left")
        self.gpu_name = ctk.CTkLabel(g, text="Đang kiểm tra phần cứng…", font=self.f["b13"], text_color=C["text"],
                                     anchor="w", wraplength=180, justify="left")
        self.gpu_name.pack(fill="x", padx=14, pady=(6, 6))
        self.vram_bar = ctk.CTkProgressBar(g, height=6, corner_radius=3, fg_color=C["card2"],
                                           progress_color=C["cyan"])
        self.vram_bar.set(0)
        self.vram_lbl = ctk.CTkLabel(g, text="", font=self.f["11"], text_color=C["muted"], anchor="w",
                                     justify="left")
        self.vram_lbl.pack(fill="x", padx=14, pady=(0, 6))
        self.device_menu = ctk.CTkOptionMenu(
            g, variable=self.device_var, values=[self.device_var.get()], height=30, corner_radius=8,
            font=self.f["12"], dropdown_font=self.f["12"], fg_color=C["card2"], button_color=C["card2"],
            button_hover_color=C["hover"], dropdown_fg_color=C["card2"], dropdown_hover_color=C["hover"],
            dynamic_resizing=False, state="disabled", command=lambda _v: self._on_device_change())
        self.device_menu.pack(fill="x", padx=14, pady=(0, 12))

    def update_nav_badge(self, key, n):
        _btn, badge = self.nav[key]
        if n:
            badge.configure(text=str(n))
            badge.place(relx=1.0, rely=0.5, x=-14, anchor="e")
        else:
            badge.place_forget()

    def show(self, key):
        if self.current:
            self.pages[self.current].grid_forget()
        self.pages[key].grid(row=0, column=0, sticky="nsew")
        self.current = key
        for k, (btn, _b) in self.nav.items():
            on = k == key
            btn.configure(fg_color=C["accent_soft"] if on else "transparent",
                          text_color=C["accent_txt"] if on else C["muted"],
                          image=self.icons[k + "_on"] if on else self.icons[k],
                          hover_color=C["accent_soft"] if on else C["hover"])

    def _gpu_tick(self, once=False):
        try:
            be = backend.resolve(self.device_pref())
        except Exception as e:
            self.gpu_name.configure(text=str(e))
            self.gpu_state.configure(text="● Lỗi", text_color=C["err"])
            return
        self.gpu_name.configure(text=backend.device_name(be))
        self.gpu_state.configure(text={"cuda": "● CUDA", "directml": "● DirectML", "cpu": "● CPU"}[be],
                                 text_color={"cuda": C["ok"], "directml": C["ok"], "cpu": C["warn"]}[be])
        usage = backend.vram_usage() if be == "cuda" else None
        if usage:
            used, total = usage
            if not self.vram_bar.winfo_ismapped():
                self.vram_bar.pack(fill="x", padx=14, pady=(0, 4), before=self.vram_lbl)
            self.vram_bar.set(used / total)
            self.vram_lbl.configure(text=f"VRAM {used / 2**30:.1f}/{total / 2**30:.0f} GB  ·  {self.encoder}")
        else:
            self.vram_bar.pack_forget()
            note = "Không có GPU – chậm, nên dùng cho ảnh" if be == "cpu" else "Chạy qua DirectX 12"
            self.vram_lbl.configure(text=f"{note}\nEncode: {self.encoder}")
        if not once:
            self.after(1500, self._gpu_tick)

    # -------------------------------------------------------------- events
    def post(self, page, kind, jid, data):
        self.events.put((page, kind, jid, data))

    def _poll(self):
        try:
            for _ in range(500):
                page, kind, jid, data = self.events.get_nowait()
                page.handle(kind, jid, data)
        except queue.Empty:
            pass
        self.after(120, self._poll)

    def _on_drop(self, event):
        paths = []
        for p in self.tk.splitlist(event.data):
            if os.path.isdir(p):
                for dp, _dn, fn in os.walk(p):
                    paths += [os.path.join(dp, f) for f in sorted(fn)]
            else:
                paths.append(p)
        got = {k: pg.add_paths([p for p in paths if pg.accepts(p)]) for k, pg in self.pages.items()}
        if not got.get(self.current) and any(got.values()):
            self.show(next(k for k, v in got.items() if v))

    # -------------------------------------------------------------- config
    def _load_cfg(self):
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) and "video" in d else {}
        except Exception:
            return {}

    def save_cfg(self):
        d = {k: p.export_cfg() for k, p in self.pages.items()}
        d["page"] = self.current
        d["device"] = self.device_pref()
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def on_close(self):
        if any(p.running for p in self.pages.values()):
            if not messagebox.askyesno("Thoát", "Đang upscale. Dừng và thoát?"):
                return
            for p in self.pages.values():
                p.stop()
        self.save_cfg()
        self.destroy()


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
