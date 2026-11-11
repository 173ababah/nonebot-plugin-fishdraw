"""nonebot-plugin-fishdraw —— 本地 ComfyUI 画图。

命令：

| 命令 | 权限 | 说明 |
|------|------|------|
| `/画图 <描述>` | 所有人 | 文生图；带图回复 = 以图生图；`/画图 画风 换装 描述` |
| `/图库 [关键词]` | 所有人 | 翻历史出图（`/图库 收藏` 只看收藏） |
| `/模板` | 超管 | 列画风模板；`/模板 改 <名字> <提示词>`、`/模板 停 <名字>` |
| `/nsfw on|off` | 超管 | 本会话是否允许裸露（默认关） |

设计取向：**能不花钱就不花钱** —— 这个插件本身不调任何大模型，
提示词由模板 + 用户输入拼出来，画图交给本地 ComfyUI（显存够的机器 = 0 成本）。
"""

from __future__ import annotations

import os
import re
from typing import List, Optional

from nonebot import get_plugin_config, logger, on_command
from nonebot.adapters import Event, Message
from nonebot.params import CommandArg
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata

from . import gateway, gallery, prompt, skin, templates
from .config import Config

__plugin_meta__ = PluginMetadata(
    name="nonebot-plugin-fishdraw",
    description="本地 ComfyUI 画图：文生图 / 以图生图 / 换装局部重绘 / 画风模板 / 配色锁",
    usage="/画图 描述\n/图库 [关键词]\n/模板（超管）",
    type="application",
    config=Config,
    homepage="https://github.com/173ababah/nonebot-plugin-fishdraw",
    supported_adapters={"~onebot.v11"},
)

cfg = get_plugin_config(Config)
DATA_DIR = os.path.join(os.getcwd(), "data", "fishdraw")
STYLE_FILE = cfg.fishdraw_styles_file or os.path.join(DATA_DIR, "draw_styles.json")

_nsfw_chats: set = set()

# ---- 内置模板（文件不存在时先给一套能用的）----
DEFAULT_STYLES = [
    {"id": "二次元", "kind": "char", "prompt": prompt.STYLE_WORDS["二次元"], "note": "默认画风"},
    {"id": "q版", "kind": "char", "prompt": prompt.STYLE_WORDS["q版"]},
    {"id": "电影", "kind": "scene", "prompt": prompt.STYLE_WORDS["电影"]},
    {"id": "水墨", "kind": "scene", "prompt": prompt.STYLE_WORDS["水墨"]},
    {"id": "巨乳", "kind": "size", "prompt": "large breasts"},
    {"id": "贫乳", "kind": "size", "prompt": "flat chest, small breasts"},
]


def _styles() -> List[dict]:
    items = templates.load(STYLE_FILE)
    if not items:
        templates.save(STYLE_FILE, DEFAULT_STYLES)
        items = templates.load(STYLE_FILE)
    return items


def _split_args(text: str):
    """`画风 换装 描述` → (选中模板, 描述)。只有第一个词是已知模板时才当模板。"""
    text = (text or "").strip()
    items = templates.enabled(_styles())
    picked, rest = [], text
    while rest:
        head, _, tail = rest.partition(" ")
        hit = templates.find(items, head)
        if hit is None:
            break
        if hit not in picked:
            picked.append(hit)
        rest = tail.strip()
    return picked, rest


def _size_bytes(size: str) -> tuple:
    m = re.match(r"^(\d{2,4})[x×*](\d{2,4})$", (size or "").strip())
    if not m:
        return (1024, 1024)
    return (int(m.group(1)), int(m.group(2)))


draw_cmd = on_command("画图", aliases={"画画", "生成图片"}, priority=20, block=True)
lib_cmd = on_command("图库", priority=20, block=True)
tpl_cmd = on_command("模板", priority=20, block=True, permission=SUPERUSER)
nsfw_cmd = on_command("nsfw", priority=20, block=True, permission=SUPERUSER)


