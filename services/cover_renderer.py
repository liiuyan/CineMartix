import json
import os
from PIL import Image, ImageDraw, ImageFont

import config
from utils import LLMBrain


class CoverRenderer:
    """
    🎴 通用封面渲染器 (CoverRenderer)

    设计目标:
    1. 与具体赛道解耦，preview/collection 均可复用。
    2. 负责封面图渲染与水印英文名判定，不参与业务路由。
    """

    def __init__(self):
        # DeepSeek 英文名判定器（按需懒初始化，避免无封面任务额外开销）。
        self.brain = None

        # 封面图渲染配置（坐标原点在左上角；单位均为 px；颜色使用 RGBA）。
        self.cover_config = {
            "canvas_size": (1200, 1600),  # 输出画布尺寸(3:4)；改这里需同步调整标题/水印坐标
            "watermark": {
                "font_path": config.FONT_SCORE_PATH,  # 水印字体（中文/英文共用）
                "font_size": 45,  # 水印字号
                "color": (255, 255, 255, 70),  # 水印颜色与透明度（A 越小越淡）
                "start_x": 480,  # 水印列起始 X（越大越靠右）
                "start_y": 100,  # 水印分布起始 Y（第一条起点）
                "end_y": 1500,  # 水印分布结束 Y（最后一条接近这里）
                "en_offset_y": 50,  # 同一条目中，英文行相对中文行的纵向偏移
            },
            "title": {
                "start_x": 480,  # 三行主标题基准 X（第一行从这里开始）
                "start_y": 700,  # 三行主标题基准 Y（第一行从这里开始）
                "line_spacing": 20,  # 行间距（每行绘制后的额外间隔）
                "styles": [
                    # offset_x/offset_y 都是“相对偏移”：
                    # - offset_x: 在 title.start_x 基础上左右微调（+ 右移，- 左移）
                    # - offset_y: 在当前行默认 y 基础上上下微调（+ 下移，- 上移）

                    # 第 1 行样式（主视觉）
                    {"font_path": config.FONT_TITLE_PATH, "size": 180, "offset_x": 0, "offset_y": 0}, 
                    # 第 2 行样式
                    {"font_path": config.FONT_TITLE_PATH, "size": 120, "offset_x": 0, "offset_y": 0},  
                    # 第 3 行样式（可空，空行仅占位）
                    {"font_path": config.FONT_TITLE_PATH, "size": 120, "offset_x": 0, "offset_y": 0},  
                ],
                "color": (255, 255, 255, 255),  # 主标题颜色
                "stroke_width": 3,  # 主标题描边宽度（提高复杂底图可读性）
                "stroke_color": (0, 0, 0, 150),  # 主标题描边颜色与透明度
            },
        }

    def render(self, cover_data: dict, movies: list, output_dir: str) -> str | None:
        """
        渲染封面图（3:4）：
        1) 主标题三行（来自文件名中的字面量 \\n）
        2) 水印电影名（中文一行 + 可选英文一行）
        """
        # cover_data 由 PreviewTopicAgent 提供，结构受命名规则约束：
        # {
        #   "path": ".../xxx.jpg",
        #   "title_lines": ["第一行", "第二行", "第三行"],
        #   "raw_title": "第一行\\n第二行\\n第三行"
        # }
        image_path = cover_data.get("path")
        title_lines = cover_data.get("title_lines") or ["", "", ""]
        if not image_path or len(title_lines) != 3:
            print("   ⛔ 封面参数非法：缺少图片路径或主标题三行信息。")
            return None

        try:
            base_img = self._crop_and_resize_to_3_4(image_path, self.cover_config["canvas_size"])
        except Exception as e:
            print(f"   ⛔ 封面底图处理失败: {e}")
            return None

        txt_layer = Image.new("RGBA", base_img.size, (255, 255, 255, 0))
        draw_layer = ImageDraw.Draw(txt_layer)

        wm_conf = self.cover_config["watermark"]
        wm_font = self._safe_load_font(wm_conf["font_path"], wm_conf["font_size"])
        watermark_rows = self._build_cover_watermark_rows(movies)

        if watermark_rows:
            # 动态均分水印条目在纵向区间中的落点，保证不同电影数下视觉密度稳定。
            if len(watermark_rows) > 1:
                wm_step = (wm_conf["end_y"] - wm_conf["start_y"]) / (len(watermark_rows) - 1)
            else:
                wm_step = 0

            current_y = wm_conf["start_y"]
            for row in watermark_rows:
                # 先画中文电影名
                draw_layer.text(
                    (wm_conf["start_x"], current_y),
                    row["name_cn"],
                    font=wm_font,
                    fill=wm_conf["color"],
                )
                # 再画可选英文名（若命中显示条件）
                if row["name_en"]:
                    draw_layer.text(
                        (wm_conf["start_x"], current_y + wm_conf["en_offset_y"]),
                        row["name_en"],
                        font=wm_font,
                        fill=wm_conf["color"],
                    )
                current_y += wm_step

        merged = Image.alpha_composite(base_img, txt_layer)
        draw_base = ImageDraw.Draw(merged)

        title_conf = self.cover_config["title"]
        current_y = title_conf["start_y"]
        base_x = title_conf["start_x"]
        line_spacing = title_conf["line_spacing"]
        styles = title_conf["styles"]

        for idx, line_text in enumerate(title_lines):
            style = styles[idx] if idx < len(styles) else styles[-1]
            font = self._safe_load_font(style["font_path"], style["size"])

            current_y += style.get("offset_y", 0)
            actual_x = base_x + style.get("offset_x", 0)

            # 空行不绘制，但保留行高占位，确保你定义的三行布局稳定。
            if line_text:
                self._draw_text_with_stroke(
                    draw_base,
                    (actual_x, current_y),
                    line_text,
                    font,
                    title_conf["color"],
                    title_conf["stroke_width"],
                    title_conf["stroke_color"],
                )
            current_y += style["size"] + line_spacing

        os.makedirs(output_dir, exist_ok=True)
        save_path = os.path.join(output_dir, "preview_cover.jpg")
        merged.convert("RGB").save(save_path, quality=95)
        print("   ✅ 封面图渲染完成: preview_cover.jpg")
        return save_path

    def _build_cover_watermark_rows(self, movies: list) -> list:
        """
        构建封面水印条目：
        - 每条固定显示中文电影名
        - 英文行是否显示交给 DeepSeek 判定（失败可重试）
        """
        # 输入 movies 为 Writer 阶段后的标准化电影对象；这里不再重新查库。
        rows = []
        if not movies:
            return rows

        show_map = self._decide_cover_en_name_visibility(movies)
        for idx, movie in enumerate(movies):
            cn_name = str(movie.get("name", "")).strip()
            if not cn_name:
                continue

            en_name = ""
            if (not bool(movie.get("is_china_film"))) and show_map.get(idx):
                en_name = str(movie.get("original_title", "")).strip()

            rows.append({"name_cn": cn_name, "name_en": en_name})
        return rows

    def _decide_cover_en_name_visibility(self, movies: list) -> dict[int, bool]:
        """
        使用 DeepSeek 判断“原名是否应作为英文行显示”。
        失败时自动按配置次数重试，全部失败则默认不显示英文行。
        """
        # 默认全部 False，只有模型明确判定可显示才置 True，防止误显。
        result_map = {idx: False for idx in range(len(movies))}
        candidates = []
        for idx, movie in enumerate(movies):
            original_title = str(movie.get("original_title", "")).strip()
            is_china = bool(movie.get("is_china_film"))
            if is_china or (not original_title):
                continue
            candidates.append(
                {
                    "idx": idx,
                    "name": str(movie.get("name", "")).strip(),
                    "original_title": original_title,
                }
            )

        if not candidates:
            return result_map

        # 懒加载：仅当本批次存在可判定候选时才初始化 LLM 客户端。
        if self.brain is None:
            self.brain = LLMBrain()

        retry_times = max(
            1, int(getattr(config.Strategy.Preview, "COVER_EN_NAME_RETRY_TIMES", 3))
        )
        prompt = f"""
你是电影原名语言判定器。请判断每条 original_title 是否应作为“英文名”显示。

输入 JSON：
{json.dumps(candidates, ensure_ascii=False)}

判定标准：
1) show_en=true：original_title 明确是英文电影名（自然英文标题）。
2) show_en=false：非英文、混杂、无法确定、或不适合按英文名展示。
3) 严禁猜测；拿不准一律 false。

仅输出 JSON：
{{
  "results": [
    {{"idx": 0, "show_en": true}}
  ]
}}
"""

        valid_idx = {item["idx"] for item in candidates}
        for attempt in range(1, retry_times + 1):
            raw = self.brain.think(prompt, system_prompt="你是严格的JSON判定器，只输出JSON。")
            parsed = self._parse_cover_en_judge_response(raw, valid_idx)
            if parsed is not None:
                result_map.update(parsed)
                return result_map
            print(f"   ⚠️ 封面英文名判定解析失败，重试 {attempt}/{retry_times}。")

        print("   ⚠️ 封面英文名判定多次失败，已回退为不显示英文名。")
        return result_map

    def _parse_cover_en_judge_response(self, raw: str | None, valid_idx: set[int]) -> dict | None:
        """解析 DeepSeek 判定结果，成功返回 {idx: bool}，失败返回 None。"""
        if not raw:
            return None
        try:
            clean = raw.replace("```json", "").replace("```", "").strip()
            obj = json.loads(clean)
        except Exception:
            return None

        if isinstance(obj, dict):
            items = obj.get("results")
        elif isinstance(obj, list):
            items = obj
        else:
            return None

        if not isinstance(items, list):
            return None

        parsed = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            if "idx" not in item:
                continue
            try:
                idx = int(item.get("idx"))
            except Exception:
                continue
            if idx not in valid_idx:
                continue
            parsed[idx] = bool(item.get("show_en", False))

        # 至少解析到 1 条有效结果才认为成功。
        if not parsed:
            return None
        return parsed

    def _crop_and_resize_to_3_4(self, image_path: str, target_size: tuple[int, int]) -> Image.Image:
        """将图片居中裁剪为 3:4 并缩放到目标尺寸。"""
        img = Image.open(image_path).convert("RGBA")
        width, height = img.size
        target_w, target_h = target_size
        target_ratio = target_w / target_h
        current_ratio = width / height

        if current_ratio > target_ratio:
            new_width = int(height * target_ratio)
            left = (width - new_width) // 2
            img = img.crop((left, 0, left + new_width, height))
        elif current_ratio < target_ratio:
            new_height = int(width / target_ratio)
            top = (height - new_height) // 2
            img = img.crop((0, top, width, top + new_height))

        return img.resize(target_size, Image.Resampling.LANCZOS)

    def _draw_text_with_stroke(
        self,
        draw: ImageDraw,
        xy: tuple[int, float],
        text: str,
        font: ImageFont.FreeTypeFont,
        text_color: tuple,
        stroke_width: int,
        stroke_color: tuple,
    ):
        """绘制描边文本（用于封面三行主标题）。"""
        x, y = xy
        if stroke_width > 0:
            for dx in range(-stroke_width, stroke_width + 1):
                for dy in range(-stroke_width, stroke_width + 1):
                    if dx * dx + dy * dy <= stroke_width * stroke_width:
                        draw.text((x + dx, y + dy), text, font=font, fill=stroke_color)
        draw.text((x, y), text, font=font, fill=text_color)

    def _safe_load_font(self, path: str, size: int) -> ImageFont.FreeTypeFont:
        """字体兜底：缺字库或路径异常时返回默认字体，避免封面渲染崩溃。"""
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            return ImageFont.load_default()
