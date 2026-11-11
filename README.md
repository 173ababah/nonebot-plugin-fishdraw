# nonebot-plugin-fishdraw 🐟

> `/画图 一只坐窗台的白猫` → 本地 ComfyUI（Qwen-Image turbo）出图，**不调用任何大模型**。
> 文生图 / 以图生图 / 换装局部重绘 / 画风模板 / 配色锁，全在这一个插件里。

这个插件是从一个跑了半年的 QQ 机器人（[肥鱼人设](https://github.com/173ababah)）里拆出来的画图部分，
所有"为什么这么写"的注释都是**线上踩过的坑**，不是理论。

## 它能干什么

| 命令 | 权限 | 说明 |
|------|------|------|
| `/画图 <描述>` | 所有人 | 文生图 |
| `/画图 二次元 一只猫` | 所有人 | 前面写**画风模板名**，后面才是描述 |
| `/画图 换装 穿白衬衫` | 所有人 | 命中 `wear` 类模板时走**局部重绘**（只改衣服，脸不动） |
| `/图库`、`/图库 猫`、`/图库 收藏` | 所有人 | 翻历史出图（含提示词、耗时、收藏） |
| `/模板` | 超管 | 列模板 / `改 <名字> <提示词>` / `停 <名字>` / `删 <名字>` |
| `/nsfw on` | 超管 | 本会话允许裸露（默认关，正向会顶「穿着完整」） |

## 装法

```bash
pip install nonebot-plugin-fishdraw[skin]     # skin = numpy + pillow（配色锁要用）
```

`.env`：

```ini
FISHDRAW_GATEWAY=http://127.0.0.1:18188
FISHDRAW_STEPS=8
FISHDRAW_SIZE=1024x1024
FISHDRAW_TIMEOUT=600
```

网关指的是 [ComfyUI-Local-Infinite-Canvas](https://github.com/) 那套 `/v1/images/*` HTTP 接口
（`generations` / `edits`，`mode` = `t2i|edit|inpaint|remove|outpaint`）。
不想用网关也行——把 `gateway.py` 里的两个函数换成本地 `comfy_exec` 调用即可，
上层 `prompt.py` / `templates.py` / `skin.py` 都是纯函数，与传输层无关。

## 三个关键设计（改之前先看这段）

### 1. turbo 模型只认正向提示词

CFG=1 时负向几乎无效。所以：

- 「别脱」不能写进 negative，要往**正向**顶 `fully clothed, wearing complete outfit`
- 「保持原图画风」不是不写风格词，而是顶 `keep the original art style…` 守护词
- 画质词（`masterpiece, highly detailed`）**只在有明确画风时**才加；
  保留原图画风时加它会把简笔表情包重绘成 CG 写实

### 2. 长度闸在本地算（`prompt.plim`）

```
normal : 总长 ≤ 300
long   : 总长 ≤ min(4200, len(底稿) + 300)
act    : 总长 ≤ min(2600, len(底稿) + 400)
```

超了就截用户那段并在回执里说明。**别指望网关帮你截**——它有时静默截断、有时直接画崩。

### 3. 配色锁（`skin.py`）

以图生图时肤色会一轮比一轮深。做法：

1. 取 **4 档亮度**（1 维 k-means），分别给值——只给一个均值时模型会拿中间调铺满整张脸
2. **排除被截白的像素**（lum > 250）：白布/白边在压缩后会变纯白，
   锁里出现 `#FFFFFF 明度 255` 模型做不到，会把整段锁丢掉
3. **只要暖色像素**（`Cr-Cb ≥ 20` 且 `R-B ≥ 10`）：头发、灰衣服的色度离肤色很近，放宽就取错
4. 锁**前置**到提示词最前面，并在末尾再补一句「不要变深」（模型对末尾更敏感）

## 模板的 `kind` 语义（混了就会出怪图）

| kind | 作用 | 关系 |
|------|------|------|
| `char` | 角色画风 | 和别的 `char` **互斥** |
| `scene` | 场景氛围 | 可与 `char` 叠加 |
| `wear` | 换装 | 触发**局部重绘** |
| `act` | 动作 | **整段替换**提示词 |
| `size` | 尺寸（巨乳/贫乳） | 只贴一段话，**不产生画风词** |
| `post` | 后处理 | 上图之后再处理，不产提示词 |

⚠️ `size` / `post` 单独选中 = **没选画风**。判断"要不要补默认画风"只能看 `char/wear/scene`
（线上 bug：`/画图 贫乳` 因为列表非空就不补默认画风，配真人参考图直接出摄影照）。

## 测试

```bash
python -m pytest tests -q      # 30 passed
```

覆盖：长度闸边界、画风词选择、模板 CRUD/去重、图库分页、配色锁（含纯白背景/灰度图两个坑）。

## License

MIT
