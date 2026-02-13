# 文件名: little_red/utils.py
import json
import os
import requests
import datetime
import re # [保留] 用于正则处理
from openai import OpenAI
import config  # 引用配置

class HistoryManager:
    """🧠 记忆模块"""
    def __init__(self):
        self.filepath = config.HISTORY_FILE
        self.history = self._load()

    def _load(self):
        if not os.path.exists(self.filepath):
            return {}
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}

    def save(self, movie_name):
        """保存电影名和当前日期"""
        self.history[movie_name] = datetime.datetime.now().strftime("%Y-%m-%d")
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(self.history, f, ensure_ascii=False, indent=2)

    def get_all_movies(self):
        """获取历史上发过的所有电影名单"""
        return list(self.history.keys())

    def get_recent(self, limit=10):
        """[新增] 获取最近发布的 N 部电影 (按日期倒序)"""
        try:
            if not self.history:
                return []
            # self.history 的结构是 {"电影名": "2023-10-27"}
            # 按日期(value)进行倒序排序
            sorted_items = sorted(self.history.items(), key=lambda x: x[1], reverse=True)
            # 只返回电影名列表
            return [item[0] for item in sorted_items[:limit]]
        except Exception as e:
            print(f"⚠️ 获取最近记录失败: {e}")
            return []

    def is_posted(self, movie_name):
        """[新增] 检查是否已发布 (辅助方法)"""
        return movie_name in self.history

class XHSClient:
    """HTTP API 客户端"""
    def __init__(self):
        self.base_url = config.API_BASE_URL

    def call_tool(self, tool_name, args=None):
        if args is None: args = {}
        url_map = {
            "check_login_status": ("/login/status", "GET"),
            "publish_content": ("/publish", "POST"),
        }
        
        if tool_name not in url_map:
            print(f"❌ 未知工具: {tool_name}")
            return None

        endpoint, method = url_map[tool_name]
        url = f"{self.base_url}{endpoint}"

        try:
            if method == "GET":
                resp = requests.get(url, params=args)
            else:
                resp = requests.post(url, json=args)
            
            resp.raise_for_status()
            res_json = resp.json()
            
            if res_json.get("success") is True:
                return res_json.get("data", res_json)
            if "code" in res_json and res_json["code"] != 0:
                print(f"❌ API错误: {res_json.get('error') or res_json.get('message')}")
                return None
            return res_json.get("data", res_json)
        except Exception as e:
            print(f"❌ 连接服务失败: {e}")
            return None

class LLMBrain:
    """DeepSeek 大脑"""
    def __init__(self):
        self.client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)

    def think(self, prompt, system_prompt="你是一个专业的小红书电影博主。"):
        try:
            # [保留] 保持原版体验
            print("   🧠 DeepSeek-Reasoner 正在深度思考中...")
            response = self.client.chat.completions.create(
                model="deepseek-reasoner",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                stream=False
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"❌ LLM 调用失败: {e}")
            return None

