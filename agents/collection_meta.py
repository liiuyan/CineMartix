# 文件名: agents/collection_meta.py
import os
import json
import config
from utils import MetaFetcher

class CollectionMetaFetcher:
    """
    📊 合集批量数据猎手 (CollectionMetaFetcher)
    
    负责批量获取合集名单中所有电影的豆瓣和 IMDb 评分。
    核心逻辑：
    1. 优先读取 config 指定的本地 local_scores.json 进行分数兜底。
    2. 如果本地未命中，降级调用原版 MetaFetcher 的 API 抓取逻辑。
    3. 柔性容错：绝不因为缺少某部电影的评分而熔断整个流程，缺失分数将自动隐藏并打印警告。
    """
    def __init__(self):
        self.local_scores_file = config.LOCAL_SCORES_FILE
        self.use_local = getattr(config.Strategy.System, 'USE_LOCAL_SCORES', True)
        
        # 实例化原版的抓取工具 (复用其底层的 TMDB 和 Serper 搜索逻辑)
        # 注意：这里我们只用到它的查询能力，我们会自己处理异常，防止它熔断合集流程
        self.api_fetcher = MetaFetcher() 

    def run(self, movies: list) -> list:
        """
        执行批量获取分数逻辑。
        
        Args:
            movies (list): CollectionTopicAgent 提取的电影列表
                           格式: [{'name': '星际穿越', 'path': '...', 'index': 1}, ...]
                           
        Returns:
            list: 补充了分数的电影列表
                  格式: [{'name': '星际穿越', 'douban': '9.4', 'imdb': '8.7', ...}, ...]
        """
        print("\n📊 [2/5 CollectionMetaFetcher] 正在批量获取评分数据...")
        
        # 1. 预加载本地分数文件
        local_scores = self._load_local_scores()
        
        for movie in movies:
            movie_name = movie['name']
            douban_score = ""
            imdb_score = ""
            
            print(f"   🔍 正在查询: 《{movie_name}》")
            
            # --- 方案 A: 尝试从本地 JSON 获取 ---
            has_full_cache = False
            if self.use_local and movie_name in local_scores:
                local_data = local_scores[movie_name]
                # [核心修改] 满血判定：除了要包含 4 个键，且核心分数 (douban, imdb) 不能是 N/A
                has_all_keys = all(k in local_data for k in ("douban", "imdb", "rotten_tomatoes", "metacritic"))
                
                if has_all_keys:
                    if local_data.get("douban") == "N/A" or local_data.get("imdb") == "N/A":
                        has_full_cache = False
                        print(f"      🔄 本地缓存存在脏数据/未开分(N/A)，触发无限重试机制...")
                    else:
                        has_full_cache = True
            
            if has_full_cache:
                print(f"      📥 命中本地缓存 (local_scores.json 满血状态)")
                local_data = local_scores[movie_name]
                # 兼容处理：防呆，防止 JSON 里写了数字类型或 None
                douban_score = str(local_data.get('douban', '')).strip()
                imdb_score = str(local_data.get('imdb', '')).strip()
            
            # --- 方案 B: 降级调用网络 API 抓取 (增量补齐或全量抓取) ---
            else:
                if self.use_local and movie_name in local_scores:
                    print(f"      🌐 本地缓存未满血(存在缺失或N/A)，触发 API 抓取补齐...")
                elif self.use_local:
                    print(f"      🌐 本地缓存未命中，降级调用 API 网络抓取...")
                else:
                    print(f"      🌐 本地读取已关闭，直接调用 API 网络抓取...")
                    
                try:
                    # 调用原版的 fetch_all 逻辑获取元数据，它会自动处理局部缓存并保存新数据
                    api_data = self.api_fetcher.fetch_all(movie_name)
                    douban_score = str(api_data.get('douban', '')).strip()
                    imdb_score = str(api_data.get('imdb', '')).strip()
                except Exception as e:
                    # 【核心修改】拦截原版的异常熔断！合集模式必须保证后续电影能继续处理
                    print(f"      ⚠️ API 抓取异常或无数据 (已拦截): {e}")
            
            # --- 数据清洗与校验 ---
            # 统一处理无效值 (API 可能会返回 "N/A"，我们将其转为空，供下游视觉生成器判断)
            invalid_vals = {"N/A", "None", "null", "none", ""}
            
            if douban_score in invalid_vals:
                douban_score = ""
                print(f"      ⚠️ [警告] 电影《{movie_name}》未查到豆瓣分数，将在海报中隐藏该元素。")
            else:
                print(f"      ✅ 豆瓣: {douban_score}")
                
            if imdb_score in invalid_vals:
                imdb_score = ""
                print(f"      ⚠️ [警告] 电影《{movie_name}》未查到 IMDb 分数，将在海报中隐藏该元素。")
            else:
                print(f"      ✅ IMDb: {imdb_score}")
                
            # 将清洗后的分数回写到字典中
            movie['douban'] = douban_score
            movie['imdb'] = imdb_score
            
        return movies

    def _load_local_scores(self) -> dict:
        """安全读取本地 JSON 分数文件"""
        if not self.use_local:
            return {}
            
        if not os.path.exists(self.local_scores_file):
            print(f"   ℹ️ 本地分数文件不存在 ({self.local_scores_file})，本次将全部使用 API 抓取。")
            return {}
            
        try:
            with open(self.local_scores_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"   ⚠️ 读取 local_scores.json 失败 (JSON 格式错误?): {e}")
            print("   ℹ️ 自动降级：本次将全部使用 API 网络抓取。")
            return {}