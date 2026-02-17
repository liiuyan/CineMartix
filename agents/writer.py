# 文件名: agents/writer.py
import json
import requests
import random
import re
import config
from utils import LLMBrain, HistoryManager # [修改] 引入 HistoryManager 用于计算进度

# ==============================================================================
# 🎨 全局美学协议 (High-End Aesthetics Protocol v2.0)
# ==============================================================================
# 这是一个常量模版，用于在初始生成和重写阶段反复注入，确保审美不降级。
AESTHETICS_PROTOCOL =  """
【小红书电影号·真实质感协议 (Grounded Aesthetics Protocol v2.2)】

1. 🏆 黄金范例 (Gold Standard) - **请严格模仿以下标题的气质与结构**：
   - 🎬《教父》：黑帮史诗的永恒回响
   - 🌌 星际穿越：爱是唯一的维度
   - 🍃治愈系天花板 | 小森林冬春篇
   - 🌿遇见龙猫：宫崎骏的童年魔法
   - ✨穿越神隐的成长之旅 | 千与千寻
   - 疯狂动物城2｜五年，仍是彼此光✨

2. 🚫 结构禁区 (Structural Bans) - **精准打击营销号句式**：
   - 🔴 **禁止“长定语+的+片名”**：严禁写“……的《电影名》”。
     - ❌ 错误：`一部让你重新相信温暖与羁绊的《触不可及》` (啰嗦，片名被淹没)
     - ✅ 修正：`神级友情 | 触不可及` (改为管道符结构)
     - ✅ 修正：`神级友情 | 触不可及` (改为管道符结构)
     - ✅ 修正：`《触不可及》：跨越阶级的灵魂共振` (改为冒号结构)
   - 🔴 **禁止“推文腔”**：严禁使用“一部让你……”、“带你走进……”、“教会我们……”这种长句开场。

3. 🌡️ 词汇温度调节 (Vocabulary Temperature)
   - 🔴 **绝对禁用**：哭晕、炸裂、绝绝子、yyds、跪求、强推、暴风哭泣、全程高能、无尿点。
   

4. ✍️ 核心法则：短语化 (Phrasing)
   - 标题必须由 **“精炼的短语”** 组成，严禁使用“完整的句子”。
   - ❌ Sentence: `《星际穿越》是一部讲述爱可以穿越维度的电影`
   - ✅ Phrase: `星际穿越：爱是唯一的维度`

5. ⚠️ 再次重申：严禁在标题中出现年份数字。
"""