# ==========================================
# [升级] 数据猎手模块 (MetaFetcher v2.4 - 稳健精简版)
# ==========================================
class MetaFetcher:
    """📊 数据猎手: 身份核验 -> 英文锚定 -> 数据分发 (移除不稳定的烂番茄观众分)"""
    def __init__(self):
        self.tmdb_key = config.TMDB_API_KEY
        self.omdb_key = config.OMDB_API_KEY
        self.serper_key = config.SERPER_API_KEY or config.SEARCH_API_KEY
        self.brain = LLMBrain()

    def fetch_all(self, movie_name):
        print(f"\n📊 [MetaFetcher] 正在构建数据传导链: 《{movie_name}》")
        
        # === Step 0: 身份核验 (Identity Resolution) ===
        # 解决中文同名/译名混淆问题 (如 "狩猎" vs "狩猎人")
        identity = self._resolve_identity(movie_name)
        
        # 确定 TMDB 搜索的锚点
        if identity:
            search_query = identity['en_title']
            search_year = identity['year']
            print(f"   🆔 身份核验成功: 锁定为 '{search_query}' ({search_year})")
        else:
            search_query = movie_name
            search_year = ""
            print(f"   ⚠️ 身份核验失败，降级使用中文名搜索: '{search_query}'")

        # === Step 1: TMDB 锚定 (Anchor) ===
        base_info = self._get_tmdb_base(search_query, search_year)
        if not base_info:
            print("   ❌ TMDB 未找到影片信息，将使用空数据兜底。")
            return {}

        imdb_id = base_info.get("imdb_id")
        tmdb_id = base_info.get("tmdb_id") # [保留] 确保获取 TMDB ID
        final_year = base_info.get("year", "")
        official_cn_name = base_info.get("official_cn_title", movie_name) # 获取官方译名
        
        print(f"   ✅ TMDB 锚定成功: ID={imdb_id}, Year={final_year}, 官方中译=《{official_cn_name}》")

        # [新增] 获取票房数据并折算
        revenue_cny = 0
        if tmdb_id:
            revenue_cny = self._get_box_office(tmdb_id)
            if revenue_cny > 0:
                # 打印友好的日志
                print(f"   💰 票房数据获取: 约 {revenue_cny / 100000000:.1f} 亿人民币")

        scores = {
            "year": final_year,
            "imdb": "N/A",
            "rotten_tomatoes": "N/A", # 影评人 (OMDB)
            "metacritic": "N/A",
            "douban": "N/A",
            "revenue_cny": revenue_cny # [新增] 注入票房数据
        }

        # === Step 2: 西方数据 (OMDB) ===
        if self.omdb_key and imdb_id:
            omdb_data = self._get_omdb_scores(imdb_id)
            scores.update(omdb_data)
            print(f"   ✅ OMDB 数据获取: IMDb={scores['imdb']}, 🍅(影评人)={scores['rotten_tomatoes']}, Ⓜ️ ={scores['metacritic']}")
        
        # === Step 3: 豆瓣评分 (Serper - 使用官方中文名) ===
        # 策略：用 TMDB 返回的官方中文名 搜豆瓣
        if self.serper_key:
            douban_score = self._get_douban_score(official_cn_name, final_year)
            if douban_score:
                scores["douban"] = douban_score
                print(f"   ✅ Serper + LLM 提取豆瓣分: {douban_score}")
            else:
                print(f"   ⚠️ 豆瓣评分提取失败 (N/A)")

        # === Step 4: [新增] 数据质量熔断检查 (Quality Gate) ===
        # 要求：豆瓣和IMDb评分至少有一个获取到，否则报错中断
        if scores.get("douban") == "N/A" and scores.get("imdb") == "N/A":
            print(f"   ⛔ [熔断] 数据质量不足: 豆瓣({scores['douban']}) 与 IMDb({scores['imdb']}) 均无有效评分。")
            raise ValueError(f"Data Quality Gate Failed: Movie '{movie_name}' has neither Douban nor IMDb score.")
        
        return scores

    def _resolve_identity(self, movie_name):
        """[新增] 询问 LLM 该电影的官方英文名和年份"""
        try:
            prompt = f"""
            Task: Identify the movie "{movie_name}".
            Return valid JSON with its **Official English Title** and **Release Year**.
            
            Example:
            Input: "霸王别姬" -> {{"en_title": "Farewell My Concubine", "year": "1993"}}
            Input: "狩猎" (Mads Mikkelsen) -> {{"en_title": "The Hunt", "year": "2012"}}
            
            JSON format only:
            {{
                "en_title": "...",
                "year": "..."
            }}
            """
            resp = self.brain.think(prompt, system_prompt="You are a movie database helper. Output JSON only.")
            clean_json = resp.replace("```json", "").replace("```", "").strip()
            data = json.loads(clean_json)
            return data
        except:
            return None

    def _get_tmdb_base(self, query_name, year=None):
        """[升级] 支持按年份精准搜索"""
        try:
            search_url = "https://api.themoviedb.org/3/search/movie"
            params = {
                "api_key": self.tmdb_key, 
                "query": query_name, 
                "language": "zh-CN"
            }
            # 如果有年份，增加过滤参数
            if year:
                params["primary_release_year"] = year

            resp = requests.get(search_url, params=params)
            results = resp.json().get("results", [])
            
            # 如果按年份没搜到，尝试不带年份复活一次 (防止 LLM 记错年份导致搜索失败)
            if not results and year:
                del params["primary_release_year"]
                resp = requests.get(search_url, params=params)
                results = resp.json().get("results", [])

            if not results: return None
            
            top_result = results[0]
            movie_id = top_result["id"]
            release_date = top_result.get("release_date", "")
            final_year = release_date.split("-")[0] if release_date else ""
            official_cn_title = top_result.get("title", "") # TMDB 的 'title' 在 zh-CN 模式下就是官方译名

            # 获取外部 ID
            id_url = f"https://api.themoviedb.org/3/movie/{movie_id}/external_ids"
            id_resp = requests.get(id_url, params={"api_key": self.tmdb_key})
            external_ids = id_resp.json()
            
            return {
                "tmdb_id": movie_id,
                "imdb_id": external_ids.get("imdb_id"),
                "year": final_year,
                "official_cn_title": official_cn_title
            }
        except Exception as e:
            print(f"   ⚠️ TMDB Base 获取失败: {e}")
            return None

    def _get_box_office(self, movie_id):
        """[新增] 获取票房详情并折算为人民币"""
        try:
            url = f"https://api.themoviedb.org/3/movie/{movie_id}"
            params = {"api_key": self.tmdb_key, "language": "zh-CN"}
            resp = requests.get(url, params=params, timeout=10)
            data = resp.json()
            
            # 获取票房 (USD)
            revenue_usd = data.get("revenue", 0)
            
            if not revenue_usd: 
                return 0
            
            # 汇率折算
            rate = config.Strategy.Writer.USD_TO_CNY_RATE
            return int(revenue_usd * rate)
            
        except Exception as e:
            print(f"   ⚠️ 票房获取失败: {e}")
            return 0

    def _get_omdb_scores(self, imdb_id):
        res = {}
        try:
            url = f"http://www.omdbapi.com/?i={imdb_id}&apikey={self.omdb_key}"
            data = requests.get(url, timeout=10).json()
            
            if data.get("Response") == "True":
                res["imdb"] = data.get("imdbRating", "N/A")
                
                ratings = data.get("Ratings", [])
                for r in ratings:
                    if r["Source"] == "Rotten Tomatoes":
                        res["rotten_tomatoes"] = r["Value"]
                    elif r["Source"] == "Metacritic":
                        res["metacritic"] = r["Value"].split("/")[0]
        except Exception as e:
            print(f"   ⚠️ OMDB 获取失败: {e}")
        return res

    def _get_douban_score(self, movie_name, year):
        """Google Search (自然语言) -> LLM 提取"""
        query = f"{movie_name} {year} 豆瓣评分"
        
        try:
            url = "https://google.serper.dev/search"
            api_key = self.serper_key
            headers = {'X-API-KEY': api_key, 'Content-Type': 'application/json'}
            payload = json.dumps({"q": query, "gl": "cn", "num": 3})
            resp = requests.post(url, headers=headers, data=payload, timeout=10)
            data = resp.json()
            
            snippets = []
            if "organic" in data:
                for item in data["organic"]:
                    title = item.get('title', '')
                    snippet = item.get('snippet', '')
                    snippets.append(f"Title: {title}\nSnippet: {snippet}")
            
            if not snippets: return None
            
            context = "\n---\n".join(snippets)
            
            prompt = f"""
            你是一个不仅精通电影，还擅长从杂乱信息中去伪存真的“数据侦探”。
            【任务目标】：从以下 Google 搜索片段中，提取电影《{movie_name}》的【豆瓣评分】。
            【搜索结果片段】：
            {context}
            【推理法则】：
            1. **优先看标题**：很多时候分数直接写在标题里，如 "xx (豆瓣) - 9.0分"。
            2. **警惕个人评价**：如果看到 "我觉得是3分"、"打分3星"，这是个人评论，**忽略它**。我们要的是大众聚合评分（通常在 6.0 - 9.9 之间）。
            3. **寻找关键字**：重点关注 "豆瓣评分"、"评分"、"Score" 后面的数字。
            4. **多源验证**：如果片段 1 说 8.5，片段 2 也说 8.5，那就是 8.5。如果冲突，取出现次数最多或来源最可信（如直接带 douban.com 域名）的。
            5. **兜底策略**：如果你翻遍了也找不到明确的聚合评分，请诚实地返回 "N/A"，不要瞎猜。
            【输出要求】：
            仅输出一个数字字符串（例如 "9.2" 或 "N/A"），严禁包含任何其他文字、符号或解释。
            """
            
            score = self.brain.think(prompt, system_prompt="你是一个数据提取器。").strip()
            
            match = re.search(r"\d+\.\d", score)
            if match: return match.group(0)
            if "N/A" in score: return None
            if score.isdigit() and len(score) < 3: return score
            return None
            
        except Exception as e:
            print(f"   ⚠️ 豆瓣分数获取失败: {e}")
            return None