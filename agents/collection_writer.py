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
        
        # [修改] 提取电影列表（不带分数），发送给 AI 进行内容拆解
        movie_list_parts = []
        for i, m in enumerate(movies):
            movie_list_parts.append(f"{i+1}. {m['name']}")
            
        movie_list_str = "\n".join(movie_list_parts)
        
        # 构建强大的批处理 Prompt
        prompt = f"""
        请为一期主题为“{theme}”，标题为“{title}”的电影专题盘点撰写文案。
        本次盘点包含以下 {len(movies)} 部电影：
        {movie_list_str}

        {MAGAZINE_AESTHETICS_PROTOCOL}
        
        【任务 1：撰写开场引入 (intro)】
        请根据标题“{title}”和主题“{theme}”，写一两句话作为本文的开场白，说明本期介绍的是什么。
        【特权豁免】：在这个环节，你可以打破旁观者视角，像卷首语一样直接点题，明确写出“本期为您呈现...”等引导语。
        
        【任务 2：撰写主题发散介绍 (divergent_text)】
        请围绕主题“{theme}”展开深度讨论。
          - 重点写“感官体验”、“价值观共鸣”与“现实投射”。
          - 【⚠️极其重要】：这部分的字数（算上标点符号和Emoji）绝对不能超过 380 字！必须精炼高级！
          
        【任务 3：拆解每部电影 (movies_content)】
        请为上述每一部电影提供：
        1. 一句最经典的台词（必须是中文翻译版本，严禁夹杂英文，最好是具有普世哲学意味的）。
        2. 一句话简介 (极度精炼的剧情梗概或核心主旨，字数尽量控制在 25 字以内，不要带片名)。

        【输出格式要求】：
        必须严格输出以下 JSON 格式，不要包含任何额外的解释或代码块标记：
        {{
            "intro": "开场的引入语...",
            "divergent_text": "深度探讨的发散文案...",
            "movies_content": [
                {{
                    "name": "电影名",
                    "quote": "经典台词...",
                    "summary": "一句话简介..."
                }}
            ]
        }}
        """
        
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
                
                # 🚨 发散介绍字数熔断检查
                divergent_text = data.get('divergent_text', '')
                if len(divergent_text) > 400:
                    print(f"   ⚠️ [熔断] 发散介绍字数超限 ({len(divergent_text)} 字，限制 400 字)，打回重写！")
                    data = None # 重置 data 以触发下一轮
                    continue
                else:
                    print(f"   ✅ 发散介绍字数合规 ({len(divergent_text)}/400 字)")
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

        # 1. 第一部分：引入 + 进度条 + 灵魂结尾
        part1 = f"{data.get('intro', '')}{progress_str}\n\n先码住，慢慢看！"
        
        # 2. 第二部分：本期片单 (使用随机 Emoji 与配置开关)
        list_emoji = random.choice(EMOJI_POOL)
        part2_lines = [f"{list_emoji}本期片单："]
        
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
            if getattr(config.Strategy.Writer, 'SHOW_GENRE', False) and m.get('genres') and m.get('genres') != '未知类型':
                extras.append(m['genres'])
            if getattr(config.Strategy.Writer, 'SHOW_REGION', False) and m.get('region') and m.get('region') != '未知地区':
                extras.append(m['region'])
                
            if extras:
                line += f" ({' | '.join(extras)})"
            part2_lines.append(line)
            
        part2 = "\n".join(part2_lines)
        
        # 3. 第三部分：发散介绍
        part3 = data.get('divergent_text', '')
        
        final_content = f"{part1}\n\n{part2}\n\n{part3}"
        
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
                movie['summary'] = matched_data.get('summary', '').strip()
            else:
                # [防呆设计] 如果 AI 漏掉了这部电影，填充默认值防止下游图片生成器崩溃
                print(f"      ⚠️ AI 遗漏了电影《{movie_name}》的台词/简介，已自动填充默认值。")
                movie['quote'] = "“光影留存记忆。”"
                movie['summary'] = "一部值得细细品味的佳作。"
                
        print(f"   ✅ 所有 {len(movies)} 部电影的台词与简介装配完毕！")
        print(f"   ✅ 专栏正文生成完毕 (共 {len(final_content)} 字)。")
        
        note_data = self._assemble_note(theme, title, final_content, movies)
        if not note_data:
            return None
        
        return {
            "note_data": note_data,
            "movies": movies
        }
    
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