"""画风模板库（data/draw_styles.json）。

文件结构：

```json
{
  "version": 1,
  "items": [
    {"id": "二次元", "kind": "char", "prompt": "anime style, cel shading",
     "negative": "", "enabled": true, "auto_ref": "", "note": "默认画风"}
  ]
}
```

`kind` 的语义（**这个必须严格区分，混了就会出怪图**）：

| kind    | 作用 | 互相关系 |
|---------|------|----------|
| `char`  | 角色画风 | 和别的 `char` **互斥**，只取第一个 |
| `scene` | 场景/氛围 | 可以和 `char` **叠加** |
| `wear`  | 换装 | 触发**局部重绘**（走 inpaint 而不是整图改） |
| `post`  | 后处理 | 上图之后再做（马赛克之类），不产生提示词 |
| `size`  | 胸部尺寸 | 只贴一段话，**不产生画风词**（比如 巨乳/贫乳） |
| `act`   | 动作 | **整段替换**提示词，不顶风格词、不补构图 |

⚠️ `size` / `post` 单独选中时等于「没选画风」——判断"要不要补默认画风"必须只看 `char`/`wear`/`scene`。
（线上踩过：`/画图 贫乳` 因为列表非空就不补默认画风，配一张真人参考图直接出摄影照。）
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

KINDS = ("char", "scene", "act", "wear", "post", "size")
STYLE_KINDS = ("char", "wear", "scene")     # 只有这几种会产生"画风"
_lock = threading.Lock()


def _norm_item(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    i = str(raw.get("id") or raw.get("name") or "").strip()
    if not i:
        return None
    kind = str(raw.get("kind") or "char").strip().lower()
    if kind not in KINDS:
        kind = "char"
    return {
        "id": i,
        "kind": kind,
        "prompt": str(raw.get("prompt") or ""),
        "negative": str(raw.get("negative") or ""),
        "enabled": bool(raw.get("enabled", True)),
        "auto_ref": str(raw.get("auto_ref") or ""),
        "note": str(raw.get("note") or ""),
    }


def load(path: str) -> List[Dict[str, Any]]:
    """读模板文件（**故意不做 mtime 缓存**：文件几百字节，热读最快也最不会踩坑）。"""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f) or {}
    except (OSError, ValueError):
        return []
    items = data.get("items") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    out = []
    for raw in items:
        it = _norm_item(raw)
        if it:
            out.append(it)
    return out


def save(path: str, items: List[Dict[str, Any]]) -> bool:
    """原子写回（先写 .tmp 再 replace，避免半个文件被读到）。"""
    obj = {"version": 1, "items": [_norm_item(i) for i in items if _norm_item(i)]}
    d = os.path.dirname(os.path.abspath(path))
    try:
        os.makedirs(d, exist_ok=True)
        tmp = path + ".tmp"
        with _lock:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False, indent=1)
            os.replace(tmp, path)
        return True
    except OSError:
        return False


def find(items: List[Dict[str, Any]], key: str) -> Optional[Dict[str, Any]]:
    """按 id 或名字找（大小写不敏感，去掉首尾空白）。"""
    k = str(key or "").strip().lower()
    if not k:
        return None
    for it in items:
        if it["id"].lower() == k:
            return it
    for it in items:
        if it["id"].lower().endswith(k):
            return it
    return None


def enabled(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [it for it in items if it.get("enabled", True)]


def upsert(items: List[Dict[str, Any]], rec: Dict[str, Any]) -> List[Dict[str, Any]]:
    """新增或按 id 覆盖；返回新列表（不改入参）。"""
    it = _norm_item(rec)
    if not it:
        return list(items)
    out = [x for x in items if x["id"] != it["id"]]
    out.append(it)
    return out


def remove(items: List[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
    hit = find(items, key)
    if not hit:
        return list(items)
    return [x for x in items if x["id"] != hit["id"]]


def styles_of(items: List[Dict[str, Any]], keys: List[str] | None) -> List[Dict[str, Any]]:
    """把用户写的若干名字换成模板记录（忽略找不到的、忽略停用的）。"""
    out = []
    for k in (keys or []):
        it = find(items, k)
        if it and it.get("enabled", True) and it not in out:
            out.append(it)
    return out


def has_style_kind(picked: List[Dict[str, Any]]) -> bool:
    """选中的里面有没有「真正产生画风」的模板（见模块注释）。"""
    return any(it.get("kind") in STYLE_KINDS for it in picked)


def act_prompt(picked: List[Dict[str, Any]]) -> str:
    """`act` 模板整段替换提示词 → 返回第一段 act 的 prompt（没有就空串）。"""
    for it in picked:
        if it.get("kind") == "act" and it.get("prompt"):
            return it["prompt"]
    return ""


def merged_positive(picked: List[Dict[str, Any]]) -> str:
    """把 `size` 这类"只贴一段话"的模板拼起来（不含 char/scene 的画风词）。"""
    parts = []
    for it in picked:
        if it.get("kind") in ("size", "post") and it.get("prompt"):
            parts.append(it["prompt"])
    return ", ".join(parts)


def touch_stamp(path: str) -> float:
    """给测试/热读用的 mtime 助手。"""
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def now_stamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")
