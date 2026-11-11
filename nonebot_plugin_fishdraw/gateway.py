"""ComfyUI 网关客户端（无限画布那套 `/v1/images/*` HTTP 接口）。

网关契约（自建 `ComfyUI-Local-Infinite-Canvas`）：

| 场景 | 接口 | mode | 字段 |
|------|------|------|------|
| 文生图 | `POST /v1/images/generations` (JSON) | `t2i` | prompt / size / steps |
| 以图生图 / 多图编辑 | `POST /v1/images/edits` (multipart) | `edit` | prompt / image×N / size |
| **局部重绘**（换装） | `POST /v1/images/edits` (multipart) | `inpaint` | prompt / **image×2（原图 + 蒙版，白=重绘区）** |
| 去物体 | 同上 | `remove` | prompt / image / mask |
| 扩图 | 同上 | `outpaint` | prompt / image / size |

⚠️ 两个必须记住的点：

1. `mode=inpaint` 要 **两张图**：`[("image", src), ("image", mask)]`，**蒙版白色 = 要重画的地方**。
   只传一张时网关会把它当 edit，等于整图重画（换装会把人脸也换掉）。
2. 多图时提示词里用「图1 / 图2」指代，网关按上传顺序编号，**不会**改写你的编号。
"""

from __future__ import annotations

import time
from typing import List, Optional, Sequence, Tuple

import httpx

DEFAULT_TIMEOUT = 600.0
MIN_TIMEOUT_INPAINT = 360.0


class GatewayError(RuntimeError):
    """网关返回了错误 / 超时 / 空图。"""


def _base(url: str) -> str:
    return (url or "").rstrip("/")


def _headers(token: str = "") -> dict:
    h = {"Accept": "image/png"}
    if token:
        h["Authorization"] = "Bearer " + token
    return h


def _clean_refs(refs) -> List[Tuple[bytes, str]]:
    """把各种传参形状统一成 `[(bytes, mime), …]`。

    踩过的坑：有人传 `(png, "image/png")`（元组），被当成"两张图"去解包 →
    `too many values to unpack`，而报错完全看不出是传参问题。这里自己兜住。
    """
    if not refs:
        return []
    if isinstance(refs, tuple) and len(refs) == 2 and isinstance(refs[0], (bytes, bytearray)):
        refs = [refs]
    out = []
    for r in refs:
        if isinstance(r, (tuple, list)) and len(r) >= 2 and r[0]:
            out.append((bytes(r[0]), str(r[1] or "image/png")))
    return out


async def generate(*,
                   gateway: str,
                   token: str = "",
                   prompt: str,
                   negative: str = "",
                   size: str = "1024x1024",
                   steps: int = 8,
                   seed: int = -1,
                   timeout: float = DEFAULT_TIMEOUT) -> Tuple[bytes, float]:
    """文生图。返回 `(图片字节, 耗时秒)`。"""
    url = _base(gateway) + "/v1/images/generations"
    body = {"prompt": prompt, "negative_prompt": negative, "size": size,
            "steps": int(steps), "seed": int(seed)}
    t0 = time.time()
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.post(url, json=body, headers=_headers(token))
    except httpx.HTTPError as e:
        raise GatewayError("网关连不上：%s" % e) from e
    if r.status_code >= 400:
        raise GatewayError("网关返回 HTTP %d：%s" % (r.status_code, r.text[:200]))
    if not r.content:
        raise GatewayError("网关返回空图")
    return r.content, time.time() - t0


async def edit(*,
               gateway: str,
               token: str = "",
               prompt: str,
               negative: str = "",
               refs: Sequence | None = None,
               size: str = "",
               steps: int = 8,
               seed: int = -1,
               mode: str = "edit",
               mask: Optional[bytes] = None,
               timeout: float = DEFAULT_TIMEOUT) -> Tuple[bytes, float]:
    """以图生图 / 局部重绘。`mask` 非空时自动走 `inpaint`。"""
    refs_l = _clean_refs(refs)
    if not refs_l:
        raise GatewayError("没有参考图：文生图请用 generate()")
    if mode == "inpaint":
        if not mask:
            raise GatewayError("mode=inpaint 需要蒙版（白色 = 重绘区）")
        refs_l = [refs_l[0], (bytes(mask), "image/png")]
        timeout = max(float(timeout), MIN_TIMEOUT_INPAINT)   # 重绘要走蒙版裁剪+回贴，慢
    url = _base(gateway) + "/v1/images/edits"
    data = {"mode": mode, "prompt": prompt, "negative_prompt": negative,
            "steps": str(int(steps)), "seed": str(int(seed))}
    if size:
        data["size"] = size
    files = [("image", ("ref%d.png" % i, blob, mime))
             for i, (blob, mime) in enumerate(refs_l)]
    t0 = time.time()
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.post(url, data=data, files=files, headers=_headers(token))
    except httpx.HTTPError as e:
        raise GatewayError("网关连不上：%s" % e) from e
    if r.status_code >= 400:
        raise GatewayError("网关返回 HTTP %d：%s" % (r.status_code, r.text[:200]))
    if not r.content:
        raise GatewayError("网关返回空图")
    return r.content, time.time() - t0


async def inpaint(*, gateway: str, src: bytes, mask: bytes, prompt: str,
                  token: str = "", negative: str = "", steps: int = 8,
                  seed: int = -1, timeout: float = DEFAULT_TIMEOUT) -> Tuple[bytes, float]:
    """局部重绘的便捷入口（换装走这个）。"""
    return await edit(gateway=gateway, token=token, prompt=prompt, negative=negative,
                      refs=[(src, "image/png")], mode="inpaint", mask=mask,
                      steps=steps, seed=seed, timeout=timeout)


async def health(gateway: str, token: str = "", timeout: float = 10.0) -> bool:
    """网关探活（`/health`）。出图前想知道"隧道通不通"就用它。"""
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.get(_base(gateway) + "/health", headers=_headers(token))
            return r.status_code < 400
    except Exception:
        return False
