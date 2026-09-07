import datetime
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
    - API 模式: TMDB -> Serper -> Gemini Grounding
    - Codex SDK 模式: TMDB -> OMDB -> Codex Live Web Search -> Serper 可选后备
    """

    CODEX_FACT_FIELDS = (
        "original_title",
        "original_language",
        "release_date",
        "release_region",
        "genres",
        "region",
        "director",
        "actors",
        "overview",
    )

    def __init__(self):
        self.llm_runtime = str(
            getattr(config.Strategy.System, "LLM_RUNTIME", "api")
        ).strip().lower()

        # 外部数据源鉴权
        self.tmdb_key = config.TMDB_API_KEY
        self.omdb_key = config.OMDB_API_KEY
        self.serper_key = config.SERPER_API_KEY or config.SEARCH_API_KEY
        # Codex SDK 模式严格绕过 Gemini Key 与调用链路。
        self.gemini_key = config.GEMINI_API_KEY if self.llm_runtime == "api" else None
        self.gemini_model = config.GEMINI_MODEL

        # 单片预算上限：严格受 config 控制，避免无限请求。
        self.max_serper_queries = max(
            0, int(getattr(config.Strategy.Preview, "SERPER_MAX_QUERIES_PER_MOVIE", 5))
        )
        self.max_codex_search_rounds = max(
            1,
            int(
                getattr(
                    config.Strategy.Preview,
                    "CODEX_MAX_SEARCH_ROUNDS_PER_MOVIE",
                    3,
                )
            ),
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
        self.codex_runtime = getattr(self.brain, "codex_runtime", None)

    def run(self, movies: list) -> list | None:
        """
        批量采集入口。

        规则:
        - API 与 Codex SDK 模式都在必填字段缺失时熔断整夹。
        - 只有非必填事实无法确认时，才保留电影并将字段留空。
        - 返回值是下游 writer/visual 可直接消费的“标准化电影字典列表”。
        """
        print("\n📊 [2/5 PreviewMetaFetcher] 正在采集新片元数据...")
        enriched = []

        for i, movie in enumerate(movies):
            movie_name = movie["name"]
            print(f"   🔍 ({i+1}/{len(movies)}) 处理: 《{movie_name}》")
            try:
                # 单片失败即整夹终止：preview 保持强一致，避免部分片目“半成品发布”。
                enriched.append(self.collect_one(movie))
            except Exception as e:
                print(f"   ⛔ [熔断] 《{movie_name}》元数据不完整: {e}")
                return None

        return enriched

    def collect_one(self, movie: dict, initial_data: dict | None = None) -> dict:
        """
        对外暴露的单部电影采集入口。

        initial_data 用于 Codex SDK 模式的缓存刷新：复用已有 hook/summary，
        但仍会执行本次运行要求的数据库读取和至少一轮实时联网核验。
        """
        return self._collect_for_one_movie(movie, initial_data=initial_data)

    def _collect_for_one_movie(
        self,
        movie: dict,
        initial_data: dict | None = None,
    ) -> dict:
        """
        单片采集总流程（按当前 LLM_RUNTIME 分流）:
        1) TMDB 结构化数据
        2) Codex SDK 模式追加 OMDB + 至少一轮原生联网核验；API 模式保留旧链路
        3) 仍缺字段时使用对应后备通道
        4) 缺噱头时再生成噱头
        5) 标准化后统一校验必填字段；其他未确认字段留空
        """
        name = movie["name"]
        lock_year = (movie.get("lock_year") or "").strip() or None
        lock_original_title = (movie.get("lock_original_title") or "").strip() or None

        result = {
            # 基础标识与文件路径（来自 topic 阶段）
            # 注意：这里先保留 path/index，是为了当前这次运行还能继续走视觉与排序。
            # 真正写入缓存前，会由 PreviewCacheManager 去掉这两个“运行时字段”。
            "name": name,
            "path": movie["path"],
            "index": movie["index"],
            "lock_year": lock_year,
            "lock_original_title": lock_original_title,
            "movie_key": movie.get("movie_key", ""),
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
            "imdb_id": "",
            "is_china_film": False,
            "sources": [],
            "unconfirmed_fields": [],
        }

        if isinstance(initial_data, dict):
            # 只复用昂贵的生成结果；旧事实字段不带入，避免无法重新确认时误用历史值。
            for generated_key in ["hook", "summary"]:
                if generated_key in initial_data:
                    result[generated_key] = initial_data.get(generated_key)

        # 1) TMDB 主通道：优先取结构化字段，稳定且成本低。
        tmdb_data = self._fetch_from_tmdb(name, lock_original_title, lock_year)
        self._merge_source_payload(result, tmdb_data)

        if self.llm_runtime == "codex_sdk":
            # 2A) Codex SDK 模式：OMDB 作为第二结构化数据源。
            omdb_data = self._fetch_from_omdb(
                name,
                lock_original_title,
                lock_year,
                result,
            )
            self._merge_source_payload(result, omdb_data)

            # 每部电影无论数据库字段是否齐全，都至少执行一次 Codex Live Web Search。
            self._collect_with_codex_web(
                name,
                lock_original_title,
                lock_year,
                result,
            )

            # Codex 多轮后硬字段仍缺失时，Serper 才作为可选后备；不会回退到 Gemini。
            hard_missing = self._collect_hard_missing_for_serper(result, lock_original_title)
            if hard_missing:
                print(
                    "      🔁 [Serper-Backup] Codex 搜索后仍有未确认字段，"
                    "尝试使用 Serper 片段补充。"
                )
                snippets = self._collect_serper_snippets(
                    name,
                    lock_original_title,
                    lock_year,
                    result=result,
                )
            else:
                snippets = []
        else:
            # 2B) API 模式：完整保留原有 Serper 搜索顺序与预算规则。
            snippets = self._collect_serper_snippets(
                name,
                lock_original_title,
                lock_year,
                result=result,
            )

        self._append_sources(
            result,
            [item.get("link", "") for item in snippets if isinstance(item, dict)],
        )
        # 透传给 writer 作为最终兜底生成 hook 的上下文，不在这里裁剪语义字段。
        # 这批 snippets 虽然不会直接发布到笔记里，但会影响 hook 生成质量，因此必须进缓存。
        result["hook_snippets"] = snippets[:8]

        # 3) Gemini Grounding 最终兜底：仅在仍有必填缺失时触发。
        if self.llm_runtime == "api" and self.max_gemini_grounding > 0 and self.gemini_key:
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
                gemini_fields = self._fetch_with_gemini(name, lock_original_title, lock_year, result)
                gemini_fields = self._log_valid_gemini_hook(gemini_fields, source="Gemini")
                self._merge_missing(result, gemini_fields)

        # 3.5) Gemini 专项补写噱头（非熔断路径）
        # 仅在 hook 仍无效时触发，失败不熔断，后续继续走本地兜底生成。
        if (
            self.llm_runtime == "api"
            and self.gemini_hook_attempts > 0
            and self.gemini_key
            and (not self._normalize_hook(result.get("hook", "")))
        ):
            for attempt in range(1, self.gemini_hook_attempts + 1):
                print(
                    f"      🌐 [Gemini-Hook] 第 {attempt}/{self.gemini_hook_attempts} 次尝试补写噱头..."
                )
                gemini_fields = self._fetch_with_gemini(name, lock_original_title, lock_year, result)
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
        # 两种运行模式共用同一发布底线：数据库与所有后备检索都结束后，
        # 上映日期、非中国电影原名、已开启简介块的源简介仍缺失时必须熔断。
        if missing_final:
            raise ValueError("缺少必填字段: " + ", ".join(missing_final))
        if self.llm_runtime == "codex_sdk":
            result["unconfirmed_fields"] = self._collect_codex_metadata_missing(result)
            if result["unconfirmed_fields"]:
                print(
                    "      ⚠️ [Codex-Web] 多轮搜索后仍未确认可选字段: "
                    + ", ".join(result["unconfirmed_fields"])
                    + "；保留电影并省略这些字段。"
                )
        if not result.get("hook"):
            print("      ⚠️ [Meta-Hook] 当前仍无合规噱头，将在 Writer 阶段执行最终兜底。")

        return result

    def _fetch_from_tmdb(
        self,
        movie_name: str,
        lock_original_title: str | None,
        lock_year: str | None,
    ) -> dict:
        """从 TMDB 拉取主数据（详情 + credits + release_dates）。"""
        if not self.tmdb_key:
            return {}

        try:
            tmdb_id = self._search_tmdb_movie_id(movie_name, lock_original_title, lock_year)
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
                "sources": [f"https://www.themoviedb.org/movie/{tmdb_id}"],
            }
        except Exception:
            return {}

    def _fetch_from_omdb(
        self,
        movie_name: str,
        lock_original_title: str | None,
        lock_year: str | None,
        current: dict,
    ) -> dict:
        """Codex SDK 模式的第二结构化数据源；失败时返回空字典。"""
        if not self.omdb_key:
            return {}

        query_title = (
            (lock_original_title or "").strip()
            or str(current.get("original_title") or "").strip()
            or movie_name
        )
        params = {
            "apikey": self.omdb_key,
            "t": query_title,
            "type": "movie",
            "plot": "full",
        }
        if lock_year:
            params["y"] = lock_year

        try:
            data = requests.get(
                "https://www.omdbapi.com/",
                params=params,
                timeout=10,
            ).json()
        except Exception:
            return {}

        if str(data.get("Response", "")).strip().lower() != "true":
            return {}

        imdb_id = self._clean_external_value(data.get("imdbID"))
        released = self._normalize_omdb_date(data.get("Released"))
        language = self._normalize_omdb_language(data.get("Language"))
        source_urls = []
        if imdb_id:
            source_urls.append(f"https://www.imdb.com/title/{imdb_id}/")

        return {
            "imdb_id": imdb_id,
            "original_title": self._clean_external_value(data.get("Title")),
            "original_language": language,
            "release_date": released,
            "genres": self._clean_external_value(data.get("Genre")),
            "region": self._clean_external_value(data.get("Country")),
            "director": self._clean_external_value(data.get("Director")),
            "actors": self._clean_external_value(data.get("Actors")),
            "overview": self._clean_external_value(data.get("Plot")),
            "sources": source_urls,
        }

    def _collect_with_codex_web(
        self,
        movie_name: str,
        lock_original_title: str | None,
        lock_year: str | None,
        result: dict,
    ):
        """使用单部电影专属线程进行一至三轮事实核验和字段补全。"""
        if self.codex_runtime is None:
            print("      ⚠️ [Codex-Web] Codex 运行时未初始化，跳过原生联网搜索。")
            return

        session = self.codex_runtime.create_preview_session(
            max_search_rounds=self.max_codex_search_rounds
        )
        any_web_search = False

        for round_index in range(1, self.max_codex_search_rounds + 1):
            missing_before = self._collect_codex_metadata_missing(result)
            prompt = self._build_codex_search_prompt(
                movie_name,
                lock_original_title,
                lock_year,
                result,
                missing_before,
                round_index,
            )
            try:
                turn = session.search_json(prompt, self._codex_search_output_schema())
            except Exception as exc:
                print(f"      ⚠️ [Codex-Web] 第 {round_index} 轮搜索失败: {exc}")
                break

            if not turn.web_search_used:
                print(
                    f"      ⚠️ [Codex-Web] 第 {round_index} 轮未检测到原生 Web Search 事件，"
                    "本轮结果不采纳。"
                )
                continue

            any_web_search = True
            source_urls = self._normalize_source_urls(turn.data.get("sources", []))
            if not source_urls:
                print(
                    f"      ⚠️ [Codex-Web] 第 {round_index} 轮没有返回可验证来源，"
                    "本轮事实字段不采纳。"
                )
                continue

            self._merge_codex_verified(result, turn.data)
            self._append_sources(result, source_urls)

            missing_after = self._collect_codex_metadata_missing(result)
            missing_text = "无" if not missing_after else "、".join(missing_after)
            print(
                f"      ✅ [Codex-Web] 第 {round_index}/{self.max_codex_search_rounds} 轮完成，"
                f"剩余未确认字段={missing_text}，来源={len(source_urls)} 条。"
            )
            if not missing_after:
                break

        if not any_web_search:
            print(
                "      ⚠️ [Codex-Web] 本电影未获得可验证的原生搜索结果；"
                "将继续尝试 Serper 后备，并在最后执行必填字段熔断校验。"
            )

    def _build_codex_search_prompt(
        self,
        movie_name: str,
        lock_original_title: str | None,
        lock_year: str | None,
        result: dict,
        missing_fields: list[str],
        round_index: int,
    ) -> str:
        current = {field: result.get(field, "") for field in self.CODEX_FACT_FIELDS}
        missing_text = "无；请核验现有字段是否存在冲突" if not missing_fields else ", ".join(missing_fields)
        return f"""