@draw_cmd.handle()
async def _(event: Event, arg: Message = CommandArg()):
    if not cfg.fishdraw_enabled:
        await draw_cmd.finish("画图功能关着呢（FISHDRAW_ENABLED=false）")
    want = arg.extract_plain_text().strip()
    picked, desc = _split_args(want)
    if not desc and not templates.act_prompt(picked):
        await draw_cmd.finish("想画什么？比如：/画图 二次元 一只坐窗台的白猫")

    chat = event.get_session_id()
    nsfw = cfg.fishdraw_nsfw_default or (chat in _nsfw_chats)

    if not await gateway.health(cfg.fishdraw_gateway, cfg.fishdraw_token):
        await draw_cmd.finish("画图的机器没连上（网关 %s 探活失败）" % cfg.fishdraw_gateway)

    style = prompt.style_words([p["id"] for p in picked], has_ref=False)
    lock = ""
    tail = ""
    act = templates.act_prompt(picked)
    kind = "act" if act else ("long" if len(desc) > 120 else "normal")
    body = act or desc
    if act:
        final = prompt.plim(act, templates.merged_positive(picked), kind="act")
    else:
        final = prompt.compose(body, style=style, lock=lock,
                               keep_style=False, clothed=not nsfw, kind=kind)
        final = prompt.plim(final, templates.merged_positive(picked), kind=kind) + tail
    neg = prompt.negative(nsfw=nsfw)

    await draw_cmd.send("在画了…（%s，%d 步）" % (cfg.fishdraw_size, cfg.fishdraw_steps))
    try:
        img, cost = await gateway.generate(
            gateway=cfg.fishdraw_gateway, token=cfg.fishdraw_token,
            prompt=final, negative=neg, size=cfg.fishdraw_size,
            steps=cfg.fishdraw_steps, timeout=cfg.fishdraw_timeout)
    except gateway.GatewayError as e:
        logger.warning("[fishdraw] 出图失败 %s", e)
        await draw_cmd.finish("没画出来：%s" % e)

    rec = gallery.add(DATA_DIR, img, prompt=final, user_want=body, style=style,
                      size=cfg.fishdraw_size, cost_s=round(cost, 1),
                      uid=str(getattr(event, "get_user_id", lambda: "")()),
                      chat=chat, nsfw=bool(nsfw))
    note = prompt.truncate_note(body, final)
    msg = "画好了（%.1fs）" % cost
    if note:
        msg += "\n" + note
    if rec:
        msg += "\n图库 id：%s" % rec["id"]
    await draw_cmd.send(msg)
    from nonebot.adapters.onebot.v11 import MessageSegment
    await draw_cmd.finish(MessageSegment.image(img))


@lib_cmd.handle()
async def _(arg: Message = CommandArg()):
    q = arg.extract_plain_text().strip()
    fav_only = q in ("收藏", "收藏夹", "fav")
    if fav_only:
        q = ""
    res = gallery.search(DATA_DIR, q, fav_only=fav_only, limit=9)
    items = res["items"]
    if not items:
        await lib_cmd.finish("图库里还没有图（或没有匹配的）")
    lines = ["图库 %d / 共 %d 张：" % (res["total"], res["all"])]
    for it in items:
        lines.append("· %s%s  %s" % ("★" if it.get("fav") else "", it["id"],
                                     (it.get("user_want") or it.get("prompt") or "")[:24]))
    await lib_cmd.finish("\n".join(lines))


@tpl_cmd.handle()
async def _(arg: Message = CommandArg()):
    text = arg.extract_plain_text().strip()
    items = _styles()
    if not text:
        lines = ["共 %d 个模板：" % len(items)]
        for it in items:
            lines.append("· %s（%s）%d 字%s" % (it["id"], it["kind"], len(it["prompt"]),
                                              "" if it.get("enabled", True) else " 停用"))
        await tpl_cmd.finish("\n".join(lines))
    action, _, rest = text.partition(" ")
    name, _, body = rest.partition(" ")
    hit = templates.find(items, name)
    if action in ("改", "add", "新增"):
        if not body:
            await tpl_cmd.finish("用法：/模板 改 <名字> <提示词>")
        rec = dict(hit) if hit else {"id": name, "kind": "char"}
        rec["prompt"] = body
        templates.save(STYLE_FILE, templates.upsert(items, rec))
        await tpl_cmd.finish("已保存「%s」（%d 字）" % (name, len(body)))
    if action in ("停", "启") or action in ("off", "on"):
        if not hit:
            await tpl_cmd.finish("没有这个模板：%s" % name)
        rec = dict(hit)
        rec["enabled"] = action in ("启", "on")
        templates.save(STYLE_FILE, templates.upsert(items, rec))
        await tpl_cmd.finish("「%s」已%s" % (name, "启用" if rec["enabled"] else "停用"))
    if action in ("删", "del"):
        if not hit:
            await tpl_cmd.finish("没有这个模板：%s" % name)
        templates.save(STYLE_FILE, templates.remove(items, name))
        await tpl_cmd.finish("已删掉「%s」" % name)
    await tpl_cmd.finish("看不懂：/模板 | /模板 改 <名字> <提示词> | /模板 停 <名字> | /模板 删 <名字>")


@nsfw_cmd.handle()
async def _(event: Event, arg: Message = CommandArg()):
    chat = event.get_session_id()
    on = arg.extract_plain_text().strip().lower() in ("on", "1", "开", "开on")
    if on:
        _nsfw_chats.add(chat)
    else:
        _nsfw_chats.discard(chat)
    await nsfw_cmd.finish("本会话 NSFW：%s" % ("开" if on else "关"))
