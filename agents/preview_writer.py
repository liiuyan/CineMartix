import random
import re

import config
from utils import LLMBrain, clean_tag, load_prompt_lines, load_prompt_text


PREVIEW_EMOJI_POOL = ["🆕", "🎬", "🍿", "📽️", "🎞️"]


class PreviewWriterAgent:
    """
    ✍️ 新片速递文案 Agent

    职责:
    1. 执行 preview 必填字段终检与熔断。
    2. 可选生成简介块（字数区间由 config 控制）。
    3. 组装正文与固定 tags。
    """

    def __init__(self):
        # 文案生成引擎（DeepSeek）
        self.brain = LLMBrain()

        # 展示开关
        self.show_summary = bool(getattr(config.Strategy.Preview, "SHOW_SUMMARY_BLOCK", True))
        self.show_cta = bool(getattr(config.Strategy.Preview, "SHOW_CTA", True))
        self.cta_text = str(getattr(config.Strategy.Preview, "CTA_TEXT", "")).strip()
        # 片单附加信息开关（默认 false；由 config 统一控制）
        self.show_list_release_date = bool(
            getattr(config.Strategy.Preview, "SHOW_LIST_RELEASE_DATE", False)
        )
        self.show_list_release_region = bool(
            getattr(config.Strategy.Preview, "SHOW_LIST_RELEASE_REGION", False)
        )
        self.show_list_genres = bool(
            getattr(config.Strategy.Preview, "SHOW_LIST_GENRES", False)
        )
        self.show_list_region = bool(
            getattr(config.Strategy.Preview, "SHOW_LIST_REGION", False)
        )

        # 噱头约束（与用户确认规则一致）
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

        # 简介约束（preview 双区间）：
        # 1) target: 给 AI 的生成目标区间
        # 2) validate: 重写触发/通过校验区间
        self.summary_target_min = int(config.Strategy.Preview.SUMMARY_TARGET_MIN_LEN)
        self.summary_target_max = int(config.Strategy.Preview.SUMMARY_TARGET_MAX_LEN)
        self.summary_min = int(config.Strategy.Preview.SUMMARY_MIN_LEN)
        self.summary_max = int(config.Strategy.Preview.SUMMARY_MAX_LEN)
        self.summary_retries = max(
            1, int(getattr(config.Strategy.Preview, "SUMMARY_REWRITE_RETRIES", 3))
        )

    def run(self, theme: str, title: str, movies: list) -> dict | None:
        """
        预览文案主流程:
        1) 必填字段终检
        2) 噱头修复/重写
        3) 可选简介改写（范围由 config 决定）
        4) 组装正文与 tags
        """
        print("\n✍️ [3/5 PreviewWriterAgent] 正在组装新片速递文案...")

        if len(title) > 20:
            print(f"   ⛔ [熔断] 标题超长: {len(title)}/20")
            return None

        for movie in movies:
            finalized = self.finalize_movie(movie)
            if not finalized:
                return None
            movie.update(finalized)

        note_data = self.build_note(theme, title, movies)
        if not note_data:
            return None

        print(f"   ✅ 新片速递正文生成完成: {len(note_data['content'])} 字")
        return {"note_data": note_data, "movies": movies}

    def finalize_movie(self, movie: dict) -> dict | None:
        """
        按“单部电影”完成 preview 写作链路。

        这个入口专门服务于新缓存流程：
        1. 先校验电影是否具备继续写作的最小事实集；
        2. 复用已有合规 hook/summary，避免重复调用模型；
        3. 只在缺失或不合规时才补写该电影。

        返回值语义：
        - 返回 dict：这部电影已经达到“可直接参与最终发布组装”的完整状态；
        - 返回 None：这部电影当前仍不完整，主流程应立即停止，且不要写入缓存。
        """
        movie_name = str(movie.get("name", "")).strip()
        if not self._validate_required_fields(movie):
            return None

        # 噱头最终修正：空值/超限/禁词 -> 重写；失败则熔断
        movie["hook"] = self._ensure_hook(movie)
        if not movie["hook"]:
            print(f"   ⛔ [熔断] 《{movie_name}》噱头生成失败")
            return None

        # 简介块开启时优先复用已有合规 summary，只有不合规时才重写。
        if self.show_summary:
            existing_summary = self._clean_plain_text(movie.get("summary", ""))
            if self._is_summary_length_valid(existing_summary):
                movie["summary"] = existing_summary
                print(f"      ✅ 《{movie_name}》复用已有合规简介: {len(existing_summary)}字")
            else:
                summary = self._rewrite_summary(movie_name, movie.get("overview", ""))
                if not summary:
                    print(f"   ⛔ [熔断] 《{movie_name}》简介改写未达标 ({self.summary_min}-{self.summary_max})")
                    return None
                movie["summary"] = summary
        else:
            movie["summary"] = ""

        # 给视觉层准备统一字段；这些字段命中缓存后也可直接复用。
        movie["poster_date"] = movie.get("release_date", "").replace("-", ".")
        movie["poster_title_en"] = movie.get("original_title", "")
        movie["poster_title_cn"] = f"《{movie_name}》"
        movie["poster_hook"] = movie["hook"]
        return movie

    def needs_meta_refresh(self, movie: dict) -> bool:
        """
        判断缓存电影是否缺少“当前配置下继续写作所需的基础事实集”。

        作用：
        - 支持“任务签名命中但设置变化”场景；
        - 若旧缓存缺 overview / release_date / original_title 等关键字段，只重查当前电影。

        典型场景：
        - 旧缓存建立时 SHOW_SUMMARY_BLOCK=False，因此没有 overview/summary；
        - 本次运行改成 SHOW_SUMMARY_BLOCK=True；
        - 这时任务签名仍然命中，但单片事实集不够，需要只重查这一部而不是整批失效。
        """
        name = str(movie.get("name", "")).strip()
        if not name:
            return True
        if not str(movie.get("release_date", "")).strip():
            return True

        is_china = bool(movie.get("is_china_film"))
        if (not is_china) and (not str(movie.get("original_title", "")).strip()):
            return True

        if self.show_summary and (not str(movie.get("overview", "")).strip()):
            return True
        return False

    def build_note(self, theme: str, title: str, movies: list) -> dict | None:
        """
        仅负责组装整篇笔记。

        说明：
        - 命中缓存后电影顺序可能变化，因此整篇 note_data 不能直接复用旧成品；
        - 这里始终基于“当前顺序的 movies”重新拼装 content/tags。
        - 也正因为如此，缓存真正复用的对象是“单部电影完整数据”，不是整篇正文字符串。
        """
        if len(title) > 20:
            print(f"   ⛔ [熔断] 标题超长: {len(title)}/20")
            return None
        return self._assemble_note(theme, title, movies)

    def _validate_required_fields(self, movie: dict) -> bool:
        """按已确认规则校验必填项；不通过直接返回 False。"""
        name = str(movie.get("name", "")).strip()
        release_date = str(movie.get("release_date", "")).strip()
        hook = str(movie.get("hook", "")).strip()

        if not name:
            print("   ⛔ [熔断] 电影名缺失")
            return False
        if not release_date:
            print(f"   ⛔ [熔断] 《{name}》上映日期缺失")
            return False

        is_china = bool(movie.get("is_china_film"))
        original_title = str(movie.get("original_title", "")).strip()
        # 非中国电影必须有原名；中国电影允许原名留空。
        if not is_china and not original_title:
            print(f"   ⛔ [熔断] 《{name}》非中国电影但原名缺失")
            return False

        if self.show_summary and not str(movie.get("overview", "")).strip():
            print(f"   ⛔ [熔断] 《{name}》简介源文本缺失 (SHOW_SUMMARY_BLOCK=True)")
            return False

        # hook 可在 _ensure_hook 中修复，不在这里直接熔断
        if not hook:
            print(f"   ⚠️ 《{name}》噱头缺失，尝试自动补写")
        return True

    def _ensure_hook(self, movie: dict) -> str:
        """
        保证噱头可用：
        - 先校验已有值
        - 不可用则按配置次数重试生成
        """
        current = self._normalize_hook(movie.get("hook", ""))
        if current:
            print("      ✅ [Writer-Hook] 复用已有合规噱头。")
            return current

        snippets = movie.get("hook_snippets", []) or []
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
4) 禁止出现：{",".join(self.hook_forbidden)}。
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
            candidate, reasons = self._validate_hook_candidate(raw or "")
            if candidate:
                print("      ✅ [Writer-Hook] 已生成合规噱头。")
                return candidate

            reason_text = "；".join(reasons) if reasons else "空内容"
            prev_text = self._clean_plain_text(raw or "")
            print(
                f"      ⚠️ [Writer-Hook] 第 {attempt}/{self.hook_retry_times} 次失败: {reason_text} "
                f"| 原输出: {prev_text or '(空)'}"
            )
            feedback_block = (
                f"上一版噱头：{prev_text or '(空)'}\n"
                f"不合格原因：{reason_text}"
            )

        return ""

    def _rewrite_summary(self, movie_name: str, overview: str) -> str:
        """
        简介改写并做严格长度校验。
        任何一次命中 [summary_min, summary_max] 即返回。
        全部重试失败返回空字符串，调用方据此触发整夹熔断。
        """
        source = str(overview or "").strip()
        if not source:
            return ""

        # 这里严格按配置次数重试；不是“尽力而为”，而是“达标才通过”。
        # [关键约束] 每次都基于“原始查询到的简介 source”重写，绝不基于上一轮 AI 文本扩写/缩写。
        length_hint = ""
        for i in range(self.summary_retries):
            attempt = i + 1
            if attempt > 1:
                print(f"      🔄 《{movie_name}》简介重写重试 {attempt}/{self.summary_retries}")

            prompt = f"""
请把以下电影简介改写成一段 {self.summary_target_min}-{self.summary_target_max} 字的中文简介。
电影名：{movie_name}
原简介：{source}

要求：
1) 必须是自然中文，不要分点，不要换行。
2) 只输出简介正文，不要加片名，不要加引号。
3) 只能基于“原简介”中的事实信息，不要编造新设定。
4) 优先命中目标区间 {self.summary_target_min}-{self.summary_target_max} 字；
   若无法精确命中，也必须落在校验区间 {self.summary_min}-{self.summary_max} 字。
{length_hint}
"""
            raw = self.brain.think(prompt, system_prompt="你是电影编辑，只返回简介正文。")
            if not raw:
                continue
            text = self._clean_plain_text(raw)
            current_len = len(text)
            if self.summary_min <= current_len <= self.summary_max:
                print(
                    f"      ✅ 《{movie_name}》简介重写成功: {current_len}字 "
                    f"(第 {attempt}/{self.summary_retries} 次)"
                )
                return text
            if current_len < self.summary_min:
                print(
                    f"      ⚠️ 《{movie_name}》简介不达标: {current_len}字 "
                    f"(校验{self.summary_min}-{self.summary_max}，目标{self.summary_target_min}-{self.summary_target_max})，"
                    f"尝试 {attempt}/{self.summary_retries}，下一轮要求更长。"
                )
                length_hint = (
                    f"5) 你上一版明显偏短。下一版请在不新增事实的前提下补充细节，"
                    f"优先写到 {self.summary_target_min}-{self.summary_target_max} 字，"
                    f"且至少达到 {self.summary_min} 字。"
                )
            else:
                print(
                    f"      ⚠️ 《{movie_name}》简介不达标: {current_len}字 "
                    f"(校验{self.summary_min}-{self.summary_max}，目标{self.summary_target_min}-{self.summary_target_max})，"
                    f"尝试 {attempt}/{self.summary_retries}，下一轮要求更短。"
                )
                length_hint = (
                    f"5) 你上一版明显偏长。下一版请压缩表达但保留核心信息，"
                    f"优先写到 {self.summary_target_min}-{self.summary_target_max} 字，"
                    f"并严格不超过 {self.summary_max} 字。"
                )
        return ""

    def _is_summary_length_valid(self, text: str) -> bool:
        """判断已有 summary 是否已落在 preview 校验区间内。"""
        if not text:
            return False
        return self.summary_min <= len(text) <= self.summary_max

    def _assemble_note(self, theme: str, title: str, movies: list) -> dict | None:
        """
        拼接 preview 正文与标签，并做发布长度熔断。

        正文结构:
        1) 片单
        2) (可选)每部简介
        3) (可选)CTA
        """
        emoji = random.choice(PREVIEW_EMOJI_POOL)
        list_lines = [f"{emoji}本期新片速递："]

        for i, movie in enumerate(movies):
            line = f"{i+1}️⃣{movie['name']}"
            extras = []
            if self.show_list_release_date and movie.get("release_date"):
                extras.append(f"上映 {movie['release_date']}")
            if self.show_list_release_region and movie.get("release_region"):
                extras.append(f"上映地 {movie['release_region']}")
            if self.show_list_genres and movie.get("genres"):
                extras.append(movie["genres"])
            if self.show_list_region and movie.get("region"):
                extras.append(movie["region"])
            if extras:
                line += f" ({' | '.join(extras)})"
            list_lines.append(line)

        sections = ["\n".join(list_lines)]

        if self.show_summary:
            summary_lines = []
            for movie in movies:
                summary_lines.append(f"《{movie['name']}》：{movie.get('summary', '')}")
            # 相邻电影简介之间显式空一行，提升正文可读性。
            sections.append("\n\n".join(summary_lines))

        if self.show_cta and self.cta_text:
            sections.append(self.cta_text)

        content = "\n\n".join([s for s in sections if s])

        tags = self._build_tags(movies)
        tags_str = " ".join([f"#{t}" for t in tags])
        total_len = len(content) + len(tags_str)
        # 与现有项目口径保持一致：正文 + tags <= 990
        if total_len > 990:
            print(f"   ⛔ [熔断] 正文+标签超长: {total_len}/990")
            return None

        return {"title": title, "content": content, "tags": tags}

    def _build_tags(self, movies: list) -> list:
        """
        标签规则:
        - 固定前三个业务标签
        - 再追加前 3 部电影的 clean_tag 结果（去重）
        """
        tags = ["新片速递", "红书宝藏片单", "电影推荐"]
        movie_tags = []
        for movie in movies:
            cleaned = clean_tag(movie.get("name", ""))
            if cleaned and cleaned not in movie_tags:
                movie_tags.append(cleaned)
            if len(movie_tags) >= 3:
                break
        tags.extend(movie_tags)
        return tags

    def _normalize_hook(self, raw: str) -> str:
        """统一清洗并做合法性判断。"""
        cleaned, _ = self._validate_hook_candidate(raw)
        return cleaned

    def _validate_hook_candidate(self, raw: str) -> tuple[str, list[str]]:
        """
        清洗并校验 hook 候选文本。
        规则：
        1) 句末 。 . , ， 会被剔除后再计数；
        2) 命中禁用词或长度不合规则判失败。
        """
        reasons = []
        text = self._clean_plain_text(raw)
        text = re.sub(r"[。.,，]+$", "", text).strip()
        if not text:
            reasons.append("空内容")
            return "", reasons

        hit_words = [word for word in self.hook_forbidden if word and word in text]
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

    def _clean_plain_text(self, raw: str) -> str:
        """清理引号/代码块/换行，得到纯文本一行字符串。"""
        text = str(raw or "").strip()
        text = text.replace("```", "").replace("`", "").strip()
        text = text.replace("“", "").replace("”", "").replace('"', "").strip()
        return text.replace("\n", "").strip()
