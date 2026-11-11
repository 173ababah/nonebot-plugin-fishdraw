"""画图图库：把每次出图的原图 + 元信息存下来，供 /图库 翻。

目录结构：

```
data/fishdraw/
  index.json          # [{id, file, at, prompt, uid, chat, style, size, model, fav, ...}]
  20261111-153012-10001.png
  thumb/20261111-153012-10001.jpg
```

id 的规则：`YYYYMMDD-HHMMSS-<uid>`，天然按时间排序。

为什么单独记索引而不是扫目录：**出图参数（提示词/画风/尺寸/耗时）比图本身更值钱**，
扫目录拿不到这些；而且 QQ 发出去的是处理过的图，原图只在本地这一份。
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

_lock = threading.Lock()


def new_id(uid: str = "0") -> str:
    return time.strftime("%Y%m%d-%H%M%S") + "-" + str(uid or "0")


def _index_path(root: str) -> str:
    return os.path.join(root, "index.json")


def load_index(root: str) -> List[Dict[str, Any]]:
    try:
        with open(_index_path(root), "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def save_index(root: str, items: List[Dict[str, Any]]) -> bool:
    try:
        os.makedirs(root, exist_ok=True)
        tmp = _index_path(root) + ".tmp"
        with _lock:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(items, f, ensure_ascii=False)
            os.replace(tmp, _index_path(root))
        return True
    except OSError:
        return False


def add(root: str, image: bytes, **meta) -> Optional[Dict[str, Any]]:
    """存一张图 + 索引记录。返回记录（失败返回 None）。"""
    if not image:
        return None
    rid = str(meta.get("id") or new_id(meta.get("uid") or "0"))
    ext = ".png" if image[:8].startswith(b"\x89PNG") else ".jpg"
    name = rid + ext
    try:
        os.makedirs(root, exist_ok=True)
        with _lock:
            with open(os.path.join(root, name), "wb") as f:
                f.write(image)
    except OSError:
        return None
    rec = {"id": rid, "file": name, "at": time.strftime("%Y-%m-%d %H:%M:%S"),
           "bytes": len(image), "fav": False}
    rec.update({k: v for k, v in meta.items() if k != "id"})
    items = load_index(root)
    items.append(rec)
    save_index(root, items)
    return rec


def find(root: str, rid: str) -> Optional[Dict[str, Any]]:
    for it in load_index(root):
        if it.get("id") == rid:
            return it
    return None


def path_of(root: str, rec: Dict[str, Any]) -> str:
    return os.path.join(root, str(rec.get("file") or ""))


def thumb_path(root: str, rec: Dict[str, Any]) -> str:
    return os.path.join(root, "thumb", str(rec.get("id") or "") + ".jpg")


def ensure_thumb(root: str, rec: Dict[str, Any], max_side: int = 320) -> Optional[str]:
    """生成缩略图（列表用）；没有 pillow 就返回原图路径。"""
    tp = thumb_path(root, rec)
    if os.path.isfile(tp):
        return tp
    src = path_of(root, rec)
    if not os.path.isfile(src):
        return None
    try:
        from PIL import Image
    except Exception:
        return src
    try:
        os.makedirs(os.path.dirname(tp), exist_ok=True)
        im = Image.open(src).convert("RGB")
        im.thumbnail((max_side, max_side))
        im.save(tp, "JPEG", quality=82)
        return tp
    except Exception:
        return src


def delete(root: str, rid: str) -> bool:
    items = load_index(root)
    rec = next((x for x in items if x.get("id") == rid), None)
    if not rec:
        return False
    for p in (path_of(root, rec), thumb_path(root, rec)):
        try:
            if os.path.isfile(p):
                os.remove(p)
        except OSError:
            pass
    save_index(root, [x for x in items if x.get("id") != rid])
    return True


def set_meta(root: str, rid: str, **kw) -> bool:
    items = load_index(root)
    for it in items:
        if it.get("id") == rid:
            for k in ("title", "tags", "note", "fav"):
                if k in kw:
                    it[k] = kw[k]
            save_index(root, items)
            return True
    return False


def search(root: str, q: str = "", *, fav_only: bool = False,
           limit: int = 20, offset: int = 0) -> Dict[str, Any]:
    """搜标题/提示词/标签，返回 `{total, all, items}`。"""
    items = load_index(root)
    q = (q or "").strip().lower()

    def hit(it):
        if fav_only and not it.get("fav"):
            return False
        if not q:
            return True
        blob = " ".join(str(it.get(k) or "") for k in ("title", "prompt", "note", "style", "uid", "chat"))
        blob += " " + " ".join(str(x) for x in (it.get("tags") or []))
        return q in blob.lower()

    sel = [it for it in items if hit(it)]
    sel.sort(key=lambda x: str(x.get("at") or ""), reverse=True)
    try:
        limit = max(1, min(200, int(limit)))
        offset = max(0, int(offset))
    except (TypeError, ValueError):
        limit, offset = 20, 0
    return {"all": len(items), "total": len(sel), "items": sel[offset:offset + limit]}
