# 文件名: agents/collection_writer.py
import json
import config
from utils import LLMBrain

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
        
        # [修改] 提取带有动态分数的片单字符串，用于发给 AI，增强区分度防幻觉
        movie_list_parts = []
        for i, m in enumerate(movies):
            name = m['name']
            scores = []
            if m.get('douban'):
                scores.append(f"豆瓣: {m['douban']}")
            if m.get('imdb'):
                scores.append(f"IMDb: {m['imdb']}")
            
            # 动态拼接分数后缀
            score_suffix = f" ({', '.join(scores)})" if scores else ""
            movie_list_parts.append(f"{i+1}. {name}{score_suffix}")
            
        movie_list_str = "\n".join(movie_list_parts)
        
        # 构建强大的批处理 Prompt
        prompt = f"""
        请为一期主题为“{theme}”的电影专题盘点撰写文案。
        本次盘点包含以下 {len(movies)} 部电影：
        {movie_list_str}

        {MAGAZINE_AESTHETICS_PROTOCOL}
        
        【任务 1：拆解每部电影 (movies_content)】
        请为上述每一部电影提供：
        1. 一句最经典的台词（必须是中文翻译版本，严禁夹杂英文，最好是具有普世哲学意味的）。
        2. 一句话简介 (极度精炼的剧情梗概或核心主旨，字数尽量控制在 25 字以内，不要带片名)。

        【任务 2：撰写专栏正文 (main_body)】
        正文请遵循以下结构，字数控制在 400-600 字左右：
        第一部分：列举片单。请使用换行，将上述所有电影排版成一个清晰的清单列表。
        第二部分：主题探讨。请围绕主题“{theme}”展开深度讨论。
          - 如果是【电影风格】(如悬疑/惊悚/治愈)：请重点写“感官体验”与“观看建议”。(例如：悬疑片不需要一惊一乍的音效，真正的恐惧来自人性的深渊。)
          - 如果是【核心主题】(如女性/成长/科幻)：请重点写“价值观共鸣”与“现实投射”。(例如：她们不是谁的附庸，在各自的平行宇宙里，长出了属于自己的骨头。)
          - 如果是【特定导演/演员】：请探讨其独特的个人美学或演技演变。
        
        【输出格式要求】：
        必须严格输出以下 JSON 格式，不要包含任何额外的解释或代码块标记：
        {{
            "movies_content": [
                {{
                    "name": "电影名",
                    "quote": "经典台词...",
                    "summary": "一句话简介..."
                }}
            ],
            "main_body": "包含片单列举和主题探讨的完整正文，使用 \\n 进行换行排版..."
        }}
        """
        
        system_prompt = "你是一个冷静专业的电影杂志主笔。你只输出合法的JSON对象。"
        
        response = self.brain.think(prompt, system_prompt=system_prompt)
        
        if not response:
            print("   ❌ AI 未返回任何文案内容，合集处理中止。")
            return None
            
        try:
            # 清洗可能存在的 markdown 代码块
            clean_json = response.replace("```json", "").replace("```", "").strip()
            data = json.loads(clean_json)
            
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
            print(f"   ✅ 专栏正文生成完毕 (共 {len(data.get('main_body', ''))} 字)。")
            
            return {
                "content": data.get('main_body', '（正文生成失败）'),
                "movies": movies
            }
            
        except Exception as e:
            print(f"   ❌ 文案 JSON 解析失败: {e}")
            print(f"   [Debug API返回的原始内容]:\n{response[:500]}...") # 打印前500字帮助排查
            return None