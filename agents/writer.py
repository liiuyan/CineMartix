# 文件名: agents/writer.py
import json
import requests
import random
import config
from utils import LLMBrain

class WriterAgent:
    """✍️ 文案 Agent (随机Emoji + 去粗体 + 深度发散分段版)"""
    def __init__(self):
        self.tmdb_key = config.TMDB_API_KEY
        self.brain = LLMBrain()

    def run(self, movie_name):
        print(f"\n✍️ [2/5 WriterAgent] 正在撰写高级感文案...")
        
        # === 1. 准备随机 Emoji 盲盒 ===
        emoji_bank = {
            "archive": ["🎞️", "📼", "💿", "📀", "📁", "📂", "📽️", "📺", "📻", "💽", "🔖"],
            "honor":   ["🏆", "🥇", "🎖️", "🏅", "👑", "🌟", "✨", "💐", "🏵️", "💎", "⚜️"],
            "cast":    ["🎬", "🎥", "📹", "🎭", "👨‍🎨", "🖌️", "🎩", "🪜", "🗣️", "🏗️"],
            "quote":   ["🗨️", "💬", "💭", "🗯️", "📢", "📜", "🖋️", "📝", "📖", "🗣️", "✉️"],
            "comment": ["💡", "🧩", "📌", "📍", "📡", "🔔", "📣", "📝", "🤔"]
        }
        
        # 随机抽取本轮使用的 Emoji
        e_arch = random.choice(emoji_bank["archive"])
        e_honor = random.choice(emoji_bank["honor"])
        e_cast = random.choice(emoji_bank["cast"])
        e_quote = random.choice(emoji_bank["quote"])
        e_comm = random.choice(emoji_bank["comment"])

        # === 2. 获取外部素材 ===
        real_reviews = self._fetch_tmdb_reviews(movie_name)
        review_context = ""
        if real_reviews:
            review_context = f"【真实TMDB评论素材(仅供参考)】：\n{json.dumps(real_reviews, ensure_ascii=False)}"
        else:
            review_context = "【无真实评论】：**请不要生成 hot_comments 字段**。"

        # === 3. 构建 Prompt ===
        prompt = f"""
        请为电影《{movie_name}》写一篇排版精美、有高级感的小红书笔记。
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
            
            # === 4. 组装正文 (去粗体 + 随机Emoji) ===
            basic = data['basic_info']
            cast = data['cast_info']
            
            # 1. 档案区
            score_part = f"豆瓣 {basic['douban_score']}"
            if basic.get('imdb_score'):
                score_part += f"  |  IMDb {basic['imdb_score']}"
            
            header_section = (
                f"{e_arch} 影片档案\n"  # 去掉 **
                f"{score_part}\n"
                f"{basic['country']} ({basic['release_date']})  |  {basic['genre']}\n\n"
            )
            
            # 2. 荣誉区 (宁缺毋滥)
            honor_section = ""
            if data.get('honors') and data['honors'].strip():
                honor_section = f"{e_honor} 荣誉\n{data['honors']}\n\n" # 去掉 **

            # 3. 主创区
            cast_section = (
                f"{e_cast} 主创\n" # 去掉 **
                f"导演：{cast['director']}\n"
                f"主演：{cast['actors']}\n\n"
            )

            # 4. 简介区 (已要求 LLM 自带换行符)
            synopsis_section = f"{data['synopsis']}\n\n"
            
            # 5. 深度发散区 (无标题，直接空行衔接)
            highlight_section = ""
            if data.get('highlight_expansion'):
                # 确保段落间有呼吸感
                highlight_section = f"{data['highlight_expansion']}\n\n"

            # 6. 台词区
            quotes_section = ""
            quotes = data.get('quotes', [])
            if quotes:
                quotes_section = f"{e_quote} 台词\n" + "\n".join(quotes) + "\n\n" # 去掉 **

            # 7. 评论区 (可选)
            comments_section = ""
            if data.get('hot_comments'):
                comments = [f"“{c}”" for c in data['hot_comments']]
                comments_str = "\n".join(comments)
                comments_section = f"{e_comm} 关于电影\n{comments_str}\n\n" # 去掉 **
            
            # 8. 结尾
            ending_section = f"{data.get('ending', '评论区告诉我你的想法！👇')}"

            # 组合最终文案
            final_content = (
                header_section + 
                honor_section + 
                cast_section + 
                "--------------------------------------\n\n" +
                synopsis_section + 
                highlight_section +  # 新增的深度发散板块
                quotes_section + 
                comments_section + 
                ending_section
            )
            
            return {
                "title": data['title'],
                "content": final_content,
                "tags": data['tags']
            }

        except Exception as e:
            print(f"❌ 文案解析失败: {e}")
            return None

    def _fetch_tmdb_reviews(self, movie_name):
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