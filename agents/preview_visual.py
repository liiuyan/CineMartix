import os
from PIL import Image, ImageDraw, ImageFont

import config


class PreviewVisualAgent:
    """
    🎨 新片速递视觉 Agent

    sub_mode=landscape:
    1) 横图渲染 16:9（不足则居中裁剪）
    2) 每 3 张拼接 16:27，余数单图独立输出
    3) 可配置追加渲染单图与原图

    sub_mode=poster:
    - 不做渲染，按序直发原图
    """

    def __init__(self):
        # 子模式由 config 决定，保证一次运行只走一条视觉链路。
        # - landscape: 渲染+拼接
        # - poster: 原图直发
        self.sub_mode = getattr(config.Strategy.Preview, "SUB_MODE", "landscape")

        # 发布图扩展策略（仅 landscape 生效）:
        # append_rendered_details=True  => 在末尾追加渲染后的单图(16:9)
        # append_original_images=True   => 在末尾追加输入原图
        self.append_rendered_details = bool(
            getattr(config.Strategy.Preview, "APPEND_RENDERED_DETAILS", True)
        )
        self.append_original_images = bool(
            getattr(config.Strategy.Preview, "APPEND_ORIGINAL_IMAGES", True)
        )

        # 统一维护“海报文字层”样式，避免在渲染流程里散落魔法数字。
        # 坐标体系:
        # - 基准画布为 1920x1080
        # - x/y 使用左上角坐标
        # 字段说明:
        # - size: 字号(px)
        # - font_path: 字体路径
        # - stroke_width/stroke_color: 描边参数
        # - shadow_offset/shadow_alpha: 阴影偏移与透明度
        self.layout_config = {
            # 底部三段文字（英文原名+日期/中文名/噱头）的纵向间距控制
            # [样式迁移] 对齐你提供的新渲染方案：左下角自下而上堆叠。
            "bottom_layout": {
                "margin_bottom": 20,  # 最底部安全边距：噱头文本距离画布底部的间隔
                "gap_cn_sub": 20,  # 中文片名 与 噱头 之间的垂直间距
                "gap_en_cn": 10,  # 英文原名 与 中文片名 之间的垂直间距
            },
            # 英文原名样式（最上层）
            "title_en": {
                "x": 80,  # 英文原名起始 X 坐标
                "size": 75,  # 英文原名字号
                "font_path": config.FONT_QUOTE_PATH,  # 英文原名字体
                "text_color": "#FFFFFF",  # 主文字颜色
                "stroke_width": 1,  # 文字描边宽度（提升暗背景可读性）
                "stroke_color": "#000000",  # 描边颜色
                "shadow_offset": (3, 3),  # 阴影偏移 (x, y)
                "shadow_alpha": 180,  # 阴影透明度（0-255）
            },
            # 中文片名样式（中间层，视觉权重最高）
            "title_cn": {
                "x": 0,  # 中文片名起始 X 坐标
                "size": 110,  # 中文片名字号（主视觉）
                "font_path": config.FONT_TITLE_PATH,  # 中文片名字体
                "text_color": "#FFFFFF",  # 主文字颜色
                "stroke_width": 3,  # 文字描边宽度（主标题更粗）
                "stroke_color": "#000000",  # 描边颜色
                "shadow_offset": (6, 6),  # 阴影偏移 (x, y)
                "shadow_alpha": 220,  # 阴影透明度（0-255）
            },
            # 噱头样式（底部第一层）
            "subtitle": {
                "x": 80,  # 噱头起始 X 坐标
                "size": 80,  # 噱头字号
                "font_path": config.FONT_SCORE_PATH,  # 噱头字体
                "text_color": "#FFFFFF",  # 主文字颜色
                "stroke_width": 2,  # 文字描边宽度
                "stroke_color": "#000000",  # 描边颜色
                "shadow_offset": (4, 4),  # 阴影偏移 (x, y)
                "shadow_alpha": 200,  # 阴影透明度（0-255）
            },
        }

    def run(self, movies: list, folder_path: str) -> list:
        """
        视觉主入口:
        - poster: 原图直发
        - landscape: 渲染 -> 3合1拼接 -> (可选)追加渲染单图 -> (可选)追加原图

        返回值即最终发布图片顺序列表。
        """
        print("\n🎨 [4/5 PreviewVisualAgent] 正在处理新片速递图片...")

        # poster 子模式：完全不做图像加工，按序发布输入原图。
        if self.sub_mode == "poster":
            print("   🖼️ 子模式 poster：按顺序直发原图，不做渲染。")
            return [m["path"] for m in movies]

        # landscape 子模式：需要生成 output 目录保存中间产物与拼接图。
        output_dir = os.path.join(folder_path, "output")
        os.makedirs(output_dir, exist_ok=True)

        rendered_canvases = []
        rendered_paths = []
        for i, movie in enumerate(movies):
            print(f"   🖌️ 渲染: 《{movie['name']}》 ({i+1}/{len(movies)})")
            canvas = self._render_single_image(movie)
            if canvas is None:
                # 视觉失败属于硬错误，直接返回空列表触发上游终止。
                print(f"   ⛔ [熔断] 渲染失败: 《{movie['name']}》")
                return []
            rendered_canvases.append(canvas)

            # 渲染后的 16:9 单图先落盘，后续是否发布由开关决定。
            detail_path = os.path.join(output_dir, f"preview_detail_{i+1}.jpg")
            canvas.save(detail_path, quality=95)
            rendered_paths.append(detail_path)

        final_paths = []

        # 3合1 拼接，余数单图独立输出（与 collection 行为保持一致）。
        group_index = 0
        for i in range(0, len(rendered_canvases), 3):
            group_index += 1
            group = rendered_canvases[i : i + 3]
            if len(group) == 3:
                # 1920x3240 = 16:27，适配你当前长图方案
                long_img = Image.new("RGB", (1920, 3240), color="black")
                long_img.paste(group[0], (0, 0))
                long_img.paste(group[1], (0, 1080))
                long_img.paste(group[2], (0, 2160))
                path = os.path.join(output_dir, f"preview_poster_{group_index}.jpg")
                long_img.save(path, quality=95)
                final_paths.append(path)
                print(f"      ✅ 长图: preview_poster_{group_index}.jpg")
            else:
                # 不满 3 张时，按单图输出，不强行拉伸或补空白。
                for j, single in enumerate(group):
                    path = os.path.join(
                        output_dir, f"preview_single_{group_index}_{j+1}.jpg"
                    )
                    single.save(path, quality=95)
                    final_paths.append(path)
                    print(f"      ✅ 余数单图: preview_single_{group_index}_{j+1}.jpg")

        # 追加渲染单图：用于“长图 + 单图”混发策略。
        if self.append_rendered_details:
            final_paths.extend(rendered_paths)
            print(f"   ➕ 已追加渲染单图: {len(rendered_paths)} 张")

        # 追加原图：保留你原始素材的发布能力。
        if self.append_original_images:
            originals = [m["path"] for m in movies]
            final_paths.extend(originals)
            print(f"   ➕ 已追加原图: {len(originals)} 张")

        return final_paths

    def _render_single_image(self, movie: dict) -> Image.Image | None:
        """
        渲染单张 16:9 图：
        - 底部: 英文原名+日期 / 中文名 / 噱头（自下而上排版）
        """
        try:
            with Image.open(movie["path"]) as img:
                # 无论输入比例如何，统一裁剪到 16:9。
                img = img.convert("RGB")
                canvas = self._center_crop_to_16_9(img)

            draw = ImageDraw.Draw(canvas)

            # [样式迁移] 文本动态排版（从下往上）：
            # 噱头(底) -> 中文名(中) -> 英文名+日期(上)。
            bl = self.layout_config["bottom_layout"]
            text_en = str(movie.get("poster_title_en") or "").strip()
            text_cn = str(movie.get("poster_title_cn") or "").strip()
            text_hook = str(movie.get("poster_hook") or "").strip()
            date_text = str(movie.get("poster_date") or "").strip()

            # [关键修复] 解决“原名为空但日期存在”时出现“|2026.xx.xx”的问题。
            # 规则：
            # 1) 原名+日期都有 -> "原名 | 日期"
            # 2) 仅原名 -> "原名"
            # 3) 仅日期 -> "日期"
            merged_title_en = self._merge_title_en_and_date(text_en, date_text)

            # 分别加载三类文本字体，便于独立调样式。
            cfg_sub = self.layout_config["subtitle"]
            cfg_cn = self.layout_config["title_cn"]
            cfg_en = self.layout_config["title_en"]
            font_sub = self._safe_load_font(cfg_sub["font_path"], cfg_sub["size"])
            font_cn = self._safe_load_font(cfg_cn["font_path"], cfg_cn["size"])
            font_en = self._safe_load_font(cfg_en["font_path"], cfg_en["size"])

            # [样式迁移] 与你新代码一致：先算底部噱头，再向上推中文，再向上推英文+日期。
            y_sub = y_cn = y_en = None

            if text_hook:
                h_sub = self._text_height(draw, text_hook, font_sub)
                y_sub = 1080 - bl["margin_bottom"] - h_sub

            if text_cn:
                h_cn = self._text_height(draw, text_cn, font_cn)
                if y_sub is not None:
                    y_cn = y_sub - bl["gap_cn_sub"] - h_cn
                else:
                    # 噱头缺失时，中文名直接落到最底部安全线，避免整块上浮过高。
                    y_cn = 1080 - bl["margin_bottom"] - h_cn

            if merged_title_en:
                h_en = self._text_height(draw, merged_title_en, font_en)
                if y_cn is not None:
                    y_en = y_cn - bl["gap_en_cn"] - h_en
                elif y_sub is not None:
                    y_en = y_sub - bl["gap_en_cn"] - h_en
                else:
                    # 仅英文/日期时，保持贴近底部显示，避免空画面。
                    y_en = 1080 - bl["margin_bottom"] - h_en

            if text_hook and y_sub is not None:
                self._render_text_element(canvas, draw, text_hook, cfg_sub, y_sub)
            if text_cn and y_cn is not None:
                self._render_text_element(canvas, draw, text_cn, cfg_cn, y_cn)
            if merged_title_en and y_en is not None:
                self._render_text_element(canvas, draw, merged_title_en, cfg_en, y_en)

            return canvas
        except Exception as e:
            print(f"      ❌ 渲染异常: {e}")
            return None

    def _render_text_element(
        self, canvas: Image.Image, draw: ImageDraw, text: str, cfg: dict, y: float
    ):
        """统一文字渲染入口，内部复用带阴影描边的绘制器。"""
        font = self._safe_load_font(cfg["font_path"], cfg["size"])
        self._draw_text_with_shadow(
            draw=draw,
            canvas=canvas,
            x=cfg["x"],
            y=y,
            text=text,
            font=font,
            color=cfg["text_color"],
            stroke=cfg["stroke_width"],
            stroke_color=cfg["stroke_color"],
            shadow_offset=cfg["shadow_offset"],
            shadow_alpha=cfg["shadow_alpha"],
        )

    def _draw_text_with_shadow(
        self,
        draw: ImageDraw,
        canvas: Image.Image,
        x: int,
        y: float,
        text: str,
        font: ImageFont.FreeTypeFont,
        color: str,
        stroke: int,
        stroke_color: str,
        shadow_offset: tuple,
        shadow_alpha: int,
    ):
        """
        文本绘制核心:
        1) 在透明层上画阴影
        2) 与底图 alpha 合成
        3) 在底图上画主体文字(可选描边)
        """
        shadow_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow_layer)

        sx, sy = shadow_offset
        shadow_draw.text(
            (x + sx, y + sy), text, font=font, fill=(0, 0, 0, shadow_alpha), anchor="lt"
        )
        canvas.paste(Image.alpha_composite(canvas.convert("RGBA"), shadow_layer), (0, 0))

        if stroke > 0:
            draw.text(
                (x, y),
                text,
                font=font,
                fill=color,
                stroke_width=stroke,
                stroke_fill=stroke_color,
                anchor="lt",
            )
        else:
            draw.text((x, y), text, font=font, fill=color, anchor="lt")

    def _center_crop_to_16_9(self, img: Image.Image) -> Image.Image:
        """将任意比例图片居中裁剪并缩放为 1920x1080。"""
        w, h = img.size
        target_ratio = 16 / 9
        current_ratio = w / h

        if abs(current_ratio - target_ratio) < 0.01:
            return img.resize((1920, 1080), Image.Resampling.LANCZOS)

        if current_ratio > target_ratio:
            new_w = int(h * target_ratio)
            left = (w - new_w) // 2
            img = img.crop((left, 0, left + new_w, h))
        else:
            new_h = int(w / target_ratio)
            top = (h - new_h) // 2
            img = img.crop((0, top, w, top + new_h))

        return img.resize((1920, 1080), Image.Resampling.LANCZOS)

    def _text_height(self, draw: ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> int:
        """获取单行文本像素高度，用于自下而上排版计算。"""
        bbox = draw.textbbox((0, 0), text, font=font, anchor="lt")
        return bbox[3] - bbox[1]

    def _merge_title_en_and_date(self, title_en: str, date_text: str) -> str:
        """
        合并英文原名与日期，避免出现前导分隔符“|2026.xx.xx”。

        规则:
        - title_en + date_text -> "title_en | date_text"
        - 仅 title_en -> "title_en"
        - 仅 date_text -> "date_text"
        """
        clean_title = str(title_en or "").strip().rstrip("|").strip()
        clean_date = str(date_text or "").strip().lstrip("|").strip()

        if clean_title and clean_date:
            return f"{clean_title} | {clean_date}"
        return clean_title or clean_date

    def _safe_load_font(self, path: str, size: int) -> ImageFont.FreeTypeFont:
        """字体兜底：缺字库或路径异常时返回默认字体，避免渲染崩溃。"""
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            return ImageFont.load_default()
