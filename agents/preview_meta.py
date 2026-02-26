import json
import re
from urllib.parse import urlparse

import requests

import config
from utils import LLMBrain, load_prompt_lines, load_prompt_text


class PreviewMetaFetcher:
    """
    🧭 新片速递数据采集 Agent

    采集链路:
    1) TMDB API 主通道
    2) Serper 搜索片段补齐
    3) Gemini Grounding 最终兜底
    """

    def __init__(self):
        # 外部数据源鉴权
        self.tmdb_key = config.TMDB_API_KEY
        self.serper_key = config.SERPER_API_KEY or config.SEARCH_API_KEY
        self.gemini_key = config.GEMINI_API_KEY
        self.gemini_model = config.GEMINI_MODEL

        # 单片预算上限：严格受 config 控制，避免无限请求。
        self.max_serper_queries = max(
            0, int(getattr(config.Strategy.Preview, "SERPER_MAX_QUERIES_PER_MOVIE", 5))
        )
        self.max_gemini_grounding = max(
            0, int(getattr(config.Strategy.Preview, "GEMINI_MAX_GROUNDING_PER_MOVIE", 3))
        )
        self.gemini_hook_attempts = max(
            0, int(getattr(config.Strategy.Preview, "GEMINI_HOOK_ATTEMPTS", 1))
        )
        self.show_summary_block = bool(
            getattr(config.Strategy.Preview, "SHOW_SUMMARY_BLOCK", True)
        )

        # 白名单只做“结果过滤”，可以避免低质量站点误命中。
        self.domain_whitelist = {
            d.strip().lower()
            for d in getattr(config.Strategy.Preview, "SERPER_DOMAIN_WHITELIST", [])
            if isinstance(d, str) and d.strip()
        }

        # 噱头约束用于字段校验与兜底重写。
        self.hook_min_len = int(getattr(config.Strategy.Preview, "HOOK_MIN_LEN", 6))
        self.hook_max_len = int(getattr(config.Strategy.Preview, "HOOK_MAX_LEN", 22))
        self.hook_retry_times = max(
            1, int(getattr(config.Strategy.Preview, "HOOK_RETRY_TIMES", 5))
        )
        # Prompt 语料从 prompts 目录读取；文件缺失会抛错并熔断流程。
        self.hook_forbidden = load_prompt_lines(
            "prompts/preview/hook_forbidden_words.txt"
        )
        self.hook_reference_examples = load_prompt_text(
            "prompts/preview/hook_reference_examples.txt"
        )

        self.brain = LLMBrain()

    def run(self, movies: list) -> list | None:
        """
        批量采集入口。

        规则:
        - 任何一部电影触发必填缺失，立即整夹熔断并返回 None。
        - 返回值是下游 writer/visual 可直接消费的“标准化电影字典列表”。
        """
        print("\n📊 [2/5 PreviewMetaFetcher] 正在采集新片元数据...")
        enriched = []

        for i, movie in enumerate(movies):
            movie_name = movie["name"]
            print(f"   🔍 ({i+1}/{len(movies)}) 处理: 《{movie_name}》")
            try:
                # 单片失败即整夹终止：preview 保持强一致，避免部分片目“半成品发布”。
                enriched.append(self._collect_for_one_movie(movie))
            except Exception as e:
                print(f"   ⛔ [熔断] 《{movie_name}》元数据不完整: {e}")
                return None

        return enriched

    def _collect_for_one_movie(self, movie: dict) -> dict:
        """
        单片采集总流程（按成本从低到高）:
        1) TMDB 结构化数据
        2) Serper 片段 + LLM抽取（满足“硬必填+类型”即提前停止）
        3) Gemini Grounding 兜底
        4) 缺噱头时再生成噱头
        5) 标准化 + 规则校验（不合格抛异常）
        """
        name = movie["name"]
        lock_original_title = (movie.get("lock_original_title") or "").strip() or None

        result = {
            # 基础标识与文件路径（来自 topic 阶段）
            "name": name,
            "path": movie["path"],
            "index": movie["index"],
            # 采集字段（逐步补齐）
            "original_title": "",
            "original_language": "",
            "release_date": "",
            "release_region": "",
            "genres": "",
            "region": "",
            "director": "",
            "actors": "",
            "overview": "",
            "hook": "",
            "hook_snippets": [],
            "tmdb_id": None,
            "is_china_film": False,
        }

        # 1) TMDB 主通道：优先取结构化字段，稳定且成本低。
        tmdb_data = self._fetch_from_tmdb(name, lock_original_title)
        self._merge_missing(result, tmdb_data)

        # 2) Serper 搜索补齐：先用便宜通道补缺。
        # 注意：_collect_serper_snippets 内部已实现“收齐即停”，不会盲目跑满预算。
        snippets = self._collect_serper_snippets(name, lock_original_title, result=result)
        # 透传给 writer 作为最终兜底生成 hook 的上下文，不在这里裁剪语义字段。
        result["hook_snippets"] = snippets[:8]

        # 3) Gemini Grounding 最终兜底：仅在仍有必填缺失时触发。
        if self.max_gemini_grounding > 0 and self.gemini_key:
            attempts = 0
            while attempts < self.max_gemini_grounding:
                missing = self._collect_required_missing(result, lock_original_title)
                # [策略] Gemini 仅补“硬必填”；hook 由后续 _generate_hookline 独立兜底。
                hard_missing = [x for x in missing if x != "hook"]
                if not hard_missing:
                    break
                attempts += 1
                print(
                    f"      🌐 [Gemini] 第 {attempts}/{self.max_gemini_grounding} 次联网补齐: 缺 {', '.join(hard_missing)}"
                )
                gemini_fields = self._fetch_with_gemini(name, lock_original_title, result)
                gemini_fields = self._log_valid_gemini_hook(gemini_fields, source="Gemini")
                self._merge_missing(result, gemini_fields)

        # 3.5) Gemini 专项补写噱头（非熔断路径）
        # 仅在 hook 仍无效时触发，失败不熔断，后续继续走本地兜底生成。
        if self.gemini_hook_attempts > 0 and self.gemini_key and (not self._normalize_hook(result.get("hook", ""))):
            for attempt in range(1, self.gemini_hook_attempts + 1):
                print(
                    f"      🌐 [Gemini-Hook] 第 {attempt}/{self.gemini_hook_attempts} 次尝试补写噱头..."
                )
                gemini_fields = self._fetch_with_gemini(name, lock_original_title, result)
                gemini_fields = self._log_valid_gemini_hook(gemini_fields, source="Gemini-Hook")
                self._merge_missing(result, gemini_fields)
                if self._normalize_hook(result.get("hook", "")):
                    print("      ✅ [Gemini-Hook] 噱头补写成功。")
                    break
            if not self._normalize_hook(result.get("hook", "")):
                print("      ⚠️ [Gemini-Hook] 补写未命中，将转入本地噱头兜底生成。")

        # 4) 噱头兜底：前面渠道都没有产出可用噱头时再生成。
        if not self._normalize_hook(result.get("hook", "")):
            result["hook"] = self._generate_hookline(result, snippets)

        # 5) 标准化：将“多源异构格式”统一成发布可用格式。
        result["release_date"] = self._normalize_date(result.get("release_date", ""))
        result["release_region"] = self._normalize_region_name(result.get("release_region", ""))
        result["region"] = self._normalize_region_list(result.get("region", ""))
        result["genres"] = self._normalize_sep_text(result.get("genres", ""))
        result["director"] = self._normalize_sep_text(result.get("director", ""))
        result["actors"] = self._normalize_sep_text(result.get("actors", ""))
        result["overview"] = str(result.get("overview", "")).strip()
        result["hook"] = self._normalize_hook(result.get("hook", ""))

        # 中国电影判定 + 原名规则：
        # - 中国电影原名允许留空
        # - 非中国电影原名必填（优先原始采集值，其次锁定值）
        result["is_china_film"] = self._is_china_film(
            result.get("original_language", ""), result.get("region", "")
        )
        if result["is_china_film"]:
            result["original_title"] = ""
        else:
            # 非中国电影：原名必填，优先英文原名，否则原始原名，否则外部锁定值
            result["original_title"] = (
                (result.get("original_title") or "").strip()
                or (lock_original_title or "").strip()
            )

        # 最终必填校验（meta 阶段）：
        # 为保证 writer 的 _ensure_hook 能执行，这里不因 hook 缺失提前熔断。
        missing_final = [
            x
            for x in self._collect_required_missing(result, lock_original_title)
            if x != "hook"
        ]
        if missing_final:
            raise ValueError("缺少必填字段: " + ", ".join(missing_final))
        if not result.get("hook"):
            print("      ⚠️ [Meta-Hook] 当前仍无合规噱头，将在 Writer 阶段执行最终兜底。")

        return result

    def _fetch_from_tmdb(self, movie_name: str, lock_original_title: str | None) -> dict:
        """从 TMDB 拉取主数据（详情 + credits + release_dates）。"""
        if not self.tmdb_key:
            return {}

        try:
            tmdb_id = self._search_tmdb_movie_id(movie_name, lock_original_title)
            if not tmdb_id:
                return {}

            url = f"https://api.themoviedb.org/3/movie/{tmdb_id}"
            params = {
                "api_key": self.tmdb_key,
                "language": "zh-CN",
                "append_to_response": "credits,release_dates",
            }
            data = requests.get(url, params=params, timeout=10).json()

            # 上映信息按“正式院线优先”规则计算，避免拿到节展日期。
            release_date, release_region = self._pick_tmdb_release(
                data.get("release_dates", {}).get("results", [])
            )

            genres = "/".join(
                [g.get("name", "").strip() for g in data.get("genres", []) if g.get("name")]
            )

            country_names = []
            for c in data.get("production_countries", []):
                name = c.get("name", "").strip()
                if name:
                    country_names.append(self._normalize_region_name(name))
            region = "/".join(self._dedup_keep_order(country_names))

            director = ""
            for crew in data.get("credits", {}).get("crew", []):
                if crew.get("job") == "Director":
                    director = crew.get("name", "").strip()
                    break

            cast_names = []
            for cast in data.get("credits", {}).get("cast", [])[:5]:
                cast_name = cast.get("name", "").strip()
                if cast_name:
                    cast_names.append(cast_name)
            actors = " / ".join(cast_names)

            return {
                "tmdb_id": tmdb_id,
                "name": data.get("title", movie_name).strip() or movie_name,
                "original_title": (data.get("original_title") or "").strip(),
                "original_language": (data.get("original_language") or "").strip().lower(),
                "release_date": release_date or (data.get("release_date") or ""),
                "release_region": release_region,
                "genres": genres,
                "region": region,
                "director": director,
                "actors": actors,
                "overview": (data.get("overview") or "").strip(),
            }
        except Exception:
            return {}

    def _search_tmdb_movie_id(self, movie_name: str, lock_original_title: str | None) -> int | None:
        """
        搜索 TMDB 电影 ID。
        优先顺序:
        1) lock_original_title（若提供）
        2) movie_name
        """
        queries = []
        if lock_original_title:
            queries.append(lock_original_title)
        queries.append(movie_name)

        for query in queries:
            search_url = "https://api.themoviedb.org/3/search/movie"
            params = {"api_key": self.tmdb_key, "query": query, "language": "zh-CN"}
            try:
                resp = requests.get(search_url, params=params, timeout=10).json()
            except Exception:
                continue

            results = resp.get("results", [])
            if not results:
                continue

            if lock_original_title:
                # 锁定场景下优先精确匹配 original_title，避免重名误命中。
                lock_lower = lock_original_title.lower()
                for item in results:
                    if str(item.get("original_title", "")).strip().lower() == lock_lower:
                        return item.get("id")

            top = results[0]
            if top.get("id"):
                return top["id"]

        return None

    def _pick_tmdb_release(self, release_results: list) -> tuple[str, str]:
        """
        从 TMDB release_dates 中挑选“主发布日期”。
        规则: 正式院线优先，type=3 > type=2 > type=1；每档取最早日期。
        """
        for target_type in [3, 2, 1]:
            candidates = []
            for country_block in release_results:
                region_code = (country_block.get("iso_3166_1") or "").strip().upper()
                for item in country_block.get("release_dates", []):
                    if item.get("type") != target_type:
                        continue
                    raw = str(item.get("release_date") or "").strip()
                    date = self._normalize_date(raw)
                    if date:
                        candidates.append((date, region_code))
            if candidates:
                candidates.sort(key=lambda x: x[0])
                date, code = candidates[0]
                return date, self._normalize_region_name(code)
        return "", ""

    def _collect_serper_snippets(
        self,
        movie_name: str,
        lock_original_title: str | None,
        result: dict | None = None,
    ) -> list:
        """
        执行 Serper 搜索并做域名白名单过滤，返回可用于抽取的片段列表。

        当传入 result 时：
        - 每次查询后都会尝试抽取并合并字段；
        - 若满足“硬必填(不含hook)+genres已收集”则提前停止；
        - genres 缺失不会熔断，只打印告警继续后续流程。
        """
        if not self.serper_key or self.max_serper_queries <= 0:
            return []

        queries = self._build_serper_queries(movie_name, lock_original_title)
        snippets = []
        used = 0
        genres_source = "TMDB" if result and self._has_collected_genres(result) else ""

        # 若 TMDB 阶段已满足“硬必填 + 类型”，直接跳过 Serper 以节省请求预算。
        if result is not None:
            hard_missing = self._collect_hard_missing_for_serper(result, lock_original_title)
            if not hard_missing and self._has_collected_genres(result):
                print("      ✅ [Serper] TMDB 已满足“硬必填+类型”，跳过 Serper 搜索。")
                return []

        for query in queries:
            if used >= self.max_serper_queries:
                break
            used += 1
            data = self._call_serper(query)
            new_snippets = []

            for item in data.get("organic", []):
                link = item.get("link", "")
                if not self._domain_allowed(link):
                    continue
                new_snippets.append(
                    {
                        "title": item.get("title", ""),
                        "snippet": item.get("snippet", ""),
                        "link": link,
                    }
                )

            if new_snippets:
                snippets.extend(new_snippets)

            # 增量抽取：每轮查询后都更新一次 result，以便触发“收齐即停”。
            if result is not None and snippets:
                had_genres_before = self._has_collected_genres(result)
                serper_fields = self._extract_from_snippets_with_llm(movie_name, snippets)
                self._merge_missing(result, serper_fields)
                has_genres_now = self._has_collected_genres(result)
                if (not had_genres_before) and has_genres_now and not genres_source:
                    genres_source = "Serper"

                hard_missing = self._collect_hard_missing_for_serper(result, lock_original_title)
                missing_str = "无" if not hard_missing else "、".join(hard_missing)
                genre_str = f"已就绪({genres_source or 'TMDB/Serper'})" if has_genres_now else "缺失"
                print(
                    f"      🔎 [Serper] 第 {used}/{self.max_serper_queries} 次后: "
                    f"硬必填缺失={missing_str} | 类型={genre_str}"
                )

                if not hard_missing and has_genres_now:
                    print(
                        f"      ✅ [Serper] 提前停止：第 {used}/{self.max_serper_queries} 次已满足“硬必填+类型”。"
                    )
                    break

        if snippets:
            print(f"      🔎 [Serper] 命中片段 {len(snippets)} 条")

        if result is not None and (not self._has_collected_genres(result)):
            print(
                f"      ⚠️ [Serper] 已达搜索上限 {used}/{self.max_serper_queries}，"
                f"电影类型仍缺失（非致命，继续流程）。"
            )

        return snippets

    def _collect_hard_missing_for_serper(self, movie: dict, lock_original_title: str | None) -> list:
        """
        Serper 提前停止判定使用的“硬必填”：
        - 基于统一必填规则
        - 排除 hook（噱头后续有独立补写链路）
        """
        missing = self._collect_required_missing(movie, lock_original_title)
        return [x for x in missing if x != "hook"]

    def _has_collected_genres(self, movie: dict) -> bool:
        """判断电影类型是否已收集到有效值。"""
        return bool(str(movie.get("genres") or "").strip())

    def _build_serper_queries(self, movie_name: str, lock_original_title: str | None) -> list:
        """构建 Serper 查询模板（尽量覆盖上映、演职员、简介等字段）。"""
        base_name = lock_original_title or movie_name
        domain_filter = " OR ".join([f"site:{d}" for d in self.domain_whitelist]) if self.domain_whitelist else ""
        prefix = f"({domain_filter}) " if domain_filter else ""
        return [
            f"{prefix}{base_name} imdb",
            f"{prefix}{base_name} release date theatrical",
            f"{prefix}{movie_name} 豆瓣 上映",
            f"{prefix}{base_name} cast director",
            f"{prefix}{base_name} plot overview",
        ]

    def _call_serper(self, query: str) -> dict:
        """单次 Serper 调用，失败返回空字典，避免中断主流程。"""
        try:
            url = "https://google.serper.dev/search"
            headers = {"X-API-KEY": self.serper_key, "Content-Type": "application/json"}
            payload = json.dumps({"q": query, "gl": "us", "num": 5})
            resp = requests.post(url, headers=headers, data=payload, timeout=12)
            return resp.json()
        except Exception:
            return {}

    def _domain_allowed(self, url: str) -> bool:
        """白名单判断：不在白名单域名内的结果直接丢弃。"""
        if not self.domain_whitelist:
            return True
        try:
            host = urlparse(url).netloc.lower()
            host = host[4:] if host.startswith("www.") else host
            return any(host == d or host.endswith("." + d) for d in self.domain_whitelist)
        except Exception:
            return False

    def _extract_from_snippets_with_llm(self, movie_name: str, snippets: list) -> dict:
        """将 Serper 片段交给 LLM 做结构化抽取。"""
        if not snippets:
            return {}
        context = []
        for s in snippets[:20]:
            context.append(
                f"Title: {s.get('title','')}\nSnippet: {s.get('snippet','')}\nURL: {s.get('link','')}"
            )

        prompt = f"""
        从以下搜索片段中提取电影《{movie_name}》信息，输出 JSON。
        只输出 JSON，不要解释。

        字段:
        {{
          "original_title": "",
          "release_date": "",
          "release_region": "",
          "genres": "",
          "region": "",
          "director": "",
          "actors": "",
          "overview": "",
          "hook": ""
        }}

        规则:
        1) release_date 必须为 YYYY-MM-DD，拿不到则空字符串。
        2) hook 为中文噱头短句，字数 {self.hook_min_len}-{self.hook_max_len}，
           且不含以下禁用词：{",".join(self.hook_forbidden)}。
        3) hook 句末的 。 . , ， 不计入字数，输出前请自行去掉句末标点。
        4) 不确定的字段返回空字符串。

        片段:
        {chr(10).join(context)}
        """

        try:
            raw = self.brain.think(prompt, system_prompt="你是电影信息抽取器，只返回JSON。")
            if not raw:
                return {}
            clean = raw.replace("```json", "").replace("```", "").strip()
            data = json.loads(clean)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _fetch_with_gemini(self, movie_name: str, lock_original_title: str | None, current: dict) -> dict:
        """
        Gemini Google Grounding 兜底补齐。
        只负责补字段，不直接决定熔断；是否合格由最终校验统一判断。
        """
        prompt = f"""
你是电影信息抽取助手。请联网搜索并补齐电影信息。
电影中文名: {movie_name}
电影原名线索: {lock_original_title or ""}

当前已知信息(JSON):
{json.dumps(current, ensure_ascii=False)}

请返回 JSON（仅JSON）:
{{
  "original_title": "",
  "release_date": "",
  "release_region": "",
  "genres": "",
  "region": "",
  "director": "",
  "actors": "",
  "overview": "",
  "hook": ""
}}

要求:
1) release_date 输出 YYYY-MM-DD。
2) hook 输出 {self.hook_min_len}-{self.hook_max_len} 字中文短句，
   禁用词：{",".join(self.hook_forbidden)}。
3) hook 句末的 。 . , ， 不计入字数，输出前请去掉句末标点。
4) 不确定则留空。
"""
        try:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{self.gemini_model}:generateContent"
            )
            headers = {"Content-Type": "application/json", "X-goog-api-key": self.gemini_key}
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "tools": [{"google_search": {}}],
                "generationConfig": {"temperature": 0.1},
            }
            resp = requests.post(url, headers=headers, json=payload, timeout=20)
            data = resp.json()

            text = ""
            for cand in data.get("candidates", []):
                content = cand.get("content", {})
                for part in content.get("parts", []):
                    if "text" in part and part["text"]:
                        text = part["text"]
                        break
                if text:
                    break

            if not text:
                return {}
            clean = text.replace("```json", "").replace("```", "").strip()
            parsed = json.loads(clean)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    def _generate_hookline(self, movie: dict, snippets: list) -> str:
        """
        在已有事实基础上生成噱头（带失败原因反馈重试）。

        约束:
        1) 句末 。 . , ， 在计数前会剔除，不计入长度。
        2) 必须通过清洗校验才算成功。
        """
        snippet_text = ""
        if snippets:
            snippet_text = "\n".join(
                [f"- {s.get('title','')} | {s.get('snippet','')}" for s in snippets[:8]]
            )

        base_prompt = f"""
请基于以下电影信息，先挑选出其中 1-2 个你认为最有噱头的点，再生成一句“新片速递噱头”。
电影名：{movie.get('name','')}
原名：{movie.get('original_title','')}
类型：{movie.get('genres','')}
导演：{movie.get('director','')}
主演：{movie.get('actors','')}
简介：{movie.get('overview','')}
补充片段：
{snippet_text}

参考示例（原文保留，不可删除或简化，不要原句照抄）：
{self.hook_reference_examples}

硬性要求：
1) 只输出一句中文短句。
2) 清洗后字数必须在 {self.hook_min_len}-{self.hook_max_len}。
3) 句末的 。 . , ， 不计入字数（并需在最终结果里去掉）。
4) 禁用词：{",".join(self.hook_forbidden)}。
5) 禁止输出任何解释、前后缀、编号。
6) 内容只围绕你选出的 1-2 个噱头点，禁止把多条信息硬拼在一句里。
"""

        feedback_block = ""
        for attempt in range(1, self.hook_retry_times + 1):
            prompt = base_prompt
            if feedback_block:
                prompt += (
                    "\n\n【上一次结果不合格，必须修正后重写】\n"
                    f"{feedback_block}\n"
                    "请严格按上方硬性要求重写，仅输出一句噱头。"
                )

            raw = self.brain.think(prompt, system_prompt="你是电影宣发编辑，只输出一句话。")
            cleaned, reasons = self._validate_hook_candidate(raw or "")
            if cleaned:
                print(f"      ✅ [Meta-Hook] 合规噱头: {cleaned}")
                return cleaned

            reason_text = "；".join(reasons) if reasons else "空内容"
            prev_text = self._clean_hook_raw(raw or "")
            print(
                f"      ⚠️ [Meta-Hook] 第 {attempt}/{self.hook_retry_times} 次失败: {reason_text} "
                f"| 原输出: {prev_text or '(空)'}"
            )
            feedback_block = (
                f"上一版噱头：{prev_text or '(空)'}\n"
                f"不合格原因：{reason_text}"
            )

        return ""

    def _collect_required_missing(self, movie: dict, lock_original_title: str | None) -> list:
        """
        计算当前电影缺失的“必填字段”。
        必填规则与用户确认保持一致：
        - 电影名
        - 上映日期
        - 噱头
        - 非中国电影的原名
        - SHOW_SUMMARY_BLOCK=True 时的简介
        """
        missing = []
        if not (movie.get("name") or "").strip():
            missing.append("movie_name")
        if not self._normalize_date(movie.get("release_date", "")):
            missing.append("release_date")
        if not self._normalize_hook(movie.get("hook", "")):
            missing.append("hook")

        is_china = self._is_china_film(
            movie.get("original_language", ""), movie.get("region", "")
        )
        if not is_china:
            original_title = (movie.get("original_title") or "").strip() or (lock_original_title or "").strip()
            if not original_title:
                missing.append("original_title")

        if self.show_summary_block and not (movie.get("overview") or "").strip():
            missing.append("overview")

        return self._dedup_keep_order(missing)

    def _merge_missing(self, target: dict, source: dict):
        """
        合并策略:
        - 默认只填充空字段
        - 对 release_date/hook 允许“有效值覆盖无效值”
        """
        if not source:
            return
        for k, v in source.items():
            if v is None:
                continue
            if isinstance(v, str):
                value = v.strip()
                if not value:
                    continue
            else:
                value = v
            current = target.get(k)
            if not current:
                target[k] = value
                continue

            # 若当前值存在但无效，允许更高质量的新值覆盖
            if k == "release_date":
                if not self._normalize_date(str(current)) and self._normalize_date(str(value)):
                    target[k] = value
            elif k == "hook":
                if not self._normalize_hook(str(current)) and self._normalize_hook(str(value)):
                    target[k] = value

    def _log_valid_gemini_hook(self, fields: dict, source: str) -> dict:
        """
        仅在 Gemini 返回的 hook 通过校验时打印日志。
        失败场景不打印，避免日志噪音。
        """
        if not isinstance(fields, dict):
            return {}

        if "hook" not in fields:
            return fields

        cleaned, _ = self._validate_hook_candidate(fields.get("hook", ""))
        if cleaned:
            fields["hook"] = cleaned
            print(f"      ✅ [{source}] 合规噱头: {cleaned}")
        else:
            # 保证无效 hook 不参与后续合并
            fields["hook"] = ""
        return fields

    def _normalize_date(self, raw: str) -> str:
        """日期标准化为 YYYY-MM-DD；无法识别则返回空字符串。"""
        if not raw:
            return ""
        text = str(raw).strip()
        if len(text) >= 10 and re.match(r"^\d{4}-\d{2}-\d{2}", text):
            return text[:10]

        m = re.search(r"(\d{4})[./年\-](\d{1,2})[./月\-](\d{1,2})", text)
        if not m:
            return ""
        y, mo, d = m.groups()
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"

    def _normalize_hook(self, raw: str) -> str:
        """统一清洗并校验 hook；不合格返回空字符串。"""
        cleaned, _ = self._validate_hook_candidate(raw)
        return cleaned

    def _validate_hook_candidate(self, raw: str) -> tuple[str, list[str]]:
        """清洗并校验 hook，返回 (cleaned_hook, reasons)。"""
        reasons = []
        text = self._clean_hook_raw(raw)
        text = re.sub(r"[。.,，]+$", "", text).strip()

        if not text:
            reasons.append("空内容")
            return "", reasons

        hit_words = [w for w in self.hook_forbidden if w and w in text]
        if hit_words:
            reasons.append("命中禁用词: " + ",".join(hit_words))

        text_len = len(text)
        if text_len < self.hook_min_len or text_len > self.hook_max_len:
            reasons.append(
                f"长度不合规: {text_len}（要求 {self.hook_min_len}-{self.hook_max_len}）"
            )

        if reasons:
            return "", reasons
        return text, []

    def _clean_hook_raw(self, raw: str) -> str:
        """基础清洗：去代码块、引号与换行。"""
        text = str(raw or "").strip()
        text = text.replace("```", "").replace("`", "").strip()
        text = text.replace("“", "").replace("”", "").replace('"', "").strip()
        return text.replace("\n", "").strip()

    def _normalize_region_name(self, raw: str) -> str:
        """地区名标准化：支持 ISO 两位码，并统一港澳台命名。"""
        name = str(raw or "").strip()
        if not name:
            return ""

        # code -> 中文名
        code_map = {
            "CN": "中国",
            "HK": "中国香港",
            "MO": "中国澳门",
            "TW": "中国台湾",
            "US": "美国",
            "GB": "英国",
            "JP": "日本",
            "KR": "韩国",
            "FR": "法国",
            "DE": "德国",
            "IT": "意大利",
            "ES": "西班牙",
            "CA": "加拿大",
            "AU": "澳大利亚",
            "IN": "印度",
        }
        upper = name.upper()
        if len(upper) == 2 and upper in code_map:
            return code_map[upper]

        replace_map = {
            "Hong Kong": "中国香港",
            "香港": "中国香港",
            "Taiwan": "中国台湾",
            "台湾": "中国台湾",
            "Macau": "中国澳门",
            "Macao": "中国澳门",
            "澳门": "中国澳门",
            "China": "中国",
        }
        return replace_map.get(name, name)

    def _normalize_region_list(self, raw: str) -> str:
        """将多分隔符地区列表归一化为 a/b/c 格式。"""
        text = str(raw or "").strip()
        if not text:
            return ""
        parts = re.split(r"[、,/|]+", text)
        normalized = []
        for p in parts:
            p = p.strip()
            if not p:
                continue
            normalized.append(self._normalize_region_name(p))
        normalized = self._dedup_keep_order(normalized)
        return "/".join(normalized)

    def _normalize_sep_text(self, raw: str, sep: str = "/") -> str:
        """将人物/类型等多值文本归一化，并做去重。"""
        text = str(raw or "").strip()
        if not text:
            return ""
        parts = [p.strip() for p in re.split(r"[、,/|]+", text) if p.strip()]
        return f" {sep} ".join(self._dedup_keep_order(parts))

    def _is_china_film(self, original_language: str, region_text: str) -> bool:
        """中国电影判定：语言为 zh 或地区包含中国相关标记。"""
        lang = str(original_language or "").strip().lower()
        region = str(region_text or "")
        if lang == "zh":
            return True
        china_markers = ["中国", "中国香港", "中国澳门", "中国台湾"]
        return any(x in region for x in china_markers)

    def _dedup_keep_order(self, items: list) -> list:
        """去重并保持原顺序。"""
        out = []
        for item in items:
            if item not in out:
                out.append(item)
        return out
