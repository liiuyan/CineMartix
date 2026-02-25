# 文件名: agents/collection_writer.py
import json
import random # [新增] 用于随机选取 emoji
import config
from utils import LLMBrain, calculate_progress, clean_tag  # [重构 板块2+7] 引入公共进度条 + 标签清洗器

# ==============================================================================
# 🖋️ 专栏主笔美学协议 (Magazine Columnist Aesthetics Protocol v1.0)
# ==============================================================================
MAGAZINE_AESTHETICS_PROTOCOL = """
【文风红线与质感要求】
1. 🎭 身份定位：你是一个冷静、客观、专业的电影杂志专栏主笔（类似于《看电影》或《帝国》杂志的资深编辑）。
2. 🚫 绝对禁语：严禁使用任何小红书营销号词汇（如：绝绝子、yyds、暴风哭泣、太好哭了、强推、按头安利、宝藏电影）。
3. 👁️ 旁观者视角：请使用克制、陈述性的语调。不要用“带你走进”、“让你感受”这种推销口吻，而是用“记录”、“审视”、“呈现”等旁观者视角的词汇。
4. 🇨🇳 纯中文排版：所有的输出内容（包括电影台词和简介），必须使用极其优美、信达雅的中文。即使是外语电影，也绝对不允许输出英文原句，必须提供高质量的中文翻译版。
"""

# [新增] 随机 Emoji 池 (用于合集片单序号前)
EMOJI_POOL = ['🎬', '🍿', '🎞️', '📽️', '🎫', '🎥', '📼', '📺', '💿', '📹']

