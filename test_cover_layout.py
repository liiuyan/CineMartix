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


TEST_IMAGE_PATH = "/Users/lihouyan/Documents/codes/little_red/资料/collections/电影三部曲｜那些影史上经典的三部曲——红白蓝/2.jpg"
OUTPUT_PATH = os.path.join(config.BASE_DIR, "test_cover_output.jpg")
TEMP_OUTPUT_DIR = os.path.join(config.BASE_DIR, ".cover_test_output")

# 测试模式参数：
# - TEST_COVER_MODE: "preview" / "collection"
# - TEST_SHOW_WATERMARK: 是否绘制电影名水印
# - TEST_SHOW_ENGLISH_NAMES: None 表示跟随赛道默认值（preview=True, collection=False）
TEST_COVER_MODE = "collection"
TEST_SHOW_WATERMARK = False
TEST_SHOW_ENGLISH_NAMES = None

# 测试态裁剪焦点覆盖：
# - None 表示沿用 CoverRenderer 正式配置
# - 填入 0.0-1.0 数值时，仅对本测试脚本生效，方便快速试焦点位置
TEST_FOCUS_X = None
TEST_FOCUS_Y = None

TEST_COVER_DATA = {
    "path": TEST_IMAGE_PATH,
    "title_lines": ["蓝白红三部曲", "", " "],
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
    为了让测试稳定可复现，这里允许测试脚本显式控制：
    1. 当前测试赛道（preview / collection）
    2. 英文名是否显示
    3. 裁剪焦点是否临时覆盖
    """
    renderer = CoverRenderer()
    show_english_names = _resolve_test_show_english_names()

    # 测试脚本不依赖真实 LLM 判定，直接用固定规则稳定复现英文行显示结果。
    renderer._decide_cover_en_name_visibility = lambda movies: {
        idx: (
            show_english_names
            and (not bool(movie.get("is_china_film")))
            and bool(str(movie.get("original_title", "")).strip())
        )
        for idx, movie in enumerate(movies)
    }
    _apply_test_crop_override(renderer)
    return renderer


def _resolve_test_show_english_names() -> bool:
    """
    解析测试脚本中的英文名开关。
    None 时按赛道默认值走：
    - preview: 显示英文名
    - collection: 不显示英文名
    """
    if TEST_SHOW_ENGLISH_NAMES is None:
        return str(TEST_COVER_MODE).strip().lower() == "preview"
    return bool(TEST_SHOW_ENGLISH_NAMES)


def _apply_test_crop_override(renderer: CoverRenderer):
    """
    将测试态焦点覆盖写到渲染器实例上。
    这样调试时不用反复修改正式配置文件，确认数值后再回写 CoverRenderer。
    """
    mode_key = str(TEST_COVER_MODE).strip().lower()
    crop_conf = renderer.cover_config.setdefault("crop", {})
    mode_conf = crop_conf.setdefault(mode_key, {"focus_x": 0.5, "focus_y": 0.5})

    if TEST_FOCUS_X is not None:
        mode_conf["focus_x"] = float(TEST_FOCUS_X)
    if TEST_FOCUS_Y is not None:
        mode_conf["focus_y"] = float(TEST_FOCUS_Y)


def main() -> int:
    if not os.path.exists(TEST_IMAGE_PATH):
        print(f"❌ 找不到测试底图: {TEST_IMAGE_PATH}")
        return 1

    os.makedirs(TEMP_OUTPUT_DIR, exist_ok=True)

    renderer = build_renderer()
    render_path = renderer.render(
        TEST_COVER_DATA,
        TEST_MOVIES,
        TEMP_OUTPUT_DIR,
        cover_mode=str(TEST_COVER_MODE).strip().lower(),
        show_english_names=_resolve_test_show_english_names(),
        show_watermark=bool(TEST_SHOW_WATERMARK),
        output_filename="test_cover_render.jpg",
    )
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
    print(
        "🧪 测试参数: "
        f"mode={TEST_COVER_MODE}, watermark={TEST_SHOW_WATERMARK}, "
        f"show_en={_resolve_test_show_english_names()}, "
        f"focus_x={TEST_FOCUS_X if TEST_FOCUS_X is not None else 'default'}, "
        f"focus_y={TEST_FOCUS_Y if TEST_FOCUS_Y is not None else 'default'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
