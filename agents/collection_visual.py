# 文件名: agents/collection_visual.py
import os
from PIL import Image, ImageDraw, ImageFont
import config

class CollectionVisualAgent:
    """
    🎨 合集视觉工厂 (CollectionVisualAgent)
    
    负责将收集到的剧照、台词、评分进行裁剪渲染并三图拼接。
    - 默认: 单图 16:9，三图拼接 16:27
    - 开关开启: 单图 9:4，三图拼接 3:4
    特色功能：
    1. 动态缩放标题，防溢出。
    2. 视觉平衡折行算法 (倒三角排版，Top-Heavy Ratio)。
    3. 精准的标点清洗与中文双引号包裹。
    """
    def __init__(self):
        # --- 沿用原版的排版常量设置 ---
        # --- A. 左侧排版设置 (独立控制) ---
        self.MARGIN_LEFT_TITLE = 0   # 标题左侧留白 (修正为80防贴边)
        self.MARGIN_LEFT_SCORE = 80   # 评分左侧留白

        # --- B. 垂直排版设置 ---
        self.MARGIN_TITLE_TOP = 40    # 标题顶部留白
        self.GAP_TITLE_SCORE = 20     # 评分与标题间距
        self.MARGIN_BOTTOM_BASE = 40  # 底部安全距离
        self.GAP_BETWEEN_TEXT = 20    # 金句与简介间距

        # --- C. 底部文字两侧留白 (控制文字换行宽度) ---
        # [修改] 解耦金句与简介的留白控制，分别控制以实现更灵活的排版
        self.MARGIN_SIDE_QUOTE = 60     # 金句两侧留白
        self.MARGIN_SIDE_SUMMARY = 60   # 简介两侧留白
        
        # --- D. 字体大小 ---
        self.SIZE_TITLE = 150
        self.SIZE_SCORE = 70
        self.SIZE_QUOTE = 60
        self.SIZE_SUMMARY = 40
        
        self.COLOR_GOLD = "#FFD700"
        self.COLOR_WHITE = "#FFFFFF"
        self.COLOR_SHADOW = "#000000"

        # [新增] 合集渲染比例开关：
        # False => 16:9 单图 + 16:27 拼接（保持现状）
        # True  => 9:4 单图 + 3:4 拼接（贴合小红书封面展示比例）
        self.use_9_4_render = bool(
            getattr(config.Strategy.Visual, "COLLECTION_USE_9_4_RENDER", False)
        )
        if self.use_9_4_render:
            # 2160x960 为精确 9:4；3 张拼接后 2160x2880 为精确 3:4
            self.render_width = 2160
            self.render_height = 960
        else:
            # 保持原有像素规格，避免旧工作流受影响
            self.render_width = 1920
            self.render_height = 1080

    def run(self, movies: list, folder_path: str) -> list:
        """
        执行视觉渲染与拼接逻辑。
        
        Args:
            movies (list): 完善了所有文案数据的电影列表。
            folder_path (str): 当前处理的合集母文件夹路径 (用于创建 output 归档)。
            
        Returns:
            list: 生成好的所有长图/横图的绝对路径列表。
        """
        render_mode = "9:4→3:4" if self.use_9_4_render else "16:9→16:27"
        print("\n🎨 [4/5 CollectionVisualAgent] 正在启动电影感排版引擎...")
        print(f"   🧭 渲染比例模式: {render_mode}")
        
        output_dir = os.path.join(folder_path, "output")
        os.makedirs(output_dir, exist_ok=True)
        
        rendered_canvases = []
        
        # 1. 逐个渲染单张海报
        for i, movie in enumerate(movies):
            print(f"   🖌️ 正在渲染排版: {movie['name']} ({i+1}/{len(movies)})")
            canvas = self._render_single_movie(movie)
            if canvas:
                rendered_canvases.append(canvas)
                
        if not rendered_canvases:
            print("   ❌ 所有图片渲染均失败。")
            return []
            
        final_images_paths = []
        
        # 2. 动态成组拼接 (3合1长图，余数保留横图)
        long_ratio_label = "3:4" if self.use_9_4_render else "16:27"
        print(f"\n   🧩 开始拼接 {long_ratio_label} 电影感长图...")
        for i in range(0, len(rendered_canvases), 3):
            group = rendered_canvases[i:i+3]
            group_index = (i // 3) + 1
            
            if len(group) == 3:
                # 按当前单图尺寸拼接 3 张，开关开启时可得到 3:4 长图
                long_img = Image.new(
                    "RGB",
                    (self.render_width, self.render_height * 3),
                    color="black",
                )
                long_img.paste(group[0], (0, 0))
                long_img.paste(group[1], (0, self.render_height))
                long_img.paste(group[2], (0, self.render_height * 2))
                
                save_path = os.path.join(output_dir, f"collection_poster_{group_index}.jpg")
                long_img.save(save_path, quality=95)
                final_images_paths.append(save_path)
                print(f"      ✅ 成功生成封面级长图: collection_poster_{group_index}.jpg")
            else:
                # 余数横图独立保存
                for j, single_img in enumerate(group):
                    save_path = os.path.join(output_dir, f"collection_single_{group_index}_{j+1}.jpg")
                    single_img.save(save_path, quality=95)
                    final_images_paths.append(save_path)
                    print(f"      ✅ 成功生成独立横版剧照: collection_single_{group_index}_{j+1}.jpg")
                    
        # 3. [新增] 追加单图逻辑 (防爆阀门与内容阀门)
        append_details = getattr(config.Strategy.Visual, 'APPEND_DETAIL_IMAGES', True)
        if append_details:
            detail_type = getattr(config.Strategy.Visual, 'DETAIL_IMAGE_TYPE', 'rendered')
            print(f"\n   📸 开始追加单部电影详情图 (模式: {detail_type})...")
            
            if detail_type == "original":
                # 零 I/O 极简优化：直接读取绝对路径，不产生新文件
                for i, movie in enumerate(movies):
                    final_images_paths.append(movie['path'])
                    print(f"      ✅ 成功追加原图: {os.path.basename(movie['path'])}")
            else:
                # 渲染图模式：逐张保存渲染画布
                for i, canvas in enumerate(rendered_canvases):
                    save_path = os.path.join(output_dir, f"collection_detail_{i+1}.jpg")
                    canvas.save(save_path, quality=95)
                    final_images_paths.append(save_path)
                    print(f"      ✅ 成功生成并追加独立排版图: collection_detail_{i+1}.jpg")
                    
        return final_images_paths

    def _render_single_movie(self, movie: dict) -> Image.Image | None:
        """渲染单张带字剧照（尺寸由开关决定：16:9 或 9:4）。"""
        try:
            # 1. 先按当前模式裁剪底图，再叠加文字，避免后裁剪截断文字
            with Image.open(movie['path']) as img:
                img = img.convert('RGB')
                canvas = self._center_crop_to_render_ratio(img)
                
            draw = ImageDraw.Draw(canvas)
            
            # 2. 挂载字体
            font_title = self._safe_load_font(config.FONT_TITLE_PATH, self.SIZE_TITLE)
            font_score = self._safe_load_font(config.FONT_SCORE_PATH, self.SIZE_SCORE)
            font_quote = self._safe_load_font(config.FONT_QUOTE_PATH, self.SIZE_QUOTE)
            font_summary = self._safe_load_font(config.FONT_SUMMARY_PATH, self.SIZE_SUMMARY)

            # --- 顶部区域渲染 (Title & Score) ---
            title_text = f"《{movie['name']}》"
            max_title_w = self.render_width - (self.MARGIN_LEFT_TITLE * 2)
            title_h = self._draw_title_auto_scale(draw, title_text, self.MARGIN_LEFT_TITLE, self.MARGIN_TITLE_TOP, max_title_w, config.FONT_TITLE_PATH, self.SIZE_TITLE, canvas)
            
            # 绘制评分 (跳过空值)
            score_text = ""
            if movie.get('douban'): score_text += f"豆瓣 {movie['douban']}  "
            if movie.get('imdb'): score_text += f"IMDb {movie['imdb']}"
            score_text = score_text.strip()
            
            if score_text:
                score_y = self.MARGIN_TITLE_TOP + title_h + self.GAP_TITLE_SCORE
                # 传入 canvas 以便 _draw_text_with_shadow 创建透明层，并严格传入 anchor="lt"
                self._draw_text_with_shadow(draw, self.MARGIN_LEFT_SCORE, score_y, score_text, font_score, self.COLOR_GOLD, 2, canvas, anchor="lt")

            # --- 底部区域渲染 (Quote & Summary) ---
            # 从下往上推算高度，确保绝对的安全距离
            center_x = self.render_width // 2
            bottom_limit = self.render_height - self.MARGIN_BOTTOM_BASE
            
            # 1. 清洗与绘制简介
            raw_summary = movie.get('summary', '')
            clean_summary = raw_summary.rstrip('。. ”"') # 仅去除尾部句号，保留中间标点
            # [修改] 传递专属于简介的留白参数
            sum_h = self._draw_bottom_stack(draw, clean_summary, center_x, bottom_limit, font_summary, self.COLOR_WHITE, canvas, self.MARGIN_SIDE_SUMMARY)
            
            # 2. 清洗、加双引号与绘制金句
            raw_quote = movie.get('quote', '')
            clean_quote = raw_quote.rstrip('。. ”"').strip()
            if clean_quote:
                clean_quote = f"“{clean_quote}”"  # 强制使用中文双引号包裹
                
            quote_limit = bottom_limit - sum_h - self.GAP_BETWEEN_TEXT
            # [修改] 传递专属于金句的留白参数
            self._draw_bottom_stack(draw, clean_quote, center_x, quote_limit, font_quote, self.COLOR_GOLD, canvas, self.MARGIN_SIDE_QUOTE)

            return canvas
            
        except Exception as e:
            print(f"      ❌ 渲染失败 {movie['name']}: {e}")
            return None

    def _draw_bottom_stack(self, draw: ImageDraw, text: str, center_x: int, bottom_y: int, font: ImageFont.FreeTypeFont, color: str, canvas: Image.Image, margin_side: int) -> int:
        """底部文字堆叠：倒三角视觉平衡折行，居中对齐，自下而上绘制。返回占据的总高度。"""
        if not text:
            return 0
            
        # [修改] 使用传入的 margin_side 动态计算当前文本块的最大宽度
        max_width = self.render_width - (margin_side * 2)
        lines = self._inverted_pyramid_wrap(text, font, draw, max_width)
        
        # 计算总高度
        line_heights = [draw.textbbox((0, 0), line, font=font)[3] - draw.textbbox((0, 0), line, font=font)[1] for line in lines]
        total_h = sum(line_heights) + (len(lines) - 1) * 15 # 15 为行距
        
        current_y = bottom_y - total_h
        
        for i, line in enumerate(lines):
            # 传入 4 像素描边、canvas 对象以及 anchor="ma" (Middle-Ascender 居中对齐)
            # 因为使用了 anchor="ma"，x 坐标直接传入 center_x 即可，Pillow 会自动居中
            self._draw_text_with_shadow(draw, center_x, current_y, line, font, color, 4, canvas, anchor="ma")
            current_y += line_heights[i] + 15
            
        return total_h

    def _inverted_pyramid_wrap(self, text: str, font: ImageFont.FreeTypeFont, draw: ImageDraw, max_width: int) -> list:
        """核心独家：倒三角视觉平衡算法 (Top-Heavy Ratio) + 标点避头机制"""
        total_w = draw.textlength(text, font=font)
        if total_w <= max_width:
            return [text]
            
        ratio = getattr(config.Strategy.Visual, 'TOP_HEAVY_RATIO', 0.6)
        target_w = min(total_w * ratio, max_width) # 第一行的理想宽度
        
        lines = []
        punctuation_avoid_start = set("，。！？、；：”’》）】")
        
        curr_w = 0
        split_idx = len(text)
        
        # 寻找第一行的最佳切分点
        for i, char in enumerate(text):
            char_w = draw.textlength(char, font=font)
            if curr_w + char_w > target_w:
                # 检查若在此切分，下一个字是否为标点（避免孤立标点出现在下一行行首）
                if i < len(text) and text[i] in punctuation_avoid_start:
                    split_idx = i + 1 # 把标点也拉进第一行
                else:
                    split_idx = i
                break
            curr_w += char_w
            
        if split_idx == 0 or split_idx == len(text):
            return [text]
            
        lines.append(text[:split_idx])
        rest = text[split_idx:]
        
        # 对剩下的文本做传统的贪心换行 (防溢出)
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
                
            lines.append(rest[:sub_split])
            rest = rest[sub_split:]
            
        return lines

    def _draw_title_auto_scale(self, draw: ImageDraw, text: str, x: int, y: int, max_w: int, font_path: str, start_size: int, canvas: Image.Image) -> int:
        """自动缩放算法：如果标题过长，循环减小字号直到能塞进一行。"""
        size = start_size
        font = self._safe_load_font(font_path, size)
        
        while draw.textlength(text, font=font) > max_w and size > 30:
            size -= 4
            font = self._safe_load_font(font_path, size)
            
        # 传入 0 像素描边和 canvas 对象，并严格传入 anchor="lt"
        self._draw_text_with_shadow(draw, x, y, text, font, self.COLOR_WHITE, 0, canvas, anchor="lt")
        
        # 严格获取纯文字占据的高度 (0,0)
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[3] - bbox[1]

    def _draw_text_with_shadow(self, draw: ImageDraw, x: int, y: int, text: str, font: ImageFont.FreeTypeFont, color: str, stroke: int, canvas: Image.Image, anchor: str = "lt"):
        """统一的带阴影与描边的文字渲染器 (全新透明图层叠加算法 + 绝对锚点控制)"""
        # 1. 建立等大的全透明"玻璃层" (RGBA)
        shadow_layer = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow_layer)
        
        # 2. 在透明层上画出 160 透明度的黑色阴影 (固定偏移 x+4, y+4)，并带上 anchor
        shadow_draw.text((x + 4, y + 4), text, font=font, fill=(0, 0, 0, 160), anchor=anchor)
        
        # 3. 将画好阴影的玻璃层，极其平滑地压合到底图 (canvas) 上
        # (因为底图原来是 RGB，压合后需保持原来的画布引用)
        canvas.paste(Image.alpha_composite(canvas.convert('RGBA'), shadow_layer), (0, 0))
        
        # 4. 在底图上直接画带有差异化描边的主体文字，并带上 anchor
        if stroke > 0:
            draw.text((x, y), text, font=font, fill=color, stroke_width=stroke, stroke_fill=self.COLOR_SHADOW, anchor=anchor)
        else:
            draw.text((x, y), text, font=font, fill=color, anchor=anchor)

    def _center_crop_to_render_ratio(self, img: Image.Image) -> Image.Image:
        """按当前配置居中裁剪并缩放到底图尺寸（16:9 或 9:4）。"""
        w, h = img.size
        target_ratio = self.render_width / self.render_height
        current_ratio = w / h
        
        if abs(current_ratio - target_ratio) < 0.01:
            return img.resize((self.render_width, self.render_height), Image.Resampling.LANCZOS)
            
        if current_ratio > target_ratio:
            new_w = int(h * target_ratio)
            left = (w - new_w) // 2
            img = img.crop((left, 0, left + new_w, h))
        else:
            new_h = int(w / target_ratio)
            top = (h - new_h) // 2
            img = img.crop((0, top, w, top + new_h))
            
        return img.resize((self.render_width, self.render_height), Image.Resampling.LANCZOS)

    def _safe_load_font(self, path: str, size: int) -> ImageFont.FreeTypeFont:
        """安全加载字体，失败则兜底返回系统默认字体"""
        try:
            return ImageFont.truetype(path, size)
        except Exception as e:
            print(f"      ⚠️ 字体加载失败 ({path}): {e}，将使用系统默认字体兜底。")
            return ImageFont.load_default()
