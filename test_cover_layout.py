#!/usr/bin/env python3
# 独立封面排版测试脚本：复用正式 CoverRenderer，仅注入固定测试数据。

import os
import sys
import types


def install_import_stubs():
    """
    为独立测试脚本补齐最小 import 依赖。
    这样即使当前环境没装 dotenv/openai，也不影响复用正式 CoverRenderer 的排版逻辑。
    """
    try:
        import dotenv  # noqa: F401
    except ModuleNotFoundError:
        dotenv_stub = types.ModuleType("dotenv")
        dotenv_stub.load_dotenv = lambda *args, **kwargs: False
        sys.modules["dotenv"] = dotenv_stub

    try:
        import openai  # noqa: F401
    except ModuleNotFoundError:
        openai_stub = types.ModuleType("openai")

        class OpenAI:  # 仅用于通过 import；本测试脚本不会真正调用 LLM。
            def __init__(self, *args, **kwargs):
                pass

        openai_stub.OpenAI = OpenAI
        sys.modules["openai"] = openai_stub


install_import_stubs()

import config
from services.cover_renderer import CoverRenderer


TEST_IMAGE_PATH = "/Users/lihouyan/Documents/电影图片资源/previews/landscape/新片速递｜2026三月观影指南/1.jpg"
OUTPUT_PATH = os.path.join(config.BASE_DIR, "test_cover_output.jpg")
TEMP_OUTPUT_DIR = os.path.join(config.BASE_DIR, ".cover_test_output")

TEST_COVER_DATA = {
    "path": TEST_IMAGE_PATH,
    "title_lines": ["2026.3", "所有名字都会", "重新发光"],
    "raw_title": r"在海风尽头\n所有名字都会\n重新发光",
}

TEST_MOVIES = [
    {
        "name": "坠入地球黄昏前的宇航员",
        "original_title": "The Astronaut Who Fell Before Sunset",
        "is_china_film": False,
    },
    {
        "name": "她在海风里想起所有未寄出的信",
        "original_title": "All the Letters She Never Sent",
        "is_china_film": False,
    },
    {
        "name": "比宇宙尽头更远的回声",
        "original_title": "Echoes Beyond the Edge of the Universe",
        "is_china_film": False,
    },
    {
        "name": "雾中列车会开往记忆最深处",
        "original_title": "The Train Through the Deepest Fog of Memory",
        "is_china_film": False,
    },
    {
        "name": "春天在旧胶片里慢慢复燃",
        "original_title": "",
        "is_china_film": True,
    },
    {
        "name": "月光照进废墟时我们谈论明天",
        "original_title": "When Moonlight Crossed the Ruins We Spoke of Tomorrow",
        "is_china_film": False,
    },
    {
        "name": "雾中列车会开往记忆最深处",
        "original_title": "The Train Through the Deepest Fog of Memory",
        "is_china_film": False,
    },{
        "name": "雾中列车会开往记忆最深处",
        "original_title": "The Train Through the Deepest F",
        "is_china_film": False,
    },
]


def build_renderer() -> CoverRenderer:
    """
    复用正式 CoverRenderer。
    为了让测试稳定可复现，这里固定英文名显示规则：
    非中国电影且 original_title 非空时，直接显示英文行。
    """
    renderer = CoverRenderer()
    renderer._decide_cover_en_name_visibility = lambda movies: {
        idx: (not bool(movie.get("is_china_film"))) and bool(str(movie.get("original_title", "")).strip())
        for idx, movie in enumerate(movies)
    }
    return renderer


def main() -> int:
    if not os.path.exists(TEST_IMAGE_PATH):
        print(f"❌ 找不到测试底图: {TEST_IMAGE_PATH}")
        return 1

    os.makedirs(TEMP_OUTPUT_DIR, exist_ok=True)

    renderer = build_renderer()
    render_path = renderer.render(TEST_COVER_DATA, TEST_MOVIES, TEMP_OUTPUT_DIR)
    if not render_path or (not os.path.exists(render_path)):
        print("❌ 封面测试图生成失败。")
        return 1

    os.replace(render_path, OUTPUT_PATH)
    try:
        os.rmdir(TEMP_OUTPUT_DIR)
    except OSError:
        pass

    print(f"✅ 测试封面已生成: {OUTPUT_PATH}")
    print(f"🖼️ 测试底图: {TEST_IMAGE_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
