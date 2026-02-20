# 文件名: little_red/utils.py
import json
import os
import requests
import datetime
import re # [保留] 用于正则处理
from openai import OpenAI
import config  # 引用配置

class HistoryManager:
    """🧠 记忆模块: 负责历史记录的读写，防止重复选题。"""
    def __init__(self):
        self.filepath = config.HISTORY_FILE
        self.history = self._load()

    def _load(self):
        if not os.path.exists(self.filepath):
            return {}
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # [平滑迁移] 兼容旧版的 {"电影名": "日期"} 格式
                migrated = {}
                for k, v in data.items():
                    if isinstance(v, str):
                        migrated[k] = {
                            "first_publish_date": v,
                            "published_modes": ["single"] # 历史老数据默认当做 single 处理
                        }
                    else:
                        migrated[k] = v
                return migrated
        except:
            return {}

    def save(self, movie_name, mode="single"):
        """[重塑] 保存电影名、首次发布日期，并记录发布模式(single/collection)"""
        now_str = datetime.datetime.now().strftime("%Y-%m-%d")
        if movie_name in self.history:
            # 若已存在，则追加模式标签 (去重机制)
            if mode not in self.history[movie_name].get("published_modes", []):
                self.history[movie_name].setdefault("published_modes", []).append(mode)
        else:
            # 若不存在，则新建全局记录
            self.history[movie_name] = {
                "first_publish_date": now_str,
                "published_modes": [mode]
            }
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(self.history, f, ensure_ascii=False, indent=2)

    def get_all_movies(self):
        """获取历史上发过的所有电影名单 (全局合并去重总数直接等于 len(keys))"""
        return list(self.history.keys())

    def get_recent(self, limit=10):
        """[新增] 获取最近发布的 N 部电影 (按日期倒序)"""
        try:
            if not self.history:
                return []
            # self.history 的结构已变，按 first_publish_date 进行倒序排序
            sorted_items = sorted(
                self.history.items(), 
                key=lambda x: x[1].get("first_publish_date", ""), 
                reverse=True
            )
            return [item[0] for item in sorted_items[:limit]]
        except Exception as e:
            print(f"⚠️ 获取最近记录失败: {e}")
            return []

    def is_posted(self, movie_name):
        """[全局查重] 检查是否在任一模式下发布过"""
        return movie_name in self.history
        
    def has_posted_in_mode(self, movie_name, mode):
        """[精准查重] 检查是否在指定模式下发布过"""
        if not self.is_posted(movie_name):
            return False
        return mode in self.history[movie_name].get("published_modes", [])

