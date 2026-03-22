# 文件名: agents/collection_meta.py
import config
from agents.meta import MetaFetcher

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
        # [重构 板块8] 删除 self.local_scores_file — 文件路径由 MetaFetcher 统一持有
        self.use_local = getattr(config.Strategy.System, 'USE_LOCAL_SCORES', True)
        self.api_fetcher = MetaFetcher()
        # 封面英文水印与片单扩展字段都依赖 fetch_all 返回的元数据。
        self.need_cover_meta = bool(
            getattr(config.Strategy.Visual, 'COLLECTION_COVER_SHOW_ENGLISH_NAMES', False)
        )
        self.need_display_meta = any(
            bool(getattr(config.Strategy.Writer, attr, False))
            for attr in ('SHOW_YEAR', 'SHOW_GENRE', 'SHOW_REGION')
        )

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
            lock_year = str(movie.get('lock_year') or "").strip() or None
            lock_original_title = str(movie.get('lock_original_title') or "").strip() or None
            cache_key = self._build_cache_key(movie_name, lock_year, lock_original_title)  # [本次新增] 重名电影使用独立缓存键

            douban_score = ""
            imdb_score = ""
            rotten_tomatoes_score = ""  # [本次新增] 合集片单可选展示烂番茄评分
            api_data = {}
            
            lock_log = ""
            if lock_year:
                lock_log = f" | 年份锁定: {lock_year}"
            elif lock_original_title:
                lock_log = f" | 原名锁定: {lock_original_title}"
            print(f"   🔍 正在查询: 《{movie_name}》{lock_log}")
            
            # --- 方案 A: 尝试从本地 JSON 获取 ---
            has_full_cache = False
            if self.use_local and cache_key in local_scores:
                local_data = local_scores[cache_key]
                # [核心修改] 满血判定：除了要包含 4 个键，且核心分数 (douban, imdb) 不能是 N/A
                # 目的：避免“命中缓存但数据无效”导致永久不触发网络补齐。
                has_all_keys = all(k in local_data for k in ("douban", "imdb", "rotten_tomatoes", "metacritic"))
                
                if has_all_keys:
                    if local_data.get("douban") == "N/A" or local_data.get("imdb") == "N/A":
                        has_full_cache = False
                        print(f"      🔄 本地缓存存在脏数据/未开分(N/A)，触发无限重试机制...")
                    else:
                        has_full_cache = True
            
            if has_full_cache:
                print(f"      📥 命中本地缓存 (local_scores.json 满血状态)")
                local_data = local_scores[cache_key]
                # 兼容处理：防呆，防止 JSON 里写了数字类型或 None
                douban_score = str(local_data.get('douban', '')).strip()
                imdb_score = str(local_data.get('imdb', '')).strip()
                rotten_tomatoes_score = str(local_data.get('rotten_tomatoes', '')).strip()
                # 分数可直接走缓存，但封面英文水印/片单扩展字段仍需补齐元数据。
                if self.need_cover_meta or self.need_display_meta:
                    try:
                        api_data = self.api_fetcher.fetch_all(
                            movie_name,
                            specific_year=lock_year,
                            specific_original_title=lock_original_title,
                            cache_key=cache_key
                        )
                    except Exception as e:
                        print(f"      ⚠️ 元数据补齐失败 (已拦截): {e}")
            
            # --- 方案 B: 降级调用网络 API 抓取 (增量补齐或全量抓取) ---
            else:
                if self.use_local and cache_key in local_scores:
                    print(f"      🌐 本地缓存未满血(存在缺失或N/A)，触发 API 抓取补齐...")
                elif self.use_local:
                    print(f"      🌐 本地缓存未命中，降级调用 API 网络抓取...")
                else:
                    print(f"      🌐 本地读取已关闭，直接调用 API 网络抓取...")
                    
                try:
                    # 调用原版的 fetch_all 逻辑获取元数据，它会自动处理局部缓存并保存新数据
                    api_data = self.api_fetcher.fetch_all(
                        movie_name,
                        specific_year=lock_year,
                        specific_original_title=lock_original_title,
                        cache_key=cache_key
                    )
                    douban_score = str(api_data.get('douban', '')).strip()
                    imdb_score = str(api_data.get('imdb', '')).strip()
                    rotten_tomatoes_score = str(api_data.get('rotten_tomatoes', '')).strip()
                except Exception as e:
                    # 【核心修改】拦截原版的异常熔断！合集模式必须保证后续电影能继续处理
                    # 语义：单片失败只影响当前项，不应拖垮整夹任务。
                    print(f"      ⚠️ API 抓取异常或无数据 (已拦截): {e}")

            if api_data:
                # 统一在这里回写，保证“缓存命中”和“API 抓取”两条路径产出的字段口径一致。
                movie['year'] = str(api_data.get('year', movie.get('year', ''))).strip()
                movie['genres'] = str(api_data.get('genres', movie.get('genres', ''))).strip()
                movie['region'] = str(api_data.get('region', movie.get('region', ''))).strip()
                movie['original_title'] = str(api_data.get('original_title', '')).strip()
                movie['is_china_film'] = bool(api_data.get('is_china_film', False))

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

            if rotten_tomatoes_score in invalid_vals:
                rotten_tomatoes_score = ""
                print(f"      ⚠️ [警告] 电影《{movie_name}》未查到烂番茄分数，将在片单中隐藏该元素。")
            else:
                print(f"      ✅ 烂番茄: {rotten_tomatoes_score}")
                
            # 将清洗后的分数回写到字典中
            movie['douban'] = douban_score
            movie['imdb'] = imdb_score
            movie['rotten_tomatoes'] = rotten_tomatoes_score

            # [本次新增] 若外部锁定的是年份，兜底写回 year，确保 SHOW_YEAR 打开时可显示
            if lock_year and not movie.get('year'):
                movie['year'] = lock_year
            
        return movies

    def _build_cache_key(self, movie_name: str, lock_year: str | None, lock_original_title: str | None) -> str:
        """
        为合集模式生成缓存键：
        - 默认: 电影名
        - 年份锁定: 电影名｜年份
        - 原名锁定: 电影名｜原名
        """
        if lock_year:
            return f"{movie_name}｜{lock_year}"
        if lock_original_title:
            return f"{movie_name}｜{lock_original_title}"
        return movie_name

    def _load_local_scores(self) -> dict:
        """
        [重构 板块8] 委托 MetaFetcher 读取本地缓存，消除重复的文件 I/O。
        本类仅保留 use_local 开关判断，实际文件读取由 MetaFetcher 统一执行。
        """
        if not self.use_local:
            return {}
        
        scores = self.api_fetcher._load_local_scores()
        if not scores:
            print(f"   ℹ️ 本地分数文件为空或不存在，本次将全部使用 API 抓取。")
        return scores
