"""模板库 / 图库 / 网关参数处理的单元测试（不需要 nonebot、不联网）。"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "nonebot_plugin_fishdraw"))

import gallery  # noqa: E402
import templates  # noqa: E402

ITEMS = [
    {"id": "二次元", "kind": "char", "prompt": "anime"},
    {"id": "水墨", "kind": "scene", "prompt": "ink"},
    {"id": "贫乳", "kind": "size", "prompt": "flat chest"},
    {"id": "脱衣", "kind": "act", "prompt": "undress", "enabled": False},
]


def test_kinds_normalized():
    items = templates.load.__globals__  # noqa: F841  (只是确保模块可导入)
    rec = templates._norm_item({"id": "x", "kind": "什么鬼"})
    assert rec["kind"] == "char"


def test_save_and_load_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "s.json")
        assert templates.save(p, ITEMS)
        got = templates.load(p)
        assert [x["id"] for x in got] == [x["id"] for x in ITEMS]
        assert got[0]["prompt"] == "anime"


def test_find_case_insensitive_and_suffix():
    assert templates.find(ITEMS, "二次元")["id"] == "二次元"
    assert templates.find(ITEMS, "  水墨 ")["id"] == "水墨"
    assert templates.find(ITEMS, "不存在") is None


def test_enabled_filter():
    assert "脱衣" not in [x["id"] for x in templates.enabled(ITEMS)]


def test_has_style_kind_ignores_size_only():
    picked = templates.styles_of(ITEMS, ["贫乳"])
    assert picked and not templates.has_style_kind(picked)


def test_has_style_kind_true_for_char():
    picked = templates.styles_of(ITEMS, ["二次元", "贫乳"])
    assert templates.has_style_kind(picked)


def test_act_prompt_and_merged_positive():
    picked = templates.styles_of(ITEMS + [{"id": "脱衣2", "kind": "act", "prompt": "undress"}],
                                 ["脱衣2", "贫乳"])
    assert templates.act_prompt(picked) == "undress"
    assert "flat chest" in templates.merged_positive(picked)


def test_upsert_replaces_by_id():
    out = templates.upsert(ITEMS, {"id": "二次元", "kind": "char", "prompt": "anime v2"})
    hit = templates.find(out, "二次元")
    assert hit["prompt"] == "anime v2"
    assert len(out) == len(ITEMS)


def test_remove():
    out = templates.remove(ITEMS, "水墨")
    assert templates.find(out, "水墨") is None


def test_gallery_add_search_delete():
    with tempfile.TemporaryDirectory() as d:
        png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
        rec = gallery.add(d, png, prompt="anime cat", uid="100", chat="group_1")
        assert rec and os.path.isfile(os.path.join(d, rec["file"]))
        res = gallery.search(d, "cat")
        assert res["total"] == 1 and res["all"] == 1
        assert gallery.search(d, "dog")["total"] == 0
        assert gallery.set_meta(d, rec["id"], fav=True, title="猫")
        assert gallery.search(d, "", fav_only=True)["total"] == 1
        assert gallery.delete(d, rec["id"])
        assert gallery.search(d, "")["all"] == 0


def test_gallery_search_pagination():
    with tempfile.TemporaryDirectory() as d:
        png = b"\x89PNG\r\n\x1a\n" + b"0" * 16
        for i in range(5):
            gallery.add(d, png, id="20261111-00000%d-1" % i, prompt="p%d" % i)
        page = gallery.search(d, "", limit=2, offset=2)
        assert page["total"] == 5 and len(page["items"]) == 2
        assert page["items"][0]["id"] == "20261111-000002-1"   # 新→旧