class XHSClient:
    """HTTP API 客户端: 封装小红书发布接口调用"""
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
    """DeepSeek 大脑: 封装 LLM 调用逻辑"""
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
# [升级] 数据猎手模块 (MetaFetcher v2.6 - 多级锚定重试版)
# ==========================================
class MetaFetcher:
    """
    📊 数据猎手 (MetaFetcher)
    
    核心流程:
    1. 身份核验: LLM 提取原版外文名和年份，防止中文同名混淆。
    2. TMDB 锚定: 获取 ID、官方译名、海报、票房数据。
    3. 数据融合:
       - TMDB: 票房 (revenue)
       - OMDB: IMDb, 烂番茄, Metacritic
       - Serper: 豆瓣 (Google Search + LLM 提取)
    4. 质量熔断 (Quality Gate): 若核心评分 (Douban/IMDb) 均缺失，则抛出异常终止流程。
    """
    def __init__(self):
        self.tmdb_key = config.TMDB_API_KEY
        self.omdb_key = config.OMDB_API_KEY
        self.serper_key = config.SERPER_API_KEY or config.SEARCH_API_KEY
        self.brain = LLMBrain()

    def _load_local_scores(self):
        """[新增] 安全读取本地 JSON 分数文件"""
        if not os.path.exists(config.LOCAL_SCORES_FILE):
            return {}
        try:
            with open(config.LOCAL_SCORES_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}

    def _save_to_local(self, movie_name, new_entries):
        """[新增] 增量保存分数到本地 JSON"""
        if not new_entries:
            return
        local_scores = self._load_local_scores()
        if movie_name not in local_scores:
            local_scores[movie_name] = {}
        local_scores[movie_name].update(new_entries)
        
        try:
            with open(config.LOCAL_SCORES_FILE, 'w', encoding='utf-8') as f:
                json.dump(local_scores, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"   ⚠️ 写入 local_scores.json 失败: {e}")

    def fetch_all(self, movie_name, specific_year=None):
        """
        [升级] 接收 specific_year 用于精准锚定
        """
        year_log = f" ({specific_year})" if specific_year else ""
        print(f"\n📊 [MetaFetcher] 正在构建数据传导链: 《{movie_name}》{year_log}")
        
        # === Step 0: 身份核验 (Identity Resolution) ===
        # 解决中文同名/译名混淆问题 (如 "狩猎" vs "狩猎人")
        # [升级] 提取原版外文名，取代容易犯错的纯英文名
        identity = self._resolve_identity(movie_name, specific_year)
        
        search_year = specific_year if specific_year else ""
        original_title = None
        
        if identity:
            search_year = identity.get('year', search_year)
            original_title = identity.get('original_title')
            print(f"   🆔 身份核验成功: 解析到原版外文名 '{original_title}' ({search_year})")
        else:
            print(f"   ⚠️ 身份核验失败，将直接使用中文名盲搜: '{movie_name}'")

        # === Step 1: TMDB 锚定 (Anchor) ===
        # [核心升级] 多级降级精准锚定策略
        base_info = self._get_tmdb_base(movie_name, search_year)
        
        if not base_info and original_title and original_title.lower() != movie_name.lower():
            print(f"   ⚠️ 中文名搜索未命中，降级使用原版外文名搜索: '{original_title}'")
            base_info = self._get_tmdb_base(original_title, search_year)

        if not base_info:
            print("   ❌ TMDB 未找到影片信息，将使用空数据兜底。")
            return {}

        imdb_id = base_info.get("imdb_id")
        tmdb_id = base_info.get("tmdb_id") # [保留] 确保获取 TMDB ID
        final_year = base_info.get("year", "")
        official_cn_name = base_info.get("official_cn_title", movie_name) # 获取官方译名
        
        print(f"   ✅ TMDB 锚定成功: ID={imdb_id}, Year={final_year}, 官方中译=《{official_cn_name}》")

        # [修改] 获取详情数据（包含票房、类型、地区）
        revenue_cny = 0
        genres = "未知类型"
        region = "未知地区"
        if tmdb_id:
            tmdb_details = self._get_tmdb_details(tmdb_id)
            revenue_cny = tmdb_details.get("revenue_cny", 0)
            genres = tmdb_details.get("genres", "未知类型")
            region = tmdb_details.get("region", "未知地区")
            if revenue_cny > 0:
                # 打印友好的日志
                print(f"   💰 票房数据获取: 约 {revenue_cny / 100000000:.1f} 亿人民币")
            print(f"   🌍 类型/地区获取: {genres} | {region}")

        local_scores = self._load_local_scores()
        movie_cache = local_scores.get(movie_name, {})

        scores = {
            "year": final_year,
            "tmdb_id": tmdb_id, # [Plan B] 关键修改: 必须将 TMDB ID 传递给下游
            "imdb": "N/A",
            "rotten_tomatoes": "N/A", # 影评人 (OMDB)
            "metacritic": "N/A",
            "douban": "N/A",
            "revenue_cny": revenue_cny, # [新增] 注入票房数据
            "genres": genres,           # [新增] 注入类型数据
            "region": region            # [新增] 注入国家地区数据
        }

        # === Step 2: 西方数据 (OMDB) ===
        fetched_new_omdb = False
        if self.omdb_key and imdb_id:
            # [核心修改] 严选逻辑：如果缓存中的 imdb 是 "N/A"，拒绝命中，强制重新调 API 抓取
            if "imdb" in movie_cache and "rotten_tomatoes" in movie_cache and "metacritic" in movie_cache and movie_cache.get("imdb") != "N/A":
                scores["imdb"] = movie_cache["imdb"]
                scores["rotten_tomatoes"] = movie_cache["rotten_tomatoes"]
                scores["metacritic"] = movie_cache["metacritic"]
                print(f"   📥 命中本地缓存 (OMDB数据)")
            else:
                omdb_data = self._get_omdb_scores(imdb_id)
                if omdb_data:
                    fetched_new_omdb = True
                    scores.update(omdb_data)
                    print(f"   ✅ OMDB 数据获取: IMDb={scores['imdb']}, 🍅(影评人)={scores['rotten_tomatoes']}, Ⓜ️ ={scores['metacritic']}")
        
        # === Step 3: 豆瓣评分 (Serper - 使用官方中文名) ===
        # 策略：用 TMDB 返回的官方中文名 搜豆瓣
        fetched_new_douban = False
        if self.serper_key:
            # [核心修改] 严选逻辑：如果缓存中的 douban 是 "N/A"，拒绝命中，强制重新调 API 抓取
            if "douban" in movie_cache and movie_cache.get("douban") != "N/A":
                scores["douban"] = movie_cache["douban"]
                print(f"   📥 命中本地缓存 (豆瓣数据)")
            else:
                douban_score = self._get_douban_score(official_cn_name, final_year)
                if douban_score is not None:
                    fetched_new_douban = True
                    scores["douban"] = douban_score
                    print(f"   ✅ Serper + LLM 提取豆瓣分: {douban_score}")
                else:
                    print(f"   ⚠️ 豆瓣评分提取失败或网络波动 (本次不计入缓存)")

        # [新增] 全局底层写入逻辑：只要调了 API（无论是第一次查还是重试覆盖），都保存进去
        new_cache_entries = {}
        if fetched_new_omdb:
            new_cache_entries["imdb"] = scores["imdb"]
            new_cache_entries["rotten_tomatoes"] = scores.get("rotten_tomatoes", "N/A")
            new_cache_entries["metacritic"] = scores.get("metacritic", "N/A")
            
        if fetched_new_douban:
            new_cache_entries["douban"] = scores["douban"]
            
        if new_cache_entries:
            self._save_to_local(movie_name, new_cache_entries)
            print(f"   💾 [缓存] 成功将《{movie_name}》的评分(含重试更新)写入本地。")

        # === Step 4: [新增] 数据质量熔断检查 (Quality Gate) ===
        # 要求：豆瓣和IMDb评分至少有一个获取到，否则报错中断
        if scores.get("douban") == "N/A" and scores.get("imdb") == "N/A":
            print(f"   ⛔ [熔断] 数据质量不足: 豆瓣({scores['douban']}) 与 IMDb({scores['imdb']}) 均无有效评分。")
            raise ValueError(f"Data Quality Gate Failed: Movie '{movie_name}' has neither Douban nor IMDb score.")
        
        return scores

    def _resolve_identity(self, movie_name, specific_year=None):
        """[新增] 询问 LLM 该电影的官方英文名和年份"""
        try:
            # [升级] 注入特定年份约束
            constraint = ""
            if specific_year:
                constraint = f"User Constraint: The movie MUST be from the year {specific_year}."

            prompt = f"""
            Task: Identify the movie "{movie_name}".
            {constraint}
            Return valid JSON with its **Original Title** (the native language title, e.g., Spanish title for a Spanish movie) and **Release Year**.
            
            Example:
            Input: "霸王别姬" -> {{"original_title": "霸王别姬", "year": "1993"}}
            Input: "看不见的客人" -> {{"original_title": "Contratiempo", "year": "2016"}}
            Input: "狩猎" (Mads Mikkelsen) -> {{"original_title": "Jagten", "year": "2012"}}
            
            JSON format only:
            {{
                "original_title": "...",
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

    def _get_tmdb_details(self, movie_id):
        """[修改] 获取票房详情并折算为人民币，同时获取类型和国家地区"""
        try:
            url = f"https://api.themoviedb.org/3/movie/{movie_id}"
            params = {"api_key": self.tmdb_key, "language": "zh-CN"}
            resp = requests.get(url, params=params, timeout=10)
            data = resp.json()
            
            # 1. 获取票房 (USD)
            revenue_usd = data.get("revenue", 0)
            revenue_cny = 0
            if revenue_usd:
                # 汇率折算
                rate = config.Strategy.Writer.USD_TO_CNY_RATE
                revenue_cny = int(revenue_usd * rate)
                
            # 2. 提取类型 (Genres)
            genres_list = [g.get("name") for g in data.get("genres", [])]
            genres_str = "/".join(genres_list) if genres_list else "未知类型"
            
            # 3. 提取国家/地区 (Production Countries) 并进行绝对合规映射
            regions_list = []
            for c in data.get("production_countries", []):
                name = c.get("name", "")
                # 强制合规拦截器 (香港，台湾，澳门强制映射为中国香港，中国台湾，中国澳门)
                if name in ["香港", "Hong Kong"]: name = "中国香港"
                elif name in ["台湾", "Taiwan"]: name = "中国台湾"
                elif name in ["澳门", "Macao", "Macau"]: name = "中国澳门"
                if name:
                    regions_list.append(name)
            region_str = "/".join(regions_list) if regions_list else "未知地区"
            
            return {
                "revenue_cny": revenue_cny,
                "genres": genres_str,
                "region": region_str
            }
            
        except Exception as e:
            print(f"   ⚠️ TMDB 详情获取失败: {e}")
            return {"revenue_cny": 0, "genres": "未知类型", "region": "未知地区"}

    def _get_omdb_scores(self, imdb_id):
        """获取 OMDB 评分数据 (IMDb, Rotten Tomatoes, Metacritic)"""
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
            else:
                # [新增] 明确找不到，放入 N/A 防止缓存穿透
                res["imdb"] = "N/A"
                res["rotten_tomatoes"] = "N/A"
                res["metacritic"] = "N/A"
        except Exception as e:
            print(f"   ⚠️ OMDB 获取失败: {e}")
        return res

    def _get_douban_score(self, movie_name, year):
        """Google Search (自然语言) -> LLM 提取豆瓣分"""
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
            4. **多源验证**：如果片段 1 说 8.5，片段 2 说 8.5，那就是 8.5。如果冲突，取出现次数最多或来源最可信（如直接带 douban.com 域名）的。
            5. **兜底策略**：如果你翻遍了也找不到明确的聚合评分，请诚实地返回 "N/A"，不要瞎猜。
            【输出要求】：
            仅输出一个数字字符串（例如 "9.2" 或 "N/A"），严禁包含任何其他文字、符号或解释。
            """
            
            score = self.brain.think(prompt, system_prompt="你是一个数据提取器。").strip()
            
            match = re.search(r"\d+\.\d", score)
            if match: return match.group(0)
            if "N/A" in score: return "N/A" # [修改] 将 return None 改为 return "N/A"，代表明确无分数
            if score.isdigit() and len(score) < 3: return score
            return None
            
        except Exception as e:
            print(f"   ⚠️ 豆瓣分数获取失败: {e}")
            return None

