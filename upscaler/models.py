"""Kiến trúc Real-ESRGAN bằng PyTorch (RRDBNet + SRVGGNetCompact) và xuất ONNX.

Chỉ dùng khi máy có PyTorch (máy NVIDIA). Máy khác dùng file .onnx qua ONNX Runtime.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F

from .catalog import MODEL_CATALOG, ensure_weights, onnx_path


class SRVGGNetCompact(nn.Module):
    def __init__(self, num_feat=64, num_conv=16, upscale=4):
        super().__init__()
        self.upscale = upscale
        body = [nn.Conv2d(3, num_feat, 3, 1, 1), nn.PReLU(num_parameters=num_feat)]
        for _ in range(num_conv):
            body += [nn.Conv2d(num_feat, num_feat, 3, 1, 1), nn.PReLU(num_parameters=num_feat)]
        body.append(nn.Conv2d(num_feat, 3 * upscale * upscale, 3, 1, 1))
        self.body = nn.ModuleList(body)
        self.upsampler = nn.PixelShuffle(upscale)

    def forward(self, x):
        out = x
        for layer in self.body:
            out = layer(out)
        out = self.upsampler(out)
        return out + F.interpolate(x, scale_factor=self.upscale, mode="nearest")


class ResidualDenseBlock(nn.Module):
    def __init__(self, nf=64, gc=32):
        super().__init__()
        self.conv1 = nn.Conv2d(nf, gc, 3, 1, 1)
        self.conv2 = nn.Conv2d(nf + gc, gc, 3, 1, 1)
        self.conv3 = nn.Conv2d(nf + 2 * gc, gc, 3, 1, 1)
        self.conv4 = nn.Conv2d(nf + 3 * gc, gc, 3, 1, 1)
        self.conv5 = nn.Conv2d(nf + 4 * gc, nf, 3, 1, 1)
        self.lrelu = nn.LeakyReLU(0.2, inplace=True)

    def forward(self, x):
        x1 = self.lrelu(self.conv1(x))
        x2 = self.lrelu(self.conv2(torch.cat((x, x1), 1)))
        x3 = self.lrelu(self.conv3(torch.cat((x, x1, x2), 1)))
        x4 = self.lrelu(self.conv4(torch.cat((x, x1, x2, x3), 1)))
        x5 = self.conv5(torch.cat((x, x1, x2, x3, x4), 1))
        return x5 * 0.2 + x


class RRDB(nn.Module):
    def __init__(self, nf, gc=32):
        super().__init__()
        self.rdb1 = ResidualDenseBlock(nf, gc)
        self.rdb2 = ResidualDenseBlock(nf, gc)
        self.rdb3 = ResidualDenseBlock(nf, gc)

    def forward(self, x):
        return self.rdb3(self.rdb2(self.rdb1(x))) * 0.2 + x


class RRDBNet(nn.Module):
    def __init__(self, scale=4, num_feat=64, num_block=23, num_grow_ch=32):
        super().__init__()
        self.scale = scale
        in_ch = 3 * (16 if scale == 1 else 4 if scale == 2 else 1)
        self.conv_first = nn.Conv2d(in_ch, num_feat, 3, 1, 1)
        self.body = nn.Sequential(*[RRDB(num_feat, num_grow_ch) for _ in range(num_block)])
        self.conv_body = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.conv_up1 = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.conv_up2 = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.conv_hr = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.conv_last = nn.Conv2d(num_feat, 3, 3, 1, 1)
        self.lrelu = nn.LeakyReLU(0.2, inplace=True)

    def forward(self, x):
        if self.scale in (1, 2):
            feat = F.pixel_unshuffle(x, 4 if self.scale == 1 else 2)
        else:
            feat = x
        feat = self.conv_first(feat)
        feat = feat + self.conv_body(self.body(feat))
        feat = self.lrelu(self.conv_up1(F.interpolate(feat, scale_factor=2, mode="nearest")))
        feat = self.lrelu(self.conv_up2(F.interpolate(feat, scale_factor=2, mode="nearest")))
        return self.conv_last(self.lrelu(self.conv_hr(feat)))


def _build_from_state(sd: dict) -> nn.Module:
    if "conv_first.weight" in sd:
        num_block = 1 + max(int(m.group(1)) for k in sd if (m := re.match(r"body\.(\d+)\.", k)))
        in_ch = sd["conv_first.weight"].shape[1]
        return RRDBNet(scale={3: 4, 12: 2, 48: 1}[in_ch], num_feat=sd["conv_first.weight"].shape[0],
                       num_block=num_block)
    idx = sorted({int(m.group(1)) for k in sd if (m := re.match(r"body\.(\d+)\.", k))})
    last = idx[-1]
    out_ch = sd[f"body.{last}.weight"].shape[0]
    return SRVGGNetCompact(num_feat=sd["body.0.weight"].shape[0], num_conv=(last - 2) // 2,
                           upscale=int(round((out_ch / 3) ** 0.5)))


@dataclass
class TorchModel:
    net: nn.Module
    supports_half: bool = True
    multiple_of: int = 1   # kích thước đầu vào phải chia hết cho số này
    minimum: int = 0       # kích thước đầu vào tối thiểu


def load_torch(key: str, status_cb=None) -> TorchModel:
    """Nạp model PyTorch (fp32, CPU, eval) – Real-ESRGAN bằng code riêng, các kiến trúc khác qua spandrel."""
    spec = MODEL_CATALOG[key]
    if spec.kind != "spandrel":
        return TorchModel(build_net(key, status_cb))
    import spandrel

    path = ensure_weights(key, status_cb)
    d = spandrel.ModelLoader().load_from_file(path)
    net = d.model.eval()
    for p in net.parameters():
        p.requires_grad_(False)
    req = d.size_requirements
    return TorchModel(net, bool(d.supports_half), max(1, req.multiple_of or 1), req.minimum or 0)


def build_net(key: str, status_cb=None) -> nn.Module:
    """Nạp model Real-ESRGAN (fp32, CPU, eval)."""
    path = ensure_weights(key, status_cb)
    sd = torch.load(path, map_location="cpu", weights_only=True)
    for k in ("params_ema", "params"):
        if isinstance(sd, dict) and k in sd:
            sd = sd[k]
            break
    net = _build_from_state(sd)
    net.load_state_dict(sd, strict=True)
    net.eval()
    for p in net.parameters():
        p.requires_grad_(False)
    return net


def export_onnx(key: str, status_cb=None) -> str:
    """Xuất model sang ONNX (kích thước ảnh động) để chạy trên AMD/Intel/CPU."""
    out = onnx_path(key)
    inner = load_torch(key, status_cb).net.float().cpu()

    class _OnlyImage(nn.Module):  # bỏ các tham số phụ (vd. alpha của Real-CUGAN) khỏi đồ thị ONNX
        def __init__(self, m):
            super().__init__()
            self.m = m

        def forward(self, x):
            return self.m(x)

    net = _OnlyImage(inner).eval()
    if status_cb:
        status_cb("Đang chuyển model sang ONNX…")
    import os
    tmp = out + ".part.onnx"
    T = MODEL_CATALOG[key].onnx_tile
    if T:
        # Kích thước cố định T×T + đổi pad âm thành cắt mảng: tránh lỗi của DirectML với kích thước động
        # và phép Pad âm (Real-CUGAN dùng F.pad âm để cắt viền).
        orig_pad = F.pad

        def safe_pad(x, pad, mode="constant", value=None):
            if mode == "constant" and all(p <= 0 for p in pad):
                left, right, top, bottom = (list(pad) + [0, 0, 0, 0])[:4]
                H, W = x.shape[-2], x.shape[-1]
                return x[..., -top:H + bottom if bottom else H, -left:W + right if right else W]
            return orig_pad(x, pad, mode=mode) if value is None else orig_pad(x, pad, mode=mode, value=value)

        F.pad = safe_pad
        try:
            torch.onnx.export(net, (torch.rand(1, 3, T, T),), tmp, input_names=["input"], output_names=["output"],
                              opset_version=17, dynamo=False)
        finally:
            F.pad = orig_pad
    elif MODEL_CATALOG[key].kind == "spandrel":
        # các kiến trúc mới có code phụ thuộc kích thước ảnh → cần bộ xuất dynamo (giữ kích thước động thật)
        h = torch.export.Dim("h", min=32, max=4096)
        w = torch.export.Dim("w", min=32, max=4096)
        torch.onnx.export(net, (torch.rand(1, 3, 96, 128),), tmp, input_names=["input"], output_names=["output"],
                          dynamo=True, dynamic_shapes=({2: h, 3: w},), opset_version=18, external_data=False)
    else:
        torch.onnx.export(
            net, (torch.rand(1, 3, 64, 64),), tmp, input_names=["input"], output_names=["output"], opset_version=17,
            dynamo=False, dynamic_axes={"input": {0: "n", 2: "h", 3: "w"}, "output": {0: "n", 2: "h4", 3: "w4"}},
        )
    os.replace(tmp, out)
    return out