class WriterAgent:
    """
    ✍️ 文案 Agent (数据驱动版 - 严格保留原版 Prompt 风味 + 审美协议植入 + 输入清洗)
    
    负责将元数据 (MetaData) 转化为具有“小红书味”的高级感文案。
    核心能力：
    1. 双重票房门槛判断。
    2. 真实评论注入 (中英对照 + 金句提取)。
    3. 智能篇幅压缩 (Sanitization) 与标题动态重写。
    """
    
    def __init__(self):
        self.tmdb_key = config.TMDB_API_KEY
        self.brain = LLMBrain()

    def run(self, movie_name: str, meta_data: dict = None) -> dict | None:
        """
        执行文案生成主流程。

        Args:
            movie_name (str): 电影名称。
            meta_data (dict, optional): MetaFetcher 抓取的评分与票房数据。
                                      包含: douban, imdb, revenue_cny 等。

        Returns:
            dict | None: 生成成功返回笔记数据字典 (title, content, tags)，失败返回 None。
        """
        # ==================== 🛡️ 输入清洗 (Sanitization) ====================
        # [Fix] 防止上游传入 "电影名|年份" 格式的脏数据导致 Prompt 指令冲突
        # 优先处理全角符号，再处理半角符号
        clean_name = movie_name
        if "｜" in clean_name:
            clean_name = clean_name.split("｜")[0].strip()
        if "|" in clean_name:
            clean_name = clean_name.split("|")[0].strip()
            
        # 更新 movie_name 变量，确保后续所有逻辑（Prompt/Check）都使用纯净片名
        movie_name = clean_name
        # ===================================================================

        print(f"\n✍️ [2/5 WriterAgent] 正在撰写高级感文案 (注入真实评分数据)...")
        print(f"   🎬 当前处理电影: 《{movie_name}》") # [新增] 打印确认清洗后的片名
        
        if meta_data is None: meta_data = {}

        # === 1. 准备随机 Emoji 盲盒 ===
        # 用于增加文案的视觉丰富度，每次运行随机抽取不同 Emoji。
        emoji_bank = {
            "archive": ["🎞️", "📼", "💿", "📀", "📁", "📂", "📽️", "📺", "📻", "💽", "🔖"],
            "honor":   ["🏆", "🥇", "🎖️", "🏅", "👑", "🌟", "✨", "💐", "🏵️", "💎", "⚜️"],
            "cast":    ["🎬", "🎥", "📹", "🎭", "👨‍🎨", "🖌️", "🎩", "🪜", "🗣️", "🏗️"],
            "quote":   ["🗨️", "💬", "💭", "🗯️", "📢", "📜", "🖋️", "📝", "📖", "🗣️", "✉️"],
            "comment": ["💡", "🧩", "📌", "📍", "📡", "🔔", "📣", "📝", "🤔"]
        }
        
        selected_emojis = {
            "archive": random.choice(emoji_bank["archive"]),
            "honor":   random.choice(emoji_bank["honor"]),
            "cast":    random.choice(emoji_bank["cast"]),
            "quote":   random.choice(emoji_bank["quote"]),
            "comment": random.choice(emoji_bank["comment"])
        }

        # === 2. 获取外部素材 ===
        # [Plan B] 提取 TMDB ID，传给评论获取函数 (防止找错电影)
        target_id = meta_data.get('tmdb_id')
        real_reviews = self._fetch_tmdb_reviews(movie_name, target_id)
        
        review_context = ""
        if real_reviews:
            review_context = f"【真实TMDB评论素材(仅供参考)】：\n{json.dumps(real_reviews, ensure_ascii=False)}"
        else:
            review_context = "【无真实评论】：**请不要生成 hot_comments 字段**。"
            
        # === 3. 构建 Prompt (严格恢复原版) ===
        
        # [逻辑] 票房双重门槛处理
        revenue_val = meta_data.get('revenue_cny', 0)
        min_threshold = config.Strategy.Writer.MIN_BOX_OFFICE_CNY
        force_threshold = config.Strategy.Writer.FORCE_BOX_OFFICE_CNY
        
        box_office_str = "N/A"
        
        # 判定票房展示策略：强制展示 vs 替补展示
        if revenue_val >= force_threshold:
            # 门槛 B: 超过10亿 -> 必须展示
            val_in_yi = revenue_val / 100000000
            box_office_str = f"全球票房约 {val_in_yi:.1f} 亿人民币 (必须展示)"
        elif revenue_val >= min_threshold:
            # 门槛 A: 超过5亿 -> 作为替补
            val_in_yi = revenue_val / 100000000
            box_office_str = f"全球票房约 {val_in_yi:.1f} 亿人民币 (作为替补)"
            
        # 准备真实数据注入 (移除不稳定的烂番茄观众分)
        score_info_str = (
            f"豆瓣评分: {meta_data.get('douban', 'N/A')} | "
            f"IMDb评分: {meta_data.get('imdb', 'N/A')} | "
            f"烂番茄新鲜度(影评人): {meta_data.get('rotten_tomatoes', 'N/A')} | "
            f"Metacritic: {meta_data.get('metacritic', 'N/A')} | "
            f"年份: {meta_data.get('year', '')} | "
            f"票房: {box_office_str}"  # [新增] 注入带标签的票房
        )

        # 构建 Prompt (Few-Shot Learning + Chain of Thought)
        prompt = f"""
        请为电影《{movie_name}》写一篇排版精美、有高级感的小红书笔记。
        【参考数据 (请优先使用)】：{score_info_str}
        {review_context}
        
        {AESTHETICS_PROTOCOL}  <-- 【核心植入：美学协议】
        
        【核心指令】：
        1. **简介流畅化 (分段)**：synopsis 字段请写一段引人入胜的剧情叙述（约150-200字）。**为了阅读舒适，请务必使用换行符将内容分成 2 个自然段**，不要堆成一大块。不要剧透核心谜底，重点营造氛围。
        
        2. **荣誉高光 (宁缺毋滥)**：honors 字段请优先输出重磅奖项(如奥斯卡/金球/戛纳/柏林/威尼斯)或影史地位(如IMDb Top 250)。
           **关键规则**：请观察传入的【票房数据】后的备注。
           1. 如果备注是 **(必须展示)**：无论有没有奖项，都**必须**将票房写在荣誉里（例如 "奥斯卡最佳影片 / 全球票房破 20 亿"）。
           2. 如果备注是 **(作为替补)**：只有在没有重磅奖项时，才输出票房。
           3. 否则，如果票房无效且无奖项，直接返回空字符串""。
        
        3. **深度发散 (Highlight Expansion)**：
           请从电影的【影史地位 / 美学视听 / 卡司幕后 / 题材视野】中挑选**最值得谈论的一个特色**，生成 highlight_expansion 字段 (100-200字)。
           **必须严格模仿以下“事实+发散”的逻辑，并适当分段：**
           * **若涉及影史节点**：比如“伪纪录片恐怖片”，请解释什么是伪纪录片，并联想《女巫布莱尔》；比如“哈利波特终章”，请回顾魔法世界的陪伴感；比如“希斯·莱杰遗作”，请讨论他演的小丑为何封神，并提及《断背山》及英年早逝的惋惜；比如“奥斯卡大赢家/票房破纪录”，请对比当年战胜了谁（如《阿甘》胜《肖申克》）。
           * **若涉及美学视听**：比如“韦斯·安德森”，请描述对称构图和糖果配色，提及《布达佩斯大饭店》；比如“诺兰实拍/汉斯季默配乐”，请发散他为了追求真实还做过什么疯狂事（炸飞机/种玉米），或配乐的史诗感。
           * **若涉及卡司幕后**：比如“演员突破”（如安妮·海瑟薇/贾玲），请发散她们为了角色剪发/增肥的牺牲；比如“昆汀”，请解释什么是“暴力美学”。
           * **若涉及题材视野**：比如“改变国家的电影”（如《熔炉》），请科普“熔炉法”的具体影响；比如“特殊职业”（如入殓师），请科普该职业如何给予逝者尊严。
           **注意：这一段不要加标题！不要加Emoji分割线！直接写内容！**

        4. **政治正确**：country 字段涉及中国地区时，必须输出"中国香港"、"中国台湾"、"中国澳门"。
        
        5. **拒绝模版**：ending 字段请自由发挥，写一段简短、口语化、有共鸣的结尾。

        【返回 JSON】：
        1. title: 标题 (<20字, 必带Emoji, **必须包含电影名《{movie_name}》**, **严格遵循上述美学协议**)
        
        2. basic_info: 
           {{
             "douban_score": "9.3",
             "imdb_score": "8.8",
             "country": "美国 / 英国",
             "release_date": "2010",
             "genre": "科幻 / 悬疑"
           }}
        
        3. honors: "奥斯卡金像奖最佳摄影 / IMDb Top 250 NO.9" (若无顶级荣誉则返回 "")

        4. cast_info: 
           {{
             "director": "克里斯托弗·诺兰",
             "actors": "莱昂纳多·迪卡普里奥 / 约瑟夫·高登-莱维特" 
           }}
            
        5. synopsis: "一段完整的剧情简介文本，包含换行符..."
        
        6. highlight_expansion: "深度发散的特色内容，包含换行符，不要标题..."
        
        7. quotes: ["英文台词...", "中文翻译...", "英文台词...", "中文翻译..."] (2-3句最经典的即可)
           
        8. hot_comments (评论区处理规则):
           * **中英对照模式**：
             - 若素材是外语：必须严格按照 `English Key Sentence\\n中文意译` 的格式输出。**英文在前，中文在后，中间用换行符分隔。不要自己加引号。**
             - 若素材是中文：直接保留原话，不要加引号。
           * **长度铁律**：单条评论（含中英双语内容）的总字数**严禁超过 60 字**。
           * **语气要求**：中文部分必须像真实的中国网友发言（口语化、带情绪），拒绝机翻腔。

        9. ending: "自由发挥的结尾文案..."

        10. tags: 标签列表。
        """
        
        # 调用 LLM 生成初始 JSON
        response = self.brain.think(prompt, system_prompt="你是一个审美极高的小红书博主，只输出JSON。")
        try:
            clean_json = response.replace("```json", "").replace("```", "").strip()
            data = json.loads(clean_json)
            
            # === 4. 智能篇幅控制 (Sanitization) ===
            # 这里包含标题重写逻辑和正文压缩逻辑
            # [Fix] 传入 movie_name，用于标题合规性检查
            is_valid = self._sanitize_content(data, selected_emojis, meta_data, movie_name)
            
            if not is_valid:
                print("❌ 文案生成失败：标题始终无法通过合规性检查（长度或缺失片名）。")
                return None

            # === 5. 组装最终正文 (含进度条逻辑) ===
            
            # [新增] 提前生成 1000部阅片计划进度条
            # 策略: 实时扫描 HistoryManager 获取已发布数量 + 1
            progress_str = ""
            try:
                history_manager = HistoryManager()
                past_count = len(history_manager.get_all_movies())
                current_index = past_count + 1
                total_target = config.Strategy.Writer.PROJECT_TOTAL_COUNT
                
                # 格式化文案 (如: "\n📅 1000部电影推荐计划：51/1000")
                progress_str = config.Strategy.Writer.PROGRESS_BAR_TEMPLATE.format(
                    current=current_index, 
                    total=total_target
                )
                print(f"   📊 [Project] 进度计算: {current_index}/{total_target}")
                
            except Exception as e:
                # 健壮性保护：如果读取历史失败，仅打印警告，进度条置空，不影响主流程
                print(f"   ⚠️ 进度条生成失败 (非致命): {e}")
                progress_str = ""

            # 最终正文内容 (此变量用于返回)
            final_content = ""

            # ------------------------------------------------------------------
            # 📜 正文篇幅控制逻辑 (The Content Loop) - [修改版: 纳入进度条]
            # ------------------------------------------------------------------
            rewrite_steps = [
                ('highlight_expansion', '深度发散'),
                ('synopsis', '剧情简介'),
                ('highlight_expansion', '深度发散'), 
                ('synopsis', '剧情简介')
            ]
            step_index = 0
            
            while True:
                # 临时组装以检查长度
                base_text = self._assemble_content(data, selected_emojis, meta_data)
                # [关键修改] 将进度条纳入总长度计算
                current_text = base_text + progress_str
                
                current_len = self._count(current_text)
                
                if current_len <= 1000:
                    final_content = current_text # 长度达标，锁定内容
                    break 
                
                # 策略1: 优先删除评论
                comments = data.get('hot_comments', [])
                if comments:
                    if len(comments) >= 2:
                        removed = comments.pop()
                        print(f"   ✂️ [长度优化] 正文超限({current_len}字，含进度条)，删除 1 条末尾评论...")
                    else:
                        data['hot_comments'] = [] 
                        print(f"   ✂️ [长度优化] 正文仍超限，移除整个评论区板块...")
                    continue 
                
                # 策略2: AI 递归精简正文段落
                if step_index < len(rewrite_steps):
                    field, name = rewrite_steps[step_index]
                    step_index += 1
                    
                    print(f"   📉 [AI重写] 正文仍超限({current_len}字)，正在精简“{name}”部分...")
                    
                    origin_text = data.get(field, "")
                    prompt = f"""
                    请将以下这段关于电影的【{name}】内容进行精简。
                    原内容：
                    {origin_text}
                    要求：保留核心看点，语言紧凑，必须比原来篇幅更短。直接返回内容。
                    """
                    
                    new_text = self.brain.think(prompt, system_prompt="你是一个擅长精简文案的编辑。")
                    if new_text:
                        data[field] = new_text.strip().replace('"', '')
                    continue 
                
                print(f"   ⚠️ 经过所有缩减努力，正文依然略长 ({current_len}字)。保留当前版本。")
                final_content = current_text
                break
            
            return {
                "title": data['title'],
                "content": final_content,
                "tags": data['tags']
            }

        except Exception as e:
            print(f"❌ 文案解析失败: {e}")
            return None

    def _assemble_content(self, data: dict, emojis: dict, meta_data: dict) -> str:
        """
        将 JSON 数据组装成最终的文本字符串 (小红书笔记正文)。
        
        特性:
        - 动态评分积木: 自动隐藏 N/A 的评分项。
        - 双行评分展示: 第一行 (豆瓣/IMDb), 第二行 (烂番茄/MTC)。
        """
        basic = data['basic_info']
        cast = data['cast_info']
        
        # --- 1. 档案区 (重构：动态积木) ---
        line1_parts = []
        
        # 豆瓣 (优先用真实数据 MetaData，若无则尝试用 AI 生成数据，但若均为 N/A 则不显示)
        douban_val = meta_data.get('douban')
        if douban_val and douban_val != 'N/A':
            line1_parts.append(f"豆瓣 {douban_val}")
        elif basic.get('douban_score') and basic['douban_score'] != 'N/A':
             line1_parts.append(f"豆瓣 {basic['douban_score']}")

        # IMDb
        imdb_val = meta_data.get('imdb')
        if imdb_val and imdb_val != 'N/A':
            line1_parts.append(f"IMDb {imdb_val}")
        elif basic.get('imdb_score') and basic['imdb_score'] != 'N/A':
             line1_parts.append(f"IMDb {basic['imdb_score']}")
        
        line1 = "  |  ".join(line1_parts)
        
        # [修改] 第二行 (烂番茄 / MTC) - 同样采用动态显示，不显示 N/A
        line2_parts = []
        
        rt_val = meta_data.get('rotten_tomatoes')
        if rt_val and rt_val != 'N/A':
            line2_parts.append(f"🍅 烂番茄 {rt_val}")
            
        mtc_val = meta_data.get('metacritic')
        if mtc_val and mtc_val != 'N/A':
            line2_parts.append(f"Ⓜ️ MTC {mtc_val}")
            
        line2 = "  |  ".join(line2_parts)
        
        header_section = f"{emojis['archive']} 影片档案\n"
        if line1: header_section += f"{line1}\n"
        if line2: header_section += f"{line2}\n"
        
        year_str = meta_data.get('year') or basic.get('release_date', '')
        country_str = basic.get('country', '')
        genre_str = basic.get('genre', '')
        
        info_line = country_str
        if year_str: info_line += f" ({year_str})"
        info_line += f"  |  {genre_str}"
        
        header_section += f"{info_line}\n\n"
        
        # --- 其余部分组装 ---
        
        honor_section = ""
        if data.get('honors') and data['honors'].strip():
            honor_section = f"{emojis['honor']} 荣誉\n{data['honors']}\n\n"

        cast_section = (
            f"{emojis['cast']} 主创\n"
            f"导演：{cast['director']}\n"
            f"主演：{cast['actors']}\n\n"
        )

        synopsis_section = f"{data['synopsis']}\n\n"
        
        highlight_section = ""
        if data.get('highlight_expansion'):
            highlight_section = f"{data['highlight_expansion']}\n\n"

        quotes_section = ""
        quotes = data.get('quotes', [])
        if quotes:
            quotes_section = f"{emojis['quote']} 台词\n" + "\n".join(quotes) + "\n\n"

        comments_section = ""
        # 仅当有评论素材时才生成此板块
        # [修改] 双语评论优化逻辑：智能拆解换行符，分别加引号
        if data.get('hot_comments'):
            formatted_comments = []
            for c in data['hot_comments']:
                if "\n" in c:
                    # 双语模式：拆分 -> 英文直引号 -> 中文全角引号
                    parts = c.split("\n")
                    english_part = parts[0].strip()
                    # 容错：防止没有第二行
                    chinese_part = parts[1].strip() if len(parts) > 1 else ""
                    
                    formatted = f'"{english_part}"\n“{chinese_part}”'
                    formatted_comments.append(formatted)
                else:
                    # 纯中文模式：直接全角引号
                    formatted_comments.append(f'“{c}”')
            
            comments_str = "\n".join(formatted_comments)
            # [UI调整] 标题已从“关于电影”改为“电影评论”
            comments_section = f"{emojis['comment']} 电影评论\n{comments_str}\n\n"
        
        ending_section = f"{data.get('ending', '评论区告诉我你的想法！👇')}"

        return (
            header_section + 
            honor_section + 
            cast_section + 
            "--------------------------------------\n\n" +
            synopsis_section + 
            highlight_section + 
            quotes_section + 
            comments_section + 
            ending_section
        )

    def _count(self, text: str) -> int:
        """
        辅助函数：计算字符串长度 (Unicode 字符计数)
        空格、中文、Emoji 统一按 1 个字符计算。
        注意：Python 的 len() 对大多数 Emoji 是 1，对复杂 Emoji 可能是多字符，
        这里为了简单高效，直接使用 len()，符合一般直觉。
        """
        return len(text)

    def _sanitize_content(self, data: dict, emojis: dict, meta_data: dict, movie_name: str) -> bool:
        """
        🛡️ 内容审查与智能压缩 (Sanitization Pipeline)
        
        【标题漏斗逻辑】：
        1. 预处理：删除所有空格。
        2. 第一关：检测是否包含电影名 (必须包含，否则直接打回重写)。
        3. 第二关：检测长度 (必须 <= 20)。
        4. 第三关：年份查杀 (Year Killer) - 严禁年份出现，触发美学重写。
        """
        if len(data.get('tags', [])) > 10:
            data['tags'] = data['tags'][:10]

        # ==========================================================
        # 🛡️ 标题熔断漏斗 (The Title Funnel)
        # ==========================================================
        clean_movie_name = movie_name.replace(" ", "")
        max_retries = config.Strategy.Writer.MAX_TITLE_RETRIES
        retry_count = 0
        
        # [新增] 读取 Emoji 开关，用于构建重写指令
        use_emoji = config.Strategy.Writer.ENABLE_TITLE_EMOJI
        if use_emoji:
            emoji_instruction = "推荐使用 `Emoji + 电影名` 或 `电影名 + Emoji` 的结构，增加视觉跳跃感。"
        else:
            emoji_instruction = "**严禁使用任何 Emoji 表情**，保持纯文字的极简与严肃。"
        
        # 编译年份正则 (匹配 19xx 或 20xx)
        year_pattern = re.compile(r'(19|20)\d{2}')

        while retry_count < max_retries:
            current_title = data.get('title', '')
            # 预处理：删除空格 (不计入字数)
            clean_title = current_title.replace(" ", "")
            title_len = self._count(clean_title)
            has_name = clean_movie_name in clean_title

            # [新增] 年份检测逻辑 (Year Check)
            found_years = year_pattern.findall(clean_title)
            is_year_violation = False
            for y in found_years:
                if y not in movie_name:
                    is_year_violation = True
                    break

            print(f"   🔍 [Title Check] 长度:{title_len}/20, 含片名:{has_name}, 含年份违规:{is_year_violation} | 原文: {current_title}")

            # --- 判定逻辑 ---
            if not has_name:
                print(f"      ⛔ 致命错误：标题缺失电影名《{movie_name}》，跳过物理降级，直接打回重写。")
            
            elif is_year_violation:
                print(f"      ⛔ 美学违规：标题包含非原名年份 ({found_years})，强制重写以提升质感。")
            
            elif title_len <= 20:
                # ✅ 完美通过
                print(f"      ✅ 标题合规。")
                data['title'] = clean_title
                break 
            
            else:
                # ⚠️ 包含电影名但超长 -> 尝试物理降级
                print(f"      ✂️ 标题超长 ({title_len}字)，启动物理降级漏斗...")
                
                # Step A: 尝试删除书名号 《 》
                temp_title = clean_title
                if "《" in temp_title and "》" in temp_title:
                    print(f"         🔨 [Funnel Step 1] 尝试删除书名号...")
                    temp_title = temp_title.replace("《", "").replace("》", "")
                    if self._count(temp_title) <= 20:
                        print(f"         ✅ 删除书名号后达标 ({self._count(temp_title)}字)。")
                        data['title'] = temp_title
                        break 
                
                # Step B: 尝试删除 Emoji (Regex 匹配)
                if self._count(temp_title) > 20:
                    print(f"         🔨 [Funnel Step 2] 尝试删除所有 Emoji...")
                    no_emoji_title = re.sub(r'[^\w\u4e00-\u9fff,.:;!?，。：；！？"\'\(\)（）]', '', temp_title)
                    if self._count(no_emoji_title) <= 20:
                        print(f"         ✅ 删除Emoji后达标 ({self._count(no_emoji_title)}字)。")
                        data['title'] = no_emoji_title
                        break
                
                print(f"      ⚠️ 物理降级失败，仍超长 ({self._count(temp_title)}字)，转交 AI 重写。")

            # --- 第三关：AI 重写 (The Rewrite Loop) ---
            retry_count += 1
            if retry_count >= max_retries:
                print(f"❌ [Writer] 标题重写次数耗尽 ({max_retries}次)，最终仍不合规，触发熔断。")
                return False

            print(f"   🔄 [Rewrite] 第 {retry_count} 次重写标题...")
            
            # 动态构建“负向反馈”指令
            feedback_instruction = ""
            
            # Case 1: 年份违规
            if is_year_violation:
                feedback_instruction += f"\n   - **严重美学违规**：检测到标题包含年份数字，这是严重的各种浪费！请删除年份，并利用腾出的空间加入一个**具体的意象词**（参考美学协议中的推荐词库），提升文学性。"
            
            # Case 2: 缺失片名
            if not has_name:
                feedback_instruction += f"\n   - **致命错误**：上一次你竟然忘了写电影名！**必须包含《{movie_name}》**！"
            
            # Case 3: 长度违规
            if title_len > 20:
                feedback_instruction += f"\n   - **长度警告**：标题超长了！请缩短成小于20字的标题，请在缩减字数的同时，保留最核心的意象词，删掉那些无意义的修饰词（如‘真的’、‘超级’），确保缩短后依然有文学质感。"
            
            # [Hybrid Prompt] 融合硬性约束与软性审美
            prompt = f"""
            你上一次生成的标题不合格。请重写标题。

            {AESTHETICS_PROTOCOL}  <-- 【再次注入美学协议】

            【硬性红线 (必须遵守)】：
            1. **必须包含电影名**：`{movie_name}` (完整的官方译名)。
            2. **字数死线**：必须 **<= 20 字** (Emoji算1个字)。

            【针对性修正指令】：
            {feedback_instruction}
            
            【结构要求】：{emoji_instruction}

            请直接输出新的标题字符串，不要加任何解释。
            """
            
            new_title_raw = self.brain.think(prompt, system_prompt="你是一个听话的、不废话的文案编辑。")
            if new_title_raw:
                # 清洗一下返回值 (去掉可能的引号等)
                data['title'] = new_title_raw.strip().replace('"', '').replace("`", "")
            
            # 循环继续，回到开头重新检查...

        # ==========================================================
        # 📜 正文篇幅控制逻辑在上方已被替换 (The Content Loop)
        # ==========================================================
        
        return True

    def _fetch_tmdb_reviews(self, movie_name: str, tmdb_id: int = None) -> list:
        """
        从 TMDB API 获取用户评论。
        
        策略:
        - [Plan B] 优先使用 tmdb_id 获取。
        - 优先获取中文评论 (zh)。
        - 不足 3 条时，使用英文评论补齐 (截取前300字符)。
        - 仅返回前 3 条，供 WriterAgent 挑选金句。
        """
        if not self.tmdb_key: return []
        try:
            movie_id = None
            if tmdb_id:
                # [Plan B] 直接使用 ID
                movie_id = tmdb_id
            else:
                # [Fallback] 降级搜索
                search_url = "https://api.themoviedb.org/3/search/movie"
                resp = requests.get(search_url, params={"api_key": self.tmdb_key, "query": movie_name, "language": "zh-CN"})
                results = resp.json().get("results", [])
                if not results: return []
                movie_id = results[0]["id"]
            
            review_url = f"https://api.themoviedb.org/3/movie/{movie_id}/reviews"
            r_resp = requests.get(review_url, params={"api_key": self.tmdb_key})
            reviews = r_resp.json().get("results", [])
            
            zh_reviews = [r["content"] for r in reviews if r.get("iso_639_1") == "zh"]
            en_reviews = [r["content"][:300] for r in reviews if r.get("iso_639_1") != "zh"]
            return (zh_reviews + en_reviews)[:3] 
        except:
            return []