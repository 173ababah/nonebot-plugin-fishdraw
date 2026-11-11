"""提示词拼装 + 长度闸（纯函数，方便单测）。

设计要点（都是踩坑踩出来的，别随手改）：

1. **turbo 模型 CFG=1，负向提示词几乎无效** —— 想要的效果必须写成**正向**。
   所以「别脱」要顶「穿着完整」，「保持原图画风」要顶守护词，而不是往 negative 里塞。
2. **长度闸**：网关对超长提示词的处理不可预期（有时静默截断、有时直接退化），
   所以先在本地按「底稿 + 允许追加」算额度，超了就截用户那段，并明确告诉用户。
3. **配色锁前置**：锁必须放在最前面，否则会被后面的风格词稀释。
4. **不要写不可能的值**：`#FFFFFF`、`明度 255` 这种模型做不到，反而会把整段锁丢掉。
"""

from __future__ import annotations

from typing import Iterable

# ---- 画风/画质词表（按需扩，id 就是模板 id）----
STYLE_WORDS = {
    "二次元": "anime style, cel shading, clean lineart",
    "q版": "chibi style, super deformed, big head, simple background",
    "电影": "cinematic still, film grain, dramatic lighting, shallow depth of field",
    "水墨": "chinese ink painting style, rice paper texture, minimal color",
    "水彩": "watercolor painting, soft edges, paper texture",
    "厚涂": "painterly, thick brush strokes, detailed rendering",
    "像素": "pixel art, 16-bit, crisp pixels",
    "素描": "pencil sketch, graphite, cross hatching, monochrome",
    "黏土3D": "3d clay render, soft clay material, studio light",
}

QUALITY_POSITIVE = "masterpiece, best quality, highly detailed, cinematic lighting"
CLOTHED_LOCK = "fully clothed, wearing complete outfit"
KEEP_STYLE_GUARD = "keep the original art style, keep the original lineart, same rendering"

NEGATIVE_BASE = (
    "lowres, blurry, jpeg artifacts, watermark, text, signature, "
    "bad anatomy, extra fingers, missing fingers, fused fingers, "
    "extra limbs, deformed, worst quality"
)


def plim(base: str, extra: str = "", kind: str = "normal") -> str:
    """长度闸：把 ``extra`` 接在 ``base`` 后面，但不让总长超过该 kind 的额度。

    · ``normal``：总长 ≤ 300
    · ``long``  ：总长 ≤ min(4200, len(base) + 300)
    · ``act``   ：总长 ≤ min(2600, len(base) + 400)

    ``kind`` 用 `act`（动作模板整段替换提示词，本身就很长）和 `long`（用户自己写了长描述）。
    返回拼接后的字符串；被截断时以 `…` 结尾并保留 base 全文。
    """
    base = (base or "").strip()
    extra = (extra or "").strip()
    if not extra:
        return base
    if not base:
        return extra
    k = (kind or "normal").lower()
    if k == "long":
        cap = min(4200, len(base) + 300)
    elif k == "act":
        cap = min(2600, len(base) + 400)
    else:
        cap = 300
    room = max(0, cap - len(base) - 3)          # 2 = ", "，1 = 结尾的 "…"
    if len(extra) <= room:
        return base + ", " + extra
    if room <= 0:
        return base
    cut = extra[:room].rstrip(" ,，")
    return base + ", " + cut + "…"


def style_words(styles: Iterable[str] | None, has_ref: bool) -> str:
    """把选中的画风模板换成词。

    · 有参考图且**没选任何角色风** → 返回空（保留原图画风）
    · 文生图且没选 → 默认二次元
    """
    picked = [s for s in (styles or []) if s]
    words = [STYLE_WORDS[s] for s in picked if s in STYLE_WORDS]
    if words:
        return ", ".join(words)
    return "" if has_ref else STYLE_WORDS["二次元"]


def compose(prompt: str,
            *,
            style: str = "",
            lock: str = "",
            keep_style: bool = False,
            clothed: bool = True,
            kind: str = "normal") -> str:
    """拼最终正向提示词。

    顺序：配色锁 → 画风词 → （画质词 | 守护词）→ 「穿着完整」→ 用户提示词
    """
    head: list[str] = []
    if lock:
        head.append(lock.strip())
    if style:
        head.append(style.strip())
    if keep_style:
        head.append(KEEP_STYLE_GUARD)
    else:
        head.append(QUALITY_POSITIVE)
    if clothed:
        head.append(CLOTHED_LOCK)
    base = ", ".join(x for x in head if x)
    return plim(base, prompt, kind=kind)


def negative(tags: Iterable[str] | None = None, *, nsfw: bool = False) -> str:
    """负向词：画质底线 + 调用方追加；`nsfw=False` 时再补一串裸体词（聊胜于无）。"""
    out = [NEGATIVE_BASE]
    if not nsfw:
        out.append("nude, naked, nipples, topless, bottomless, nsfw")
    for t in (tags or []):
        t = (t or "").strip()
        if t:
            out.append(t)
    return ", ".join(out)


def truncate_note(original: str, final: str) -> str:
    """提示词被截断时给用户的一句说明（没截断返回空串）。"""
    if len(final) >= len(original):
        return ""
    return "提示词太长（%d 字），已按额度截到 %d 字。" % (len(original), len(final))
