"""配色锁：从参考图里取肤色，写成一段"锁"，前置到提示词最前面。

为什么需要它：以图生图时模型会**逐步把肤色画深**（每轮在上一轮结果上再猜一遍），
链式几轮下来皮肤就变成棕色。把肤色写成明确的值锁死，能显著缓解。

做法（都是实测的取舍）：

1. **取 4 档亮度**（1 维 k-means，k=4）：暗部 / 中间调 / 亮部 / 高光，分别给值。
   —— 只取一个"均值"时模型会用中间调铺满整张脸，出来脏。
2. **排除被截白的像素**（lum > 250）：白围裙/白布在 QQ 压缩后会变成纯白，
   如果它进了统计，锁里就会出现 `#FFFFFF 明度 255` —— 模型做不到这个值，反而把整段锁丢掉。
3. **只要暖色像素**（Cr-Cb ≥ 20 且 R-B ≥ 10）：头发、灰衣服、白蕾丝的色度坐标离肤色很近，
   放宽就取错（线上真实踩过：银发取成 `#D8BCC3`，出图灰紫）。
4. **锁里只写"能力范围内"的话**，而且给出面积占比，让模型知道哪档是主色。

依赖 numpy + pillow（可选依赖 `pip install nonebot-plugin-fishdraw[skin]`）；
没装就退化成"不锁"，绝不让出图挂掉。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

MAX_LOCK_CHARS = 560


def _have_deps() -> bool:
    try:
        import numpy  # noqa: F401
        import PIL  # noqa: F401
        return True
    except Exception:
        return False


def _hex(rgb) -> str:
    return "#%02X%02X%02X" % (int(rgb[0]), int(rgb[1]), int(rgb[2]))


def _lum(rgb) -> int:
    r, g, b = float(rgb[0]), float(rgb[1]), float(rgb[2])
    return int(round(0.299 * r + 0.587 * g + 0.114 * b))


def _bands(lum_sorted: List[int], k: int = 4) -> List[int]:
    """1 维 k-means（初始化等距分位），返回 k 个中心，升序。"""
    lum_sorted = list(lum_sorted)      # 允许传 ndarray
    if not lum_sorted:
        return []
    k = max(1, min(k, len(lum_sorted)))
    step = max(1, len(lum_sorted) // k)
    centers = [float(lum_sorted[min(len(lum_sorted) - 1, i * step + step // 2)])
               for i in range(k)]
    for _ in range(12):
        sums = [0.0] * k
        cnts = [0] * k
        for v in lum_sorted:
            best, bd = 0, 1e9
            for idx, c in enumerate(centers):
                d = abs(v - c)
                if d < bd:
                    best, bd = idx, d
            sums[best] += v
            cnts[best] += 1
        new = [sums[i] / cnts[i] if cnts[i] else centers[i] for i in range(k)]
        if all(abs(new[i] - centers[i]) < 0.5 for i in range(k)):
            centers = new
            break
        centers = new
    return sorted(int(round(c)) for c in centers)


def probe(img_bytes: bytes, edge: int = 0) -> Optional[Dict[str, Any]]:
    """从图片字节里取肤色。取不到返回 None（= 不锁）。

    返回：`{base, base_share, bands:[{rgb,lum,share}...], tone, blush}`。
    """
    if not img_bytes or not _have_deps():
        return None
    try:
        import io

        import numpy as np
        from PIL import Image

        im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        if edge > 0:
            w, h = im.size
            im = im.crop((edge, edge, max(edge + 1, w - edge), max(edge + 1, h - edge)))
        # 太大就缩一下，采样足够且快
        im.thumbnail((320, 320))
        arr = np.asarray(im).astype(np.int16)
        r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
        cr = (r - g) * 0.5 + 128          # 近似 YCbCr 的 Cr/Cb，够区分肤色
        cb = (b - g) * 0.5 + 128
        lum = (0.299 * r + 0.587 * g + 0.114 * b)
        skin = (r > 60) & (r > g) & (g > b * 0.7) & (abs(cr - cb) >= 6)
        warm = ((cr - cb) >= 20) & ((r - b) >= 10)
        strict = skin & warm
        if int(strict.sum()) >= 400:
            skin = strict
        if int(skin.sum()) < 300:
            return None
        ys, xs = np.nonzero(skin)
        px = arr[ys, xs]
        lums = sorted(int(v) for v in lum[ys, xs])   # 注意别用 np.sort：它返回 ndarray，`if not list` 会抛
        centers = _bands(lums, 4)
        if not centers:
            return None
        total = len(lums)
        bands = []
        for c in centers:
            sel = [abs(v - c) <= 6 for v in lums]
            n = sum(1 for x in sel if x)
            if not n:
                continue
            rr = [int(px[i][0]) for i, ok in enumerate(sel) if ok]
            gg = [int(px[i][1]) for i, ok in enumerate(sel) if ok]
            bb = [int(px[i][2]) for i, ok in enumerate(sel) if ok]
            rgb = (sum(rr) // len(rr), sum(gg) // len(gg), sum(bb) // len(bb))
            bands.append({"rgb": rgb, "lum": _lum(rgb), "share": round(n / total, 3)})
        if not bands:
            return None
        # 主色：面积最大、且没被截白（lum ≤ 250）
        usable = [b for b in bands if b["lum"] <= 250] or bands
        base = max(usable, key=lambda x: x["share"])
        # 腮红：暖色那批像素的平均色（注意索引要在已筛出的 px 上做，
        # 直接 arr[mask(ys,xs)] 会维度错 → 整个 probe 被 except 吞掉返回 None，线上踩过）
        blush = None
        try:
            wsel = warm[ys, xs]
            if int(wsel.sum()) > 50:
                blush = _hex(px[wsel].mean(axis=0))
        except Exception:
            blush = None
        return {
            "base": _hex(base["rgb"]),
            "base_share": base["share"],
            "bands": bands,
            "blush": blush,
            "tone": tone_word(base["rgb"]),
        }
    except Exception:
        return None


def tone_word(rgb) -> str:
    """把 RGB 说成一个中文词（写进提示词，比只给十六进制更容易被模型理解）。"""
    r, g, b = [float(x) for x in rgb]
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    warm = (r - b) >= 18
    if lum >= 235:
        return "极浅冷白"
    if lum >= 215:
        return "浅白"
    if lum >= 195:
        return "偏白" if not warm else "暖白"
    if lum >= 170:
        return "自然" if not warm else "蜜色"
    return "偏深"


def color_lock_text(p: Optional[Dict[str, Any]], *, limit: int = MAX_LOCK_CHARS) -> str:
    """把 probe 结果写成一段锁。取不到就返回空串（= 不锁）。"""
    if not p or not p.get("bands"):
        return ""
    parts = []
    base = p.get("base")
    share = p.get("base_share") or 0
    if base:
        parts.append("肤色以 %s（%s）为主，约占皮肤面积 %d%%" %
                     (base, p.get("tone") or "", int(round(share * 100))))
    for b in p["bands"]:
        if b["lum"] > 250:            # 截白档不写（模型做不到）
            continue
        if _hex(b["rgb"]) == base:
            continue
        parts.append("%s 约 %d%%" % (_hex(b["rgb"]), int(round(b["share"] * 100))))
    if p.get("blush"):
        parts.append("腮红用 %s" % p["blush"])
    parts.append("全图肤色保持统一，不要加深，不要偏黄偏灰")
    text = "；".join(parts) + "。"
    if len(text) > limit:
        text = text[:limit].rstrip("；，") + "。"
    return text


def skin_tail_text(p: Optional[Dict[str, Any]]) -> str:
    """尾巴（放提示词最后）：再强调一次别加深，模型对末尾更敏感。"""
    if not p or not p.get("base"):
        return ""
    return "（肤色锁定 %s，全程不要变深）" % p["base"]

