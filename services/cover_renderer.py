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
                "min_font_size": 30,  # 全局统一缩字号的最小下限
                "color": (255, 255, 255, 70),  # 水印颜色与透明度（A 越小越淡）
                "start_x": 480,  # 水印列起始 X（越大越靠右）
                "start_y": 100,  # 水印分布起始 Y（第一条起点）
                "end_y": 1550,  # 水印分布结束 Y（最后一条接近这里）
                "right_margin": 0,  # 水印文本块右边界距离画布右侧的留白
                "cn_max_lines": 2,  # 中文名最多换行数
                "en_max_lines": 2,  # 英文名最多换行数
                "line_spacing": 8,  # 中文/英文各自块内部的行间距
                "cn_en_gap": 12,  # 中文块与英文块之间的固定间距
                "min_item_gap": 24,  # 相邻电影条目的最小边缘间距
            },
            "title": {
                "start_x": 480,  # 三行主标题基准 X（第一行从这里开始）
                "start_y": 300,  # 三行主标题基准 Y（第一行从这里开始）
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
        watermark_rows = self._build_cover_watermark_rows(movies)

        if watermark_rows:
            watermark_layout = self._layout_watermark_blocks(
                draw_layer, watermark_rows, base_img.size
            )
            if watermark_layout is None:
                print("   ⛔ 封面水印排版失败：文本过长且已触及最小字号。")
                return None

            for block in watermark_layout["blocks"]:
                self._draw_watermark_block(draw_layer, wm_conf, block)

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
            # 标题位置回归参考工程逻辑：由当前行字号主导层级，再叠加统一 line_spacing。
            current_y += style["size"] + line_spacing

        os.makedirs(output_dir, exist_ok=True)
        save_path = os.path.join(output_dir, "preview_cover.jpg")
        merged.convert("RGB").save(save_path, quality=95)
        print("   ✅ 封面图渲染完成: preview_cover.jpg")
        return save_path

    def _layout_watermark_blocks(
        self, draw: ImageDraw.ImageDraw, watermark_rows: list, canvas_size: tuple[int, int]
    ) -> dict | None:
        """
        水印块总布局：
        1. 先按 collection 同口径的折行思路拆分中英文行
        2. 若放不下，所有条目统一缩字号
        3. 放得下后按“边缘间距等距”从上到下排布
        """
        wm_conf = self.cover_config["watermark"]
        available_height = wm_conf["end_y"] - wm_conf["start_y"]
        max_width = canvas_size[0] - wm_conf["start_x"] - wm_conf["right_margin"]
        if max_width <= 0 or available_height <= 0:
            return None

        start_size = int(wm_conf["font_size"])
        min_size = int(wm_conf["min_font_size"])
        item_count = len(watermark_rows)

        for font_size in range(start_size, min_size - 1, -1):
            font = self._safe_load_font(wm_conf["font_path"], font_size)
            measured_blocks = []
            total_height = 0

            for row in watermark_rows:
                block = self._measure_watermark_block(draw, row, font, max_width)
                if block is None:
                    measured_blocks = []
                    break
                measured_blocks.append(block)
                total_height += block["height"]

            if not measured_blocks:
                continue

            min_total_gap = wm_conf["min_item_gap"] * max(0, item_count - 1)
            if total_height + min_total_gap > available_height:
                continue

            actual_gap = 0
            if item_count > 1:
                actual_gap = (available_height - total_height) / (item_count - 1)

            current_y = float(wm_conf["start_y"])
            for block in measured_blocks:
                block["font"] = font
                block["y"] = current_y
                current_y += block["height"] + actual_gap

            return {"font_size": font_size, "gap": actual_gap, "blocks": measured_blocks}

        return None

    def _measure_watermark_block(
        self,
        draw: ImageDraw.ImageDraw,
        row: dict,
        font: ImageFont.FreeTypeFont,
        max_width: int,
    ) -> dict | None:
        """
        计算单个电影条目的水印块尺寸。
        规则：
        - 中文最多 2 行
        - 英文最多 2 行
        - 中英文之间固定留白
        """
        wm_conf = self.cover_config["watermark"]
        cn_lines = self._wrap_watermark_text(
            draw, row.get("name_cn", ""), font, max_width, wm_conf["cn_max_lines"]
        )
        if cn_lines is None or (not cn_lines):
            return None

        en_name = str(row.get("name_en", "") or "").strip()
        en_lines = []
        if en_name:
            en_lines = self._wrap_watermark_text(
                draw, en_name, font, max_width, wm_conf["en_max_lines"]
            )
            if en_lines is None:
                return None

        cn_height = self._measure_multiline_height(draw, cn_lines, font, wm_conf["line_spacing"])
        en_height = self._measure_multiline_height(draw, en_lines, font, wm_conf["line_spacing"])
        block_height = cn_height
        if en_lines:
            block_height += wm_conf["cn_en_gap"] + en_height

        return {
            "name_cn": row.get("name_cn", ""),
            "name_en": en_name,
            "cn_lines": cn_lines,
            "en_lines": en_lines,
            "cn_height": cn_height,
            "en_height": en_height,
            "height": block_height,
        }

    def _draw_watermark_block(
        self, draw: ImageDraw.ImageDraw, wm_conf: dict, block: dict
    ):
        """按测量结果绘制单个水印块。"""
        current_y = block["y"]
        font = block["font"]
        current_y = self._draw_multiline_text(
            draw,
            wm_conf["start_x"],
            current_y,
            block["cn_lines"],
            font,
            wm_conf["color"],
            wm_conf["line_spacing"],
        )

        if block["en_lines"]:
            current_y += wm_conf["cn_en_gap"]
            self._draw_multiline_text(
                draw,
                wm_conf["start_x"],
                current_y,
                block["en_lines"],
                font,
                wm_conf["color"],
                wm_conf["line_spacing"],
            )

    def _draw_multiline_text(
        self,
        draw: ImageDraw.ImageDraw,
        x: int,
        y: float,
        lines: list[str],
        font: ImageFont.FreeTypeFont,
        color: tuple,
        line_spacing: int,
    ) -> float:
        """逐行绘制文本块，并返回块底部 y。"""
        current_y = y
        for idx, line in enumerate(lines):
            draw.text((x, current_y), line, font=font, fill=color)
            current_y += self._measure_text_height(draw, line, font)
            if idx < len(lines) - 1:
                current_y += line_spacing
        return current_y

    def _measure_multiline_height(
        self,
        draw: ImageDraw.ImageDraw,
        lines: list[str],
        font: ImageFont.FreeTypeFont,
        line_spacing: int,
    ) -> int:
        """计算多行文本块总高度。"""
        if not lines:
            return 0
        total = 0
        for idx, line in enumerate(lines):
            total += self._measure_text_height(draw, line, font)
            if idx < len(lines) - 1:
                total += line_spacing
        return total

    def _measure_text_height(
        self, draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont
    ) -> int:
        """测量单行文本高度。"""
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[3] - bbox[1]

    def _wrap_watermark_text(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.FreeTypeFont,
        max_width: int,
        max_lines: int,
    ) -> list[str] | None:
        """
        水印换行器：
        - 沿用 collection 金句的倒三角折行思路
        - 超过最大行数则视为当前字号放不下
        """
        clean_text = str(text or "").strip()
        if not clean_text:
            return []
        if draw.textlength(clean_text, font=font) <= max_width:
            return [clean_text]

        lines = self._inverted_pyramid_wrap(clean_text, font, draw, max_width)
        if len(lines) <= max_lines:
            return lines
        return None

    def _inverted_pyramid_wrap(
        self,
        text: str,
        font: ImageFont.FreeTypeFont,
        draw: ImageDraw.ImageDraw,
        max_width: int,
    ) -> list[str]:
        """沿用 collection 金句的倒三角视觉平衡折行逻辑。"""
        total_w = draw.textlength(text, font=font)
        if total_w <= max_width:
            return [text]

        ratio = 0.55
        target_w = min(total_w * ratio, max_width)
        lines = []
        punctuation_avoid_start = set("，。！？、；：”’》）】,.!?;:)]}")

        curr_w = 0
        split_idx = len(text)
        for i, char in enumerate(text):
            char_w = draw.textlength(char, font=font)
            if curr_w + char_w > target_w:
                if i < len(text) and text[i] in punctuation_avoid_start:
                    split_idx = i + 1
                else:
                    split_idx = i
                break
            curr_w += char_w

        if split_idx == 0 or split_idx == len(text):
            return [text]

        lines.append(text[:split_idx].rstrip())
        rest = text[split_idx:].lstrip()

        while rest:
            if draw.textlength(rest, font=font) <= max_width:
                lines.append(rest)
                break

            curr_w = 0
            sub_split = len(rest)
            for i, char in enumerate(rest):
                char_w = draw.textlength(char, font=font)
                if curr_w + char_w > max_width:
                    if i < len(rest) and rest[i] in punctuation_avoid_start:
                        sub_split = i + 1
                    else:
                        sub_split = max(1, i)
                    break
                curr_w += char_w

            lines.append(rest[:sub_split].rstrip())
            rest = rest[sub_split:].lstrip()

        return lines

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
