"""配色锁的单元测试（合成图，不依赖外部素材）。

覆盖三个真实踩过的坑：
1. `np.sort` 返回 ndarray → `if not list` 抛异常（整个 probe 变 None）
2. 纯白背景若被当成皮肤 → 锁里出现 `#FFFFFF`，模型会把整段锁丢掉
3. 冷色/灰色像素混进来 → 锁出来的肤色偏灰紫
"""

import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "nonebot_plugin_fishdraw"))

import skin  # noqa: E402

try:
    from PIL import Image
    HAS_PIL = True
except Exception:  # pragma: no cover
    HAS_PIL = False

import pytest


def _png(size=(240, 240), bg=(20, 190, 90), box=(60, 120, 180, 240), fg=(246, 206, 201)):
    im = Image.new("RGB", size, bg)
    for x in range(box[0], min(box[2], size[0])):
        for y in range(box[1], min(box[3], size[1])):
            im.putpixel((x, y), fg)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


@pytest.mark.skipif(not HAS_PIL, reason="需要 pillow")
def test_probe_returns_bands_not_none():
    p = skin.probe(_png())
    assert p is not None
    assert p["bands"], "取不到分档"
    assert p["base"].startswith("#")


@pytest.mark.skipif(not HAS_PIL, reason="需要 pillow")
def test_probe_ignores_white_background():
    # 大半是纯白，皮肤只占一小块：base 不能是 #FFFFFF
    p = skin.probe(_png(bg=(255, 255, 255), box=(100, 180, 200, 240)))
    if p:
        assert p["base"].upper() != "#FFFFFF"
        text = skin.color_lock_text(p)
        assert "#FFFFFF" not in text


@pytest.mark.skipif(not HAS_PIL, reason="需要 pillow")
def test_probe_gray_image_returns_none():
    assert skin.probe(_png(bg=(120, 120, 120), fg=(120, 120, 120))) is None


def test_lock_text_empty_without_probe():
    assert skin.color_lock_text(None) == ""
    assert skin.skin_tail_text(None) == ""


@pytest.mark.skipif(not HAS_PIL, reason="需要 pillow")
def test_lock_text_shape_and_limit():
    p = skin.probe(_png())
    text = skin.color_lock_text(p)
    assert text.endswith("。")
    assert len(text) <= skin.MAX_LOCK_CHARS
    assert "#FFFFFF" not in text
    assert skin.skin_tail_text(p).startswith("（肤色锁定")


def test_tone_word_buckets():
    assert skin.tone_word((250, 248, 246)) == "极浅冷白"
    assert skin.tone_word((246, 206, 201)) == "浅白"
    assert skin.tone_word((140, 100, 90)) == "偏深"
