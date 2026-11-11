"""Deterministic image checks: palette, contrast, logo fidelity."""
from pathlib import Path

import numpy as np
from PIL import Image


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_hex(rgb) -> str:
    return "#%02X%02X%02X" % tuple(int(x) for x in rgb)


def _srgb_to_lin(c):
    c = np.asarray(c, dtype=float) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def rgb_to_lab(rgb) -> np.ndarray:
    lin = _srgb_to_lin(rgb)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = lin @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    L = 116 * f[..., 1] - 16
    a = 500 * (f[..., 0] - f[..., 1])
    b = 200 * (f[..., 1] - f[..., 2])
    return np.stack([L, a, b], axis=-1)


def delta_e(rgb1, rgb2) -> float:
    return float(np.linalg.norm(rgb_to_lab(rgb1) - rgb_to_lab(rgb2)))


def luminance(rgb) -> float:
    r, g, b = _srgb_to_lin(rgb)
    return float(0.2126 * r + 0.7152 * g + 0.0722 * b)


def contrast_ratio(a, b) -> float:
    la, lb = sorted([luminance(a), luminance(b)], reverse=True)
    return round((la + 0.05) / (lb + 0.05), 2)


def palette(path: str | Path, n: int = 6) -> list[dict]:
    """Dominant colours with coverage share (median-cut quantisation)."""
    img = Image.open(path).convert("RGB")
    img.thumbnail((240, 240))
    q = img.quantize(colors=n, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()[: n * 3]
    counts = sorted(q.getcolors(), reverse=True)
    total = sum(c for c, _ in counts)
    out = []
    for count, idx in counts:
        rgb = tuple(pal[idx * 3: idx * 3 + 3])
        out.append({"hex": rgb_to_hex(rgb), "share": round(count / total, 3)})
    return out


def check_palette(colors: list[dict], brand: list[dict], min_share: float = 0.04, max_de: float = 18.0) -> list[dict]:
    """Return colours that take meaningful space but are far from every approved colour."""
    issues = []
    if not brand:
        return issues
    for c in colors:
        if c["share"] < min_share:
            continue
        rgb = hex_to_rgb(c["hex"])
        best = min(brand, key=lambda b: delta_e(rgb, hex_to_rgb(b["hex"])))
        de = delta_e(rgb, hex_to_rgb(best["hex"]))
        if de > max_de:
            issues.append({**c, "nearest": best["name"], "nearest_hex": best["hex"], "delta_e": round(de, 1)})
    return issues


def _dhash(img: Image.Image, size: int = 16) -> np.ndarray:
    g = img.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    a = np.asarray(g, dtype=float)
    return (a[:, 1:] > a[:, :-1]).flatten()


def _trim(img: Image.Image) -> Image.Image:
    """Crop away near-uniform border so aspect ratio reflects the mark itself."""
    rgb = np.asarray(img.convert("RGB"), dtype=int)
    bg = rgb[0, 0]
    mask = np.abs(rgb - bg).sum(axis=2) > 30
    if not mask.any():
        return img
    ys, xs = np.where(mask)
    return img.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))


def compare_logo(candidate: str | Path, official: str | Path) -> dict:
    """Compare a logo file used in content with the official mark."""
    a = _trim(Image.open(candidate).convert("RGB"))
    b = _trim(Image.open(official).convert("RGB"))
    ar_a, ar_b = a.width / a.height, b.width / b.height
    aspect_diff = abs(ar_a - ar_b) / ar_b
    # Compare shape after normalising size (so distortion shows up via aspect, shape via hash)
    ha, hb = _dhash(a), _dhash(b)
    shape_sim = float((ha == hb).mean())
    pa = palette(candidate, 3)
    pb = palette(official, 3)
    main_a = next((p for p in pa if luminance(hex_to_rgb(p["hex"])) < 0.85), pa[0])
    main_b = next((p for p in pb if luminance(hex_to_rgb(p["hex"])) < 0.85), pb[0])
    color_de = delta_e(hex_to_rgb(main_a["hex"]), hex_to_rgb(main_b["hex"]))
    return {
        "aspect_candidate": round(ar_a, 3), "aspect_official": round(ar_b, 3),
        "aspect_diff_pct": round(aspect_diff * 100, 1),
        "shape_similarity": round(shape_sim, 3),
        "main_color_candidate": main_a["hex"], "main_color_official": main_b["hex"],
        "color_delta_e": round(color_de, 1),
    }
