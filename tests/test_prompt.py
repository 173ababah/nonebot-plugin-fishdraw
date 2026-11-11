"""提示词拼装 / 长度闸的单元测试（不需要 nonebot，纯函数）。"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "nonebot_plugin_fishdraw"))

import prompt  # noqa: E402  （纯模块，不依赖 nonebot）


def test_plim_normal_cap_300():
    base = "anime style"
    long_extra = "x" * 500
    out = prompt.plim(base, long_extra, kind="normal")
    assert len(out) <= 300
    assert out.startswith(base)
    assert out.endswith("…")


def test_plim_short_extra_untouched():
    out = prompt.plim("anime style", "a cat", kind="normal")
    assert out == "anime style, a cat"


def test_plim_act_cap_is_lenient():
    base = "a" * 2000
    out = prompt.plim(base, "b" * 500, kind="act")
    assert len(out) <= 2600
    assert base in out


def test_plim_long_cap():
    base = "a" * 1000
    out = prompt.plim(base, "b" * 1000, kind="long")
    assert len(out) <= min(4200, 1000 + 300)


def test_plim_empty_extra():
    assert prompt.plim("anime", "", "normal") == "anime"
    assert prompt.plim("", "cat", "normal") == "cat"


def test_style_words_default_for_t2i():
    assert "anime" in prompt.style_words(None, has_ref=False)


def test_style_words_empty_when_has_ref_and_no_pick():
    assert prompt.style_words(None, has_ref=True) == ""


def test_style_words_multiple():
    w = prompt.style_words(["二次元", "水墨"], has_ref=False)
    assert "anime" in w and "ink" in w


def test_compose_order_lock_first():
    out = prompt.compose("a girl", style="anime style", lock="肤色以 #F4D8C8 为主",
                         clothed=True, kind="normal")
    assert out.startswith("肤色")
    assert "a girl" in out


def test_compose_clothed_off_when_nsfw():
    out = prompt.compose("a girl", style="anime style", clothed=False)
    assert prompt.CLOTHED_LOCK not in out


def test_compose_keep_style_uses_guard_not_quality():
    out = prompt.compose("a girl", style="", keep_style=True)
    assert prompt.KEEP_STYLE_GUARD in out
    assert prompt.QUALITY_POSITIVE not in out


def test_negative_includes_nude_when_not_nsfw():
    assert "nude" in prompt.negative(nsfw=False)
    assert "nude" not in prompt.negative(nsfw=True)


def test_truncate_note():
    assert prompt.truncate_note("abc", "abc") == ""
    note = prompt.truncate_note("x" * 400, "x" * 200)
    assert "截到" in note