class CollectionWriterAgent:
    """
    ✍️ 合集文案 Agent (CollectionWriterAgent)
    
    负责批量生成合集所需的所有文案：
    1. 为每部电影提取 1 句经典台词 + 1 句短评简介。
    2. 根据合集的“探讨主题”，撰写一篇极具高级感和深度的杂志专栏式正文。
    """
    def __init__(self):
        self.brain = LLMBrain()

    def run(self, theme: str, title: str, movies: list) -> dict | None:
        """
        执行合集文案生成逻辑。
        
        Args:
            theme (str): 探讨主题 (例如 "悬疑大师")
            title (str): 笔记标题 (例如 "9部必看神作")
            movies (list): 包含已排序、已查好分数的电影列表
        
        Returns:
            dict | None: 包含 { "content": 正文, "movies": [完善了文案的电影列表] }
        """
        print(f"\n✍️ [3/5 CollectionWriterAgent] 正在呼叫 DeepSeek 批量撰写文案...")
        print(f"   📝 探讨主题: 【{theme}】 | 涉及电影数: {len(movies)} 部")
        divergent_min_len = int(getattr(config.Strategy.Writer, 'COLLECTION_DIVERGENT_MIN_LEN', 250))
        divergent_max_len = int(getattr(config.Strategy.Writer, 'COLLECTION_DIVERGENT_MAX_LEN', 600))
        if divergent_min_len > divergent_max_len:
            # 防呆：配置写反时自动回退默认值，避免流程卡死
            divergent_min_len, divergent_max_len = 250, 600
            print("   ⚠️ [Collection] 发散字数配置异常，已回退默认区间 250-600。")
        
        # [修改] 提取电影列表（不带分数），发送给 AI 进行内容拆解
        movie_list_parts = []
        for i, m in enumerate(movies):
            movie_list_parts.append(f"{i+1}. {m['name']}")
            
        movie_list_str = "\n".join(movie_list_parts)
        
        # [原因: 模式化 Prompt] 不同正文模式使用独立提示词，保证输出结构与语气贴合模式目标
        body_mode = self._get_collection_body_mode()
        print(f"   🧩 [Collection] 正文模式: {body_mode}")
        prompt = self._build_prompt_by_mode(theme, title, movies, movie_list_str, body_mode)
        
        system_prompt = "你是一个冷静专业的电影杂志主笔。你只输出合法的JSON对象。"
        
        max_retries = 3
        data = None
        
        for attempt in range(max_retries):
            if attempt > 0:
                print(f"   🔄 正在重新生成文案 (尝试 {attempt + 1}/{max_retries})...")
            
            response = self.brain.think(prompt, system_prompt=system_prompt)
            
            if not response:
                print("   ⚠️ AI 未返回任何文案内容。")
                continue
                
            try:
                # 清洗可能存在的 markdown 代码块
                clean_json = response.replace("```json", "").replace("```", "").strip()
                data = json.loads(clean_json)
                
                # 🚨 mode_one 发散介绍字数熔断检查
                divergent_text = str(data.get('divergent_text', '')).strip()
                divergent_len = len(divergent_text)
                if body_mode == "mode_one":
                    if divergent_len < divergent_min_len or divergent_len > divergent_max_len:
                        if divergent_len < divergent_min_len:
                            reason = "偏短"
                        else:
                            reason = "超限"
                        print(
                            f"   ⚠️ [熔断] 发散介绍字数{reason} "
                            f"({divergent_len} 字，要求 {divergent_min_len}-{divergent_max_len} 字)，打回重写！"
                        )
                        data = None  # 重置 data 以触发下一轮
                        continue

                # [原因: mode_three 专属约束] mode_three 的 intro 仅做上限校验，避免唯一正文段过长
                intro_text = str(data.get('intro', '')).strip()
                if body_mode == "mode_three" and len(intro_text) > 200:
                    print(f"   ⚠️ [熔断] mode_three intro 超限 ({len(intro_text)} 字，限制 200 字)，打回重写！")
                    data = None
                    continue

                if body_mode == "mode_one":
                    print(
                        f"   ✅ 发散介绍字数合规 "
                        f"({divergent_len}/{divergent_min_len}-{divergent_max_len} 字)"
                    )
                if body_mode == "mode_three":
                    print(f"   ✅ mode_three intro 长度合规 ({len(intro_text)}/200 字)")
                break # 成功则跳出循环
                    
            except Exception as e:
                print(f"   ❌ 文案 JSON 解析失败: {e}")
                print(f"   [Debug API返回的原始内容]:\n{response[:500]}...") # 打印前500字帮助排查
                data = None
        
        if not data:
            print("   ❌ 多次尝试生成或解析文案失败，合集处理中止。")
            return None
            
        # --- 组装正文 (在 Python 侧精准控制) ---
        # [重构 板块2] 调用公共进度条计算器 (逻辑已统一至 utils.calculate_progress)
        movie_names_for_progress = [m['name'] for m in movies]
        progress_str = calculate_progress(movie_names_for_progress)

        # 1. 第一部分：本期片单 (保持原有随机 Emoji 与配置开关)
        list_emoji = random.choice(EMOJI_POOL)
        part_list_lines = [f"{list_emoji}本期片单："]
        
        for i, m in enumerate(movies):
            line = f"{i+1}️⃣{m['name']}"
            extras = []
            
            # [新增] 优先判断年份开关，确保年份显示在第一位 (例如: 1997 | 豆瓣 9.2)
            if getattr(config.Strategy.Writer, 'SHOW_YEAR', False) and m.get('year'):
                extras.append(m['year'])
            if getattr(config.Strategy.Writer, 'SHOW_DOUBAN', False) and m.get('douban') and m.get('douban') != 'N/A':
                extras.append(f"豆瓣 {m['douban']}")
            if getattr(config.Strategy.Writer, 'SHOW_IMDB', False) and m.get('imdb') and m.get('imdb') != 'N/A':
                extras.append(f"IMDb {m['imdb']}")
            # [本次新增] 烂番茄分数放在 IMDb 与 类型之间，受 config 开关控制
            if getattr(config.Strategy.Writer, 'SHOW_ROTTEN_TOMATOES', False) and m.get('rotten_tomatoes') and m.get('rotten_tomatoes') != 'N/A':
                extras.append(f"烂番茄 {m['rotten_tomatoes']}")
            if getattr(config.Strategy.Writer, 'SHOW_GENRE', False) and m.get('genres') and m.get('genres') != '未知类型':
                extras.append(m['genres'])
            if getattr(config.Strategy.Writer, 'SHOW_REGION', False) and m.get('region') and m.get('region') != '未知地区':
                extras.append(m['region'])
                
            if extras:
                line += f" ({' | '.join(extras)})"
            part_list_lines.append(line)
            
        part_list = "\n".join(part_list_lines)
        
        # --- 核心机制：安全对齐装配 ---
        # 为了防止 AI 的幻觉（漏写某部电影，或改了电影名字），
        # 我们以原来真实的 movies 列表为主轴，去 data['movies_content'] 里捞数据。
        ai_movie_contents = {item['name']: item for item in data.get('movies_content', [])}
        
        # [新增] 提取 AI 返回的电影名，并按长度从大到小排序，用于模糊兜底匹配
        sorted_ai_names = sorted(ai_movie_contents.keys(), key=len, reverse=True)
        
        for movie in movies:
            movie_name = movie['name']
            matched_data = None
            
            # [修改] 1. 优先精确匹配
            if movie_name in ai_movie_contents:
                matched_data = ai_movie_contents[movie_name]
            else:
                # [修改] 2. 长度降序的模糊兜底：如果 AI 返回的名字和我们的名字互相包含即可
                for ai_name in sorted_ai_names:
                    if ai_name in movie_name or movie_name in ai_name:
                        matched_data = ai_movie_contents[ai_name]
                        break
            
            if matched_data:
                movie['quote'] = matched_data.get('quote', '').strip()
                # [原因: 字段语义化] 统一优先使用 short_summary/long_summary，兼容旧字段 summary/body_summary
                movie['summary'] = matched_data.get('short_summary', matched_data.get('summary', '')).strip()
                # [原因: mode_two 正文字段兼容] long_summary -> body_summary(内部沿用老字段名供下游复用)
                movie['body_summary'] = matched_data.get('long_summary', matched_data.get('body_summary', '')).strip()
            else:
                # [防呆设计] 如果 AI 漏掉了这部电影，填充默认值防止下游图片生成器崩溃
                print(f"      ⚠️ AI 遗漏了电影《{movie_name}》的台词/简介，已自动填充默认值。")
                movie['quote'] = "“光影留存记忆。”"
                movie['summary'] = "一部值得细细品味的佳作。"
                movie['body_summary'] = ""

        # 2. 第二部分：根据 mode 组装正文顺序 (仅 collection 模式生效)
        intro_text = data.get('intro', '').strip()
        divergent_text = data.get('divergent_text', '').strip()
        progress_text = progress_str.strip()

        sections = [part_list]

        if intro_text:
            sections.append(intro_text)

        if body_mode == "mode_one":
            if divergent_text:
                sections.append(divergent_text)
        elif body_mode == "mode_two":
            summaries_block = self._build_mode_two_summaries(theme, title, movies)
            if summaries_block is None:
                return None
            if summaries_block:
                sections.append(summaries_block)
        elif body_mode == "mode_three":
            pass

        show_cta = getattr(config.Strategy.Writer, 'COLLECTION_SHOW_CTA', True)
        cta_text = str(getattr(config.Strategy.Writer, 'COLLECTION_CTA_TEXT', '')).strip()
        if show_cta and cta_text:
            sections.append(cta_text)

        if progress_text:
            sections.append(progress_text)

        # [排版] 只拼接非空段落，避免关闭 CTA 时出现空行
        final_content = "\n\n".join([s for s in sections if s])
                
        print(f"   ✅ 所有 {len(movies)} 部电影的台词与简介装配完毕！")
        print(f"   ✅ 专栏正文生成完毕 (共 {len(final_content)} 字)。")
        
        note_data = self._assemble_note(theme, title, final_content, movies)
        if not note_data:
            return None
        
        return {
            "note_data": note_data,
            "movies": movies
        }

    def _build_prompt_by_mode(self, theme: str, title: str, movies: list, movie_list_str: str, body_mode: str) -> str:
        """
        [原因: 模式化 Prompt] 根据 collection 正文模式构建不同的 AI 提示词。
        """
        movie_count = len(movies)
        min_len = int(getattr(config.Strategy.Writer, 'COLLECTION_SUMMARY_MIN_LEN', 55))
        max_len = int(getattr(config.Strategy.Writer, 'COLLECTION_SUMMARY_MAX_LEN', 80))
        divergent_min_len = int(getattr(config.Strategy.Writer, 'COLLECTION_DIVERGENT_MIN_LEN', 250))
        divergent_max_len = int(getattr(config.Strategy.Writer, 'COLLECTION_DIVERGENT_MAX_LEN', 600))

        common_header = f"""
        请为一期主题为“{theme}”，标题为“{title}”的电影专题盘点撰写文案。
        本次盘点包含以下 {movie_count} 部电影：
        {movie_list_str}

        {MAGAZINE_AESTHETICS_PROTOCOL}
        """

        if body_mode == "mode_two":
            return f"""
        {common_header}

        【任务 1：撰写过渡语 (intro)】
        注意：这段文字将展示在本期【{movie_count}部电影片单】的正下方，下文紧接着会逐一拆解这些电影。
        请写一两句话对上方的片单进行总结，并顺畅地引出下文。不要使用“今天为你推荐”等开头式的语调，请直接承接片单。

        【任务 2：主题发散 (divergent_text)】
        本模式不需要发散介绍，请直接返回空字符串 ""。

        【任务 3：拆解每部电影素材 (movies_content) 🚨核心任务】
        请为每部电影提供以下 3 个字段：
        1. 经典台词 (quote)：一句最经典的台词（必须是高质量中文翻译，严禁夹杂英文）。
        2. 海报简介 (short_summary)：极度精炼的主旨，必须控制在 25 字以内（专用于海报排版）。
        3. 正文长评 (long_summary)：客观犀利的剧情解析或影史价值陈述。
        【⚠️字数极度严格】：long_summary 的字数必须严格控制在 {min_len}-{max_len} 字之间！如果不达标或超标，系统将判定失败！

        【输出格式要求】：
        必须严格输出以下 JSON 格式，不要包含任何额外解释或代码块标记：
        {{
            "intro": "过渡语...",
            "divergent_text": "",
            "movies_content": [
                {{
                    "name": "电影名",
                    "quote": "经典台词...",
                    "short_summary": "25字以内的海报简介...",
                    "long_summary": "{min_len}-{max_len}字的正文长评..."
                }}
            ]
        }}
        """

        if body_mode == "mode_three":
            return f"""
        {common_header}

        【任务 1：撰写核心总结陈词 (intro)】
        注意：这段文字将展示在本期【{movie_count}部电影片单】的正下方。这是本篇笔记唯一的正文段落，后面没有任何解读内容了。
        请写一段话（约 50-200 字），对上方的片单进行高度概括与情感升华，一语道破这些电影的共性与魅力。
        语气要求：像电影节闭幕式上的致辞，掷地有声，余音绕梁。直接给出结论，绝对不要出现“接下来”、“下面”等引出式的词汇。

        【任务 2：主题发散 (divergent_text)】
        本模式不需要发散介绍，请直接返回空字符串 ""。

        【任务 3：拆解每部电影素材 (movies_content)】
        请为每部电影提供：
        1. 一句最经典的台词（必须是高质量中文翻译，严禁夹杂英文）。
        2. 一句话简介 short_summary（极度精炼的主旨，控制在 25 字以内，用于海报排版）。

        【输出格式要求】：
        必须严格输出以下 JSON 格式，不要包含任何额外解释或代码块标记：
        {{
            "intro": "核心总结陈词...",
            "divergent_text": "",
            "movies_content": [
                {{
                    "name": "电影名",
                    "quote": "经典台词...",
                    "short_summary": "25字以内的海报简介..."
                }}
            ]
        }}
        """

        # [原因: mode_one 独立提示词] 默认或显式 mode_one 走过渡语 + 发散的专栏模式
        return f"""
        {common_header}

        【任务 1：撰写过渡语 (intro)】
        注意：这段文字将展示在本期【{movie_count}部电影片单】的正下方，下文紧接着会有更详细的深度探讨。
        请写一两句话对上方的片单进行总结，并顺畅地引出下文。不要使用“今天为你推荐”、“接下来”等开头式的语调，请直接承接片单。

        【任务 2：撰写主题发散介绍 (divergent_text)】
        请围绕主题“{theme}”，撰写一段极具深度的专栏评述。
        写作要求：
        1. 切入点：不要空洞说教，必须从本期这 {movie_count} 部电影的共性中提取独特洞察。
        2. 行文逻辑：先用一句犀利的论断重新定义该主题，然后具体描述这类电影带给观众的真实心理/生理反应，最后落脚于“为什么我们今天依然需要这类电影”。
        3. 语感红线：句子短促有力，多用名词和动词。严禁出现“不仅仅是...更是”、“视觉盛宴”、“淋漓尽致”等烂俗套话。
        4. 字数要求：严格控制在 {divergent_min_len}-{divergent_max_len} 字之间。

        【任务 3：拆解每部电影素材 (movies_content)】
        请为每部电影提供：
        1. 一句最经典的台词（必须是高质量中文翻译，严禁夹杂英文）。
        2. 一句话简介 short_summary（极度精炼的主旨，控制在 25 字以内，用于海报排版）。

        【输出格式要求】：
        必须严格输出以下 JSON 格式，不要包含任何额外解释或代码块标记：
        {{
            "intro": "过渡语...",
            "divergent_text": "主题发散介绍...",
            "movies_content": [
                {{
                    "name": "电影名",
                    "quote": "经典台词...",
                    "short_summary": "25字以内的海报简介..."
                }}
            ]
        }}
        """

    def _get_collection_body_mode(self) -> str:
        """
        读取并校验合集正文模式。
        若配置值非法，回退到 mode_one，避免主流程崩溃。
        """
        raw_mode = str(getattr(config.Strategy.Writer, 'COLLECTION_BODY_MODE', 'mode_one')).strip()
        valid_modes = {"mode_one", "mode_two", "mode_three"}
        if raw_mode in valid_modes:
            return raw_mode
        print(f"   ⚠️ [Collection] 未知正文模式 '{raw_mode}'，已回退为 mode_one。")
        return "mode_one"

    def _build_mode_two_summaries(self, theme: str, title: str, movies: list) -> str | None:
        """
        组装 mode_two 的正文简介块:
        《电影名》：简介

        规则:
        - 每条简介长度必须在 [min_len, max_len]。
        - 仅重写不合格条目，且单条重写次数受配置控制。
        """
        min_len = int(getattr(config.Strategy.Writer, 'COLLECTION_SUMMARY_MIN_LEN', 55))
        max_len = int(getattr(config.Strategy.Writer, 'COLLECTION_SUMMARY_MAX_LEN', 80))
        max_retries = int(getattr(config.Strategy.Writer, 'COLLECTION_SUMMARY_REWRITE_RETRIES', 3))
        max_retries = max(1, max_retries)

        lines = []
        for movie in movies:
            movie_name = movie['name']
            current_summary = str(movie.get('body_summary', '')).strip()

            if not self._is_summary_length_valid(current_summary, min_len, max_len):
                rewritten = self._rewrite_single_mode_two_summary(
                    movie_name=movie_name,
                    theme=theme,
                    title=title,
                    draft=current_summary,
                    min_len=min_len,
                    max_len=max_len,
                    max_retries=max_retries
                )
                if rewritten is None:
                    print(f"   ❌ [mode_two] 《{movie_name}》简介在 {max_retries} 次重写后仍不达标，流程中止。")
                    return None
                current_summary = rewritten

            movie['body_summary'] = current_summary
            lines.append(f"《{movie_name}》：{current_summary}")

        return "\n".join(lines)

    def _rewrite_single_mode_two_summary(
        self,
        movie_name: str,
        theme: str,
        title: str,
        draft: str,
        min_len: int,
        max_len: int,
        max_retries: int
    ) -> str | None:
        """对单条不合格简介进行有限次重写，返回首个达标结果。"""
        for attempt in range(max_retries):
            if attempt == 0:
                print(f"      🔄 [mode_two] 《{movie_name}》简介不合格，开始定向重写...")
            else:
                print(f"      🔄 [mode_two] 《{movie_name}》继续重写 ({attempt + 1}/{max_retries})...")

            prompt = f"""
            请为电影《{movie_name}》写一段用于合集正文的中文简介。
            背景主题：{theme}
            合集标题：{title}
            参考草稿：{draft if draft else "（无）"}

            规则：
            1. 严格输出 {min_len}-{max_len} 字（按字符计数，含标点）。
            2. 只写简介正文，不要带片名，不要加引号，不要换行，不要序号。
            3. 文风克制、专业，避免营销腔。
            """
            resp = self.brain.think(prompt, system_prompt="你是电影杂志编辑，只返回简介正文。")
            if not resp:
                continue

            candidate = resp.strip().replace("\n", "")
            candidate = candidate.strip('"').strip("“").strip("”").strip()
            if self._is_summary_length_valid(candidate, min_len, max_len):
                print(f"      ✅ [mode_two] 《{movie_name}》简介重写达标 ({len(candidate)} 字)。")
                return candidate

        return None

    def _is_summary_length_valid(self, text: str, min_len: int, max_len: int) -> bool:
        """简介长度检测器。"""
        if not text:
            return False
        return min_len <= len(text) <= max_len
    
    # ==========================================
    # [重构 板块7] 从 main.py run_collection_mode() 迁入
    # ==========================================
    def _assemble_note(self, theme: str, title: str, content: str, movies: list) -> dict | None:
        """
        组装最终发布数据 (标签生成 + Fail-Fast 长度熔断)。
        
        [重构 板块7] 原逻辑散落在 main.py 的 run_collection_mode() 中约 45 行，
        现统一收敛至 CollectionWriterAgent 内部，main.py 只做薄层调度。
        
        Args:
            theme: 探讨主题 (如 "莱昂纳多")
            title: 笔记标题 (如 "地球球草❗️小李子的6部必看电影")
            content: 已组装完毕的正文
            movies: 已装配台词/简介的电影列表
            
        Returns:
            dict | None: 成功返回 {title, content, tags}；长度超限返回 None 触发熔断
        """
        # --- 动态组装高优精简 Tags (T0主题 + T1流量池 + T2全局去重顺延前4部电影) ---
        raw_theme = theme.replace(" ", "")
        
        # 1. 对所有电影名进行清洗和主IP提取 (泛流量截流)
        all_cleaned_tags = []
        for m in movies:
            cleaned = clean_tag(m['name'])
            if cleaned:
                all_cleaned_tags.append(cleaned)
                
        # 2. 全局去重 (保持原有高优顺序，防标签坍缩)
        unique_movie_tags = []
        for t in all_cleaned_tags:
            if t not in unique_movie_tags:
                unique_movie_tags.append(t)
                
        # 3. 截取前 4 个不重复的标签顺延补齐
        movie_tags = unique_movie_tags[:4]
        
        final_tags = [raw_theme, "电影推荐"] + movie_tags
        
        # --- 模拟 Tags 拼接成 "#标签" 后的字符串，以便合并计算总长度 ---
        tags_str = " ".join([f"#{t}" for t in final_tags])
        total_content_len = len(content) + len(tags_str)
        
        # 🚨 触发式熔断：绝不自动截断，超限直接报错终止！
        if len(title) > 20:
            print(f"\n   ❌ [致命错误] 标题长度超限 (当前 {len(title)} 字，极限 20 字)。")
            print(f"      超长标题: {title}")
            print(f"      -> 请修改文件夹名称中的标题部分后，重新运行程序！")
            return None
            
        if total_content_len > 990:
            print(f"\n   ❌ [致命错误] 正文及标签总长度超限 (当前 {total_content_len} 字，极限 990 字)。")
            print(f"      -> AI 发散过长，已中断。请清理 output 文件夹后重新运行程序，让 AI 重写！")
            return None
        
        print(f"   [安全检查] 最终标题长度合规: {len(title)}/20")
        print(f"   [安全检查] 最终正文及标签总长度合规: {total_content_len}/990")
        
        return {
            "title": title,
            "content": content,
            "tags": final_tags
        }
