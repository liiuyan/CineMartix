import os
from PIL import Image, ImageDraw, ImageFont

import config
from services.cover_renderer import CoverRenderer


class PreviewVisualAgent:
    """
    🎨 新片速递视觉 Agent

    sub_mode=landscape:
    1) 横图渲染（默认 16:9；开关可切 9:4）
    2) 每 3 张拼接（默认 16:27；开关可切 3:4）
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
        # append_rendered_details=True  => 在末尾追加渲染后的单图(比例受开关控制)
        # append_original_images=True   => 在末尾追加输入原图
        self.append_rendered_details = bool(
            getattr(config.Strategy.Preview, "APPEND_RENDERED_DETAILS", True)
        )
        self.append_original_images = bool(
            getattr(config.Strategy.Preview, "APPEND_ORIGINAL_IMAGES", True)
        )

        # [新增] preview landscape 渲染比例开关：
        # False => 16:9 单图 + 16:27 拼接（保持现状）
        # True  => 9:4 单图 + 3:4 拼接（仅 landscape 生效）
        self.landscape_use_9_4_render = bool(
            getattr(config.Strategy.Preview, "LANDSCAPE_USE_9_4_RENDER", False)
        )
        if self.landscape_use_9_4_render:
            # 2160x960 为精确 9:4；三图拼接后 2160x2880 为精确 3:4
            self.render_width = 2160
            self.render_height = 960
        else:
            # 保持旧规格，避免已有任务视觉结果变化
            self.render_width = 1920
            self.render_height = 1080
        # preview 封面可单独控制是否绘制电影名水印，不影响封面主标题。
        self.cover_show_watermark = bool(
            getattr(config.Strategy.Preview, "COVER_SHOW_WATERMARK", True)
        )
        # preview 封面英文原名单独受配置控制；关闭时仅保留中文水印。
        self.cover_show_english_names = bool(
            getattr(config.Strategy.Preview, "COVER_SHOW_ENGLISH_NAMES", True)
        )

        # 统一维护“海报文字层”样式，避免在渲染流程里散落魔法数字。
        # 坐标体系:
        # - 基准画布为 render_width x render_height（默认 1920x1080）
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
                "right_margin": 60,  # 右侧安全边距：文本防溢出时的最大可用宽度预留
                "gap_en_sub": 20,  # 英文原名+日期 与 噱头 之间的垂直间距
                "gap_en_cn": 20,  # 英文原名 与 中文片名 之间的垂直间距
            },
            # 英文原名样式（中间层）
            "title_en": {
                "x": 60,  # 英文原名起始 X 坐标
                "size": 80,  # 英文原名字号
                "min_size": 20,  # 英文原名自适应缩放最小字号
                "font_path": config.FONT_QUOTE_PATH,  # 英文原名字体
                "text_color": "#FFFFFF",  # 主文字颜色
                "stroke_width": 1,  # 文字描边宽度（提升暗背景可读性）
                "stroke_color": "#000000",  # 描边颜色
                "shadow_offset": (3, 3),  # 阴影偏移 (x, y)
                "shadow_alpha": 180,  # 阴影透明度（0-255）
            },
            # 中文片名样式（最上层，视觉权重最高）
            "title_cn": {
                "x": 0,  # 中文片名起始 X 坐标 
                "size": 110,  # 中文片名字号（主视觉）
                "min_size": 30,  # 中文主标题自适应缩放最小字号
                "font_path": config.FONT_TITLE_PATH,  # 中文片名字体
                "text_color": "#FFFFFF",  # 主文字颜色
                "stroke_width": 3,  # 文字描边宽度（主标题更粗）
                "stroke_color": "#000000",  # 描边颜色
                "shadow_offset": (6, 6),  # 阴影偏移 (x, y)
                "shadow_alpha": 220,  # 阴影透明度（0-255）
            },
            # 噱头样式（底部第一层）
            "subtitle": {
                "x": 60,  # 噱头起始 X 坐标
                "size": 80,  # 噱头字号
                "min_size": 22,  # 噱头自适应缩放最小字号
                "font_path": config.FONT_SCORE_PATH,  # 噱头字体
                "text_color": "#FFFFFF",  # 主文字颜色
                "stroke_width": 2,  # 文字描边宽度
                "stroke_color": "#000000",  # 描边颜色
                "shadow_offset": (4, 4),  # 阴影偏移 (x, y)
                "shadow_alpha": 200,  # 阴影透明度（0-255）
            },
        }
        # 封面渲染能力下沉到 services，便于 preview/collection 复用。
        self.cover_renderer = CoverRenderer()

    def run(self, movies: list, folder_path: str, cover_data: dict | None = None) -> list:
        """
        视觉主入口:
        - poster: 原图直发
        - landscape: 渲染 -> 3合1拼接 -> (可选)追加渲染单图 -> (可选)追加原图
        - 可选封面: 若检测到 `|0/｜0` 封面图，先渲染并插入发布序列首位

        返回值即最终发布图片顺序列表。
        """
        print("\n🎨 [4/5 PreviewVisualAgent] 正在处理新片速递图片...")

        output_dir = os.path.join(folder_path, "output")
        cover_path = None
        if cover_data:
            os.makedirs(output_dir, exist_ok=True)
            # 封面渲染失败视为硬错误：用户显式提供了封面素材，必须保证可发布。
            cover_path = self.cover_renderer.render(
                cover_data,
                movies,
                output_dir,
                cover_mode="preview",
                show_english_names=self.cover_show_english_names,
                show_watermark=self.cover_show_watermark,
            )
            if not cover_path:
                print("   ⛔ [熔断] 封面图渲染失败。")
                return []

        # poster 子模式：完全不做图像加工，按序发布输入原图。
        if self.sub_mode == "poster":
            print("   🖼️ 子模式 poster：按顺序直发原图，不做渲染。")
            final_paths = [m["path"] for m in movies]
            if cover_path:
                # 需求约束：封面图永远是第 1 张。
                final_paths.insert(0, cover_path)
            return final_paths

        # landscape 子模式：需要生成 output 目录保存中间产物与拼接图。
        render_mode = "9:4→3:4" if self.landscape_use_9_4_render else "16:9→16:27"
        print(f"   🧭 landscape 渲染比例模式: {render_mode}")
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

            # 渲染后的单图先落盘（比例由开关决定），后续是否发布由开关决定。
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
                # 按当前单图尺寸拼接 3 张；开关开启时得到 3:4 长图
                long_img = Image.new(
                    "RGB",
                    (self.render_width, self.render_height * 3),
                    color="black",
                )
                long_img.paste(group[0], (0, 0))
                long_img.paste(group[1], (0, self.render_height))
                long_img.paste(group[2], (0, self.render_height * 2))
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

        if cover_path:
            # 需求约束：无论 landscape 如何拼接，最终封面都插入发布序列首位。
            final_paths.insert(0, cover_path)
            print("   ✅ 已将封面图插入发布序列首位。")

        return final_paths

    def _render_single_image(self, movie: dict) -> Image.Image | None:
        """
        渲染单张图（默认 16:9；开关开启时 9:4）：
        - 底部自下而上: 噱头 / 英文原名+日期 / 中文名
        """
        try:
            with Image.open(movie["path"]) as img:
                # 先按目标比例裁剪，再叠字，避免后裁剪截断文字。
                img = img.convert("RGB")
                canvas = self._center_crop_to_render_ratio(img)

            draw = ImageDraw.Draw(canvas)

            # [样式迁移] 文本动态排版（从下往上）：
            # 噱头(底) -> 英文名+日期(中) -> 中文名(上)。
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
            right_margin = int(bl.get("right_margin", 60))
            gap_en_sub = int(bl.get("gap_en_sub", bl.get("gap_cn_sub", 20)))

            # [样式迁移] 与你新代码一致：先算底部噱头，再向上推英文+日期，再向上推中文。
            y_sub = y_cn = y_en = None
            cfg_sub_dynamic = cfg_sub
            cfg_en_dynamic = cfg_en
            cfg_cn_dynamic = cfg_cn

            if text_hook:
                cfg_sub_dynamic, h_sub = self._fit_text_size_within_width(
                    draw, text_hook, cfg_sub, right_margin, "噱头"
                )
                y_sub = self.render_height - bl["margin_bottom"] - h_sub

            if merged_title_en:
                cfg_en_dynamic, h_en = self._fit_text_size_within_width(
                    draw, merged_title_en, cfg_en, right_margin, "英文名+日期"
                )
                if y_sub is not None:
                    y_en = y_sub - gap_en_sub - h_en
                else:
                    # 仅英文/日期时，保持贴近底部显示，避免空画面。
                    y_en = self.render_height - bl["margin_bottom"] - h_en

            if text_cn:
                cfg_cn_dynamic, h_cn = self._fit_text_size_within_width(
                    draw, text_cn, cfg_cn, right_margin, "中文名"
                )
                if y_en is not None:
                    y_cn = y_en - bl["gap_en_cn"] - h_cn
                elif y_sub is not None:
                    y_cn = y_sub - bl["gap_en_cn"] - h_cn
                else:
                    # 仅中文名时，落到最底部安全线，避免空画面。
                    y_cn = self.render_height - bl["margin_bottom"] - h_cn

            if text_hook and y_sub is not None:
                self._render_text_element(canvas, draw, text_hook, cfg_sub_dynamic, y_sub)
            if merged_title_en and y_en is not None:
                self._render_text_element(canvas, draw, merged_title_en, cfg_en_dynamic, y_en)
            if text_cn and y_cn is not None:
                self._render_text_element(canvas, draw, text_cn, cfg_cn_dynamic, y_cn)

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

    def _center_crop_to_render_ratio(self, img: Image.Image) -> Image.Image:
        """按当前模式把输入图裁剪并缩放到目标尺寸（16:9 或 9:4）。"""
        w, h = img.size
        target_ratio = self.render_width / self.render_height
        current_ratio = w / h

        if abs(current_ratio - target_ratio) < 0.01:
            return img.resize(
                (self.render_width, self.render_height), Image.Resampling.LANCZOS
            )

        if current_ratio > target_ratio:
            new_w = int(h * target_ratio)
            left = (w - new_w) // 2
            img = img.crop((left, 0, left + new_w, h))
        else:
            new_h = int(w / target_ratio)
            top = (h - new_h) // 2
            img = img.crop((0, top, w, top + new_h))

        return img.resize((self.render_width, self.render_height), Image.Resampling.LANCZOS)

    def _text_height(self, draw: ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> int:
        """获取单行文本像素高度，用于自下而上排版计算。"""
        bbox = draw.textbbox((0, 0), text, font=font, anchor="lt")
        return bbox[3] - bbox[1]

    def _fit_text_size_within_width(
        self,
        draw: ImageDraw,
        text: str,
        cfg: dict,
        right_margin: int,
        label: str,
    ) -> tuple[dict, int]:
        """
        单行文本自适应缩放：
        - 按右侧安全边距计算最大可用宽度
        - 超宽时递减字号
        - 若降到最小字号仍超宽则报错熔断
        """
        text_val = str(text or "").strip()
        if not text_val:
            return cfg, 0

        dynamic_cfg = cfg.copy()
        x = int(dynamic_cfg.get("x", 0))
        max_width = self.render_width - x - int(right_margin)
        if max_width <= 0:
            raise ValueError(f"{label} 可用宽度非法: max_width={max_width}")

        current_size = int(dynamic_cfg.get("size", 20))
        min_size = int(dynamic_cfg.get("min_size", 12))
        if min_size > current_size:
            min_size = current_size

        while True:
            font = self._safe_load_font(dynamic_cfg["font_path"], current_size)
            bbox = draw.textbbox((0, 0), text_val, font=font, anchor="lt")
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]

            if text_width <= max_width:
                dynamic_cfg["size"] = current_size
                return dynamic_cfg, text_height

            if current_size <= min_size:
                raise ValueError(
                    f"{label} 超出安全宽度: width={text_width}, max={max_width}, min_size={min_size}, text={text_val}"
                )

            current_size -= 2

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