请对电影《{movie_name}》执行第 {round_index}/{self.max_codex_search_rounds} 轮实时联网事实核查。
你必须在本轮使用 Codex 原生 Live Web Search，不能只依赖模型记忆。

识别线索：
- 中文名：{movie_name}
- 原名线索：{lock_original_title or ""}
- 年份线索：{lock_year or ""}

当前结构化数据：
{json.dumps(current, ensure_ascii=False)}

本轮优先核查字段：{missing_text}

要求：
1) 核验当前字段；若权威来源证明当前值有冲突，返回纠正后的值。
2) release_date 必须输出 YYYY-MM-DD；无法确认到具体日期则留空。
3) release_region 必须与 release_date 对应，并使用中文国家/地区全称。
4) original_language 使用 ISO 639-1 两位小写代码；无法确认则留空。
5) genres、region、release_region 使用中文；actors 最多保留 5 位主要演员，多值字段使用 / 分隔。
6) overview 只写可由来源支持的剧情事实，不写推测或营销判断。
7) 每个非空事实都必须有 sources 中的 URL 支持；sources 只放直接来源网页。
8) 没有硬性域名白名单，但优先片方、发行方、院线等一手来源。
9) 无法确认的字段返回空字符串，严禁猜测或把“待定”写进字段。
"""

    def _codex_search_output_schema(self) -> dict:
        properties = {
            field: {"type": "string"}
            for field in self.CODEX_FACT_FIELDS
        }
        properties["sources"] = {
            "type": "array",
            "items": {"type": "string"},
        }
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": properties,
            "required": [*self.CODEX_FACT_FIELDS, "sources"],
        }

    def _collect_codex_metadata_missing(self, movie: dict) -> list[str]:
        """计算需要继续联网核查的事实字段。

        其中必填字段会在全部检索结束后由统一校验熔断；
        其他字段仍允许记入 unconfirmed_fields 并在发布时省略。
        """
        fields = list(self.CODEX_FACT_FIELDS)
        if self._is_china_film(
            movie.get("original_language", ""),
            movie.get("region", ""),
        ):
            fields.remove("original_title")

        missing = []
        for field in fields:
            value = movie.get(field, "")
            if field == "release_date":
                if not self._normalize_date(value):
                    missing.append(field)
            elif not self._clean_external_value(value):
                missing.append(field)
        return missing

    def _merge_codex_verified(self, target: dict, source: dict):
        """只合并有来源支持的 Codex 字段，并允许纠正结构化数据冲突。"""
        for field in self.CODEX_FACT_FIELDS:
            value = self._clean_external_value(source.get(field))
            if not value:
                continue
            if field == "release_date":
                value = self._normalize_date(value)
                if not value:
                    continue
            elif field == "original_language":
                value = value.lower()[:2]
            target[field] = value

    def _merge_source_payload(self, target: dict, source: dict):
        """合并结构化字段，同时把数据源链接收敛到统一 sources 列表。"""
        if not isinstance(source, dict):
            return
        payload = dict(source)
        source_urls = payload.pop("sources", [])
        self._merge_missing(target, payload)
        self._append_sources(target, source_urls)

    def _append_sources(self, target: dict, source_urls):
        current = target.setdefault("sources", [])
        for url in self._normalize_source_urls(source_urls):
            if url not in current:
                current.append(url)

    def _normalize_source_urls(self, source_urls) -> list[str]:
        if not isinstance(source_urls, list):
            return []
        normalized = []
        for raw in source_urls:
            url = str(raw or "").strip()
            try:
                parsed = urlparse(url)
            except Exception:
                continue
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                continue
            if url not in normalized:
                normalized.append(url)
        return normalized

    def _clean_external_value(self, raw) -> str:
        text = str(raw or "").strip()
        if text.lower() in {"n/a", "na", "none", "null", "unknown", "tbd"}:
            return ""
        if text in {"未知", "不详", "待定"}:
            return ""
        return text

    def _normalize_omdb_date(self, raw) -> str:
        text = self._clean_external_value(raw)
        if not text:
            return ""
        normalized = self._normalize_date(text)
        if normalized:
            return normalized
        try:
            return datetime.datetime.strptime(text, "%d %b %Y").strftime("%Y-%m-%d")
        except ValueError:
            return ""

    def _normalize_omdb_language(self, raw) -> str:
        first = self._clean_external_value(raw).split(",", 1)[0].strip().lower()
        language_map = {
            "chinese": "zh",
            "mandarin": "zh",
            "cantonese": "zh",
            "english": "en",
            "french": "fr",
            "german": "de",
            "italian": "it",
            "japanese": "ja",
            "korean": "ko",
            "spanish": "es",
        }
        return language_map.get(first, "")

    def _search_tmdb_movie_id(
        self,
        movie_name: str,
        lock_original_title: str | None,
        lock_year: str | None,
    ) -> int | None:
        """
        搜索 TMDB 电影 ID。
        优先顺序:
        1) lock_original_title（若提供）
        2) movie_name

        说明：
        - 若外部传入年份锁定，则会先带年份过滤搜索；
        - 若带年份未命中，再降级不带年份复活一次，避免年份线索写错导致全失效。
        """
        queries = []
        if lock_original_title:
            queries.append(lock_original_title)
        queries.append(movie_name)

        for query in queries:
            search_url = "https://api.themoviedb.org/3/search/movie"
            params = {"api_key": self.tmdb_key, "query": query, "language": "zh-CN"}
            if lock_year:
                params["primary_release_year"] = lock_year
            try:
                resp = requests.get(search_url, params=params, timeout=10).json()
            except Exception:
                continue

            results = resp.get("results", [])
            if not results and lock_year:
                try:
                    fallback_params = {"api_key": self.tmdb_key, "query": query, "language": "zh-CN"}
                    resp = requests.get(search_url, params=fallback_params, timeout=10).json()
                    results = resp.get("results", [])
                except Exception:
                    results = []
            if not results:
                continue

            if lock_original_title:
                # 锁定场景下优先精确匹配 original_title，避免重名误命中。
                lock_lower = lock_original_title.lower()
                for item in results:
                    item_year = str(item.get("release_date", "") or "").strip()[:4]
                    if str(item.get("original_title", "")).strip().lower() == lock_lower:
                        if lock_year and item_year and item_year != lock_year:
                            continue
                        return item.get("id")

            if lock_year:
                # 没有原名精确锚点时，优先挑年份一致的结果。
                for item in results:
                    item_year = str(item.get("release_date", "") or "").strip()[:4]
                    if item_year and item_year == lock_year and item.get("id"):
                        return item["id"]

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
        lock_year: str | None,
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

        queries = self._build_serper_queries(movie_name, lock_original_title, lock_year)
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

    def _build_serper_queries(
        self,
        movie_name: str,
        lock_original_title: str | None,
        lock_year: str | None,
    ) -> list:
        """构建 Serper 查询模板（尽量覆盖上映、演职员、简介等字段）。"""
        base_name = lock_original_title or movie_name
        year_suffix = f" {lock_year}" if lock_year else ""
        # Codex SDK 模式遵循已确认规则，不给后备搜索设置硬性域名白名单。
        use_domain_whitelist = self.llm_runtime == "api"
        domain_filter = (
            " OR ".join([f"site:{d}" for d in self.domain_whitelist])
            if use_domain_whitelist and self.domain_whitelist
            else ""
        )
        prefix = f"({domain_filter}) " if domain_filter else ""
        return [
            f"{prefix}{base_name}{year_suffix} imdb",
            f"{prefix}{base_name}{year_suffix} release date theatrical",
            f"{prefix}{movie_name}{year_suffix} 豆瓣 上映",
            f"{prefix}{base_name}{year_suffix} cast director",
            f"{prefix}{base_name}{year_suffix} plot overview",
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
        if self.llm_runtime == "codex_sdk":
            return True
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

    def _fetch_with_gemini(
        self,
        movie_name: str,
        lock_original_title: str | None,
        lock_year: str | None,
        current: dict,
    ) -> dict:
        """
        Gemini Google Grounding 兜底补齐。
        只负责补字段，不直接决定熔断；是否合格由最终校验统一判断。
        """
        prompt = f"""
你是电影信息抽取助手。请联网搜索并补齐电影信息。
电影中文名: {movie_name}
电影原名线索: {lock_original_title or ""}
电影年份线索: {lock_year or ""}

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
                print("      ✅ [Meta-Hook] 已生成合规噱头。")
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
            print(f"      ✅ [{source}] 已获得合规噱头。")
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
            "BE": "比利时",
            "NL": "荷兰",
            "IE": "爱尔兰",
            "NZ": "新西兰",
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
            "United States": "美国",
            "United States of America": "美国",
            "USA": "美国",
            "United Kingdom": "英国",
            "Belgium": "比利时",
            "Netherlands": "荷兰",
            "Ireland": "爱尔兰",
            "New Zealand": "新西兰",
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