# ==========================================
# [新增] 标签清洗与泛流量截流器 (Tag Cleaner)
# ==========================================
def clean_tag(raw_str: str) -> str:
    """
    [新增] 标签清洗器 (Tag Cleaner)
    核心策略：主标题截断 + 尾号抹除 (泛流量截流)
    解决小红书标点符号断层及续集流量分散问题。
    """
    if not raw_str:
        return ""
        
    # 预处理：去掉书名号等绝对不能出现在 tag 里的包裹符号
    raw_str = raw_str.replace("《", "").replace("》", "")
        
    # 1. 符号截断：遇到冒号、破折号、空格、括号等直接截断，取前半截 (主 IP)
    # 注意包含了全角和半角的标点符号
    import re
    parts = re.split(r'[:：\-——(（\s]', raw_str)
    base_name = parts[0] if parts else raw_str
    
    # 2. 尾号抹除：去掉末尾的数字 (如 银翼杀手2049 -> 银翼杀手, 指环王3 -> 指环王)
    cleaned_name = re.sub(r'\d+$', '', base_name)
    
    # 3. 防误杀兜底：如果抹除数字后变成了空字符串 (说明原片名就是纯数字，如 1917 或 2012)，则退回 base_name
    if not cleaned_name:
        return base_name
        
    return cleaned_name