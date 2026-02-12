# 文件名: little_red/agents/writer.py
import json
import requests
import random
import config
from utils import LLMBrain

class WriterAgent:
    """✍️ 文案 Agent (数据驱动版 - 严格保留原版 Prompt 风味)"""
    def __init__(self):
        self.tmdb_key = config.TMDB_API_KEY
        self.brain = LLMBrain()

    def run(self, movie_name, meta_data=None):
        print(f"\n✍️ [2/5 WriterAgent] 正在撰写高级感文案 (注入真实评分数据)...")
        
        if meta_data is None: meta_data = {}

        # === 1. 准备随机 Emoji 盲盒 ===
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
        real_reviews = self._fetch_tmdb_reviews(movie_name)
        review_context = ""
        if real_reviews:
            review_context = f"【真实TMDB评论素材(仅供参考)】：\n{json.dumps(real_reviews, ensure_ascii=False)}"
        else:
            review_context = "【无真实评论】：**请不要生成 hot_comments 字段**。"
            
        # === 3. 构建 Prompt (严格恢复原版) ===
        # 准备真实数据注入 (移除不稳定的烂番茄观众分)
        score_info_str = (
            f"豆瓣评分: {meta_data.get('douban', 'N/A')} | "
            f"IMDb评分: {meta_data.get('imdb', 'N/A')} | "
            f"烂番茄新鲜度(影评人): {meta_data.get('rotten_tomatoes', 'N/A')} | "
            f"Metacritic: {meta_data.get('metacritic', 'N/A')} | "
            f"年份: {meta_data.get('year', '')}"
        )

        prompt = f"""
        请为电影《{movie_name}》写一篇排版精美、有高级感的小红书笔记。
        【参考数据 (请优先使用)】：{score_info_str}
        {review_context}
        
        【核心指令】：
        1. **简介流畅化 (分段)**：synopsis 字段请写一段引人入胜的剧情叙述（约150-200字）。**为了阅读舒适，请务必使用换行符将内容分成 2 个自然段**，不要堆成一大块。不要剧透核心谜底，重点营造氛围。
        
        2. **荣誉高光 (宁缺毋滥)**：honors 字段**只输出重磅奖项**(如奥斯卡/金球/戛纳/柏林/威尼斯)或**影史地位**(如IMDb Top 250)。**如果没有此类顶级荣誉，请直接返回空字符串""**。
        
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
        1. title: 标题 (<20字, 必带Emoji)
        
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
           
        8. hot_comments: (列表，无素材则为空)
           
        9. ending: "自由发挥的结尾文案..."

        10. tags: 标签列表。
        """
        
        response = self.brain.think(prompt, system_prompt="你是一个审美极高的小红书博主，只输出JSON。")
        try:
            clean_json = response.replace("```json", "").replace("```", "").strip()
            data = json.loads(clean_json)
            
            # === 4. 智能篇幅控制 ===
            is_valid = self._sanitize_content(data, selected_emojis, meta_data)
            
            if not is_valid:
                return None

            # === 5. 组装最终正文 ===
            final_content = self._assemble_content(data, selected_emojis, meta_data)
            
            return {
                "title": data['title'],
                "content": final_content,
                "tags": data['tags']
            }

        except Exception as e:
            print(f"❌ 文案解析失败: {e}")
            return None

    def _assemble_content(self, data, emojis, meta_data):
        """
        将 JSON 数据组装成最终的文本字符串 (双行评分版)
        """
        basic = data['basic_info']
        cast = data['cast_info']
        
        # --- 1. 档案区 (重构：双行评分) ---
        line1_parts = []
        if meta_data.get('douban') and meta_data['douban'] != 'N/A':
            line1_parts.append(f"豆瓣 {meta_data['douban']}")
        elif basic.get('douban_score'): # 兜底
             line1_parts.append(f"豆瓣 {basic['douban_score']}")

        if meta_data.get('imdb') and meta_data['imdb'] != 'N/A':
            line1_parts.append(f"IMDb {meta_data['imdb']}")
        elif basic.get('imdb_score'): # 兜底
             line1_parts.append(f"IMDb {basic['imdb_score']}")
        
        line1 = "  |  ".join(line1_parts)
        
        # [修改] 第二行固定为：🍅 烂番茄 91% | Ⓜ️ MTC 80
        line2_parts = []
        if meta_data.get('rotten_tomatoes') and meta_data['rotten_tomatoes'] != 'N/A':
            line2_parts.append(f"🍅 烂番茄 {meta_data['rotten_tomatoes']}")
            
        if meta_data.get('metacritic') and meta_data['metacritic'] != 'N/A':
            line2_parts.append(f"Ⓜ️ MTC {meta_data['metacritic']}")
            
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
        
        # --- 其余部分保持原样 ---
        
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
        if data.get('hot_comments'):
            comments = [f"“{c}”" for c in data['hot_comments']]
            comments_str = "\n".join(comments)
            comments_section = f"{emojis['comment']} 关于电影\n{comments_str}\n\n"
        
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

    def _count(self, text):
        return len(text)

    def _sanitize_content(self, data, emojis, meta_data):
        """
        🛡️ 内容审查与智能压缩
        """
        if len(data.get('tags', [])) > 10:
            data['tags'] = data['tags'][:10]

        original_title = data['title']
        clean_title = original_title.replace(" ", "")
        current_len = self._count(clean_title)
        
        if current_len <= 20:
            data['title'] = clean_title
        else:
            retry_count = 0
            max_retries = getattr(config, 'MAX_TITLE_RETRIES', 3)
            
            while retry_count < max_retries:
                print(f"   ⚠️ 标题超长 ({current_len}字)，正在第 {retry_count+1} 次尝试重写...")
                extra_instruction = ""
                if retry_count > 0:
                    extra_instruction = f"警告：上一次你写的还是太长了（{current_len}字），请务必更短一点！"
                    
                prompt = f"""
                请将标题“{original_title}”改写为 **20字以内**。
                要求：
                1. 必须保留原有的 Emoji（如果有）。
                2. 保持原意，但用词更精简。
                3. 直接返回新标题，不要解释。
                {extra_instruction}
                """
                
                new_title = self.brain.think(prompt, system_prompt="你是一个擅长起短标题的小红书博主。")
                
                if new_title:
                    clean_new_title = new_title.strip().replace('"', '').replace(" ", "")
                    new_len = self._count(clean_new_title)
                    
                    if new_len <= 20:
                        data['title'] = clean_new_title
                        print(f"      ✅ 标题优化成功: {clean_new_title}")
                        break 
                    else:
                        current_len = new_len
                
                retry_count += 1
            
            final_len = self._count(data.get('title', ''))
            if final_len > 20:
                print(f"❌ [Writer] 标题重写失败，经过 {max_retries} 次尝试后仍超长 ({final_len}字)。")
                return False

        rewrite_steps = [
            ('highlight_expansion', '深度发散'),
            ('synopsis', '剧情简介'),
            ('highlight_expansion', '深度发散'), 
            ('synopsis', '剧情简介')
        ]
        step_index = 0
        
        while True:
            # 传入 meta_data
            current_text = self._assemble_content(data, emojis, meta_data)
            current_len = self._count(current_text)
            
            if current_len <= 1000:
                break 
                
            comments = data.get('hot_comments', [])
            if comments:
                if len(comments) >= 2:
                    removed = comments.pop()
                    print(f"   ✂️ [长度优化] 正文超限({current_len}字)，删除 1 条末尾评论...")
                else:
                    data['hot_comments'] = [] 
                    print(f"   ✂️ [长度优化] 正文仍超限，移除整个评论区板块...")
                continue 
            
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
            break
        
        return True

    def _fetch_tmdb_reviews(self, movie_name):
        # 保持原样...
        if not self.tmdb_key: return []
        try:
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