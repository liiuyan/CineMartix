import random

import config
from utils import LLMBrain, clean_tag


PREVIEW_EMOJI_POOL = ["🆕", "🎬", "🍿", "📽️", "🎞️"]


class PreviewWriterAgent:
    """
    ✍️ 新片速递文案 Agent

    职责:
    1. 执行 preview 必填字段终检与熔断。
    2. 可选生成简介块 (55-80 字)。
    3. 组装正文与固定 tags。
    """

    def __init__(self):
        # 文案生成引擎（DeepSeek）
        self.brain = LLMBrain()

        # 展示开关
        self.show_summary = bool(getattr(config.Strategy.Preview, "SHOW_SUMMARY_BLOCK", True))
        self.show_cta = bool(getattr(config.Strategy.Preview, "SHOW_CTA", True))
        self.cta_text = str(getattr(config.Strategy.Preview, "CTA_TEXT", "")).strip()

        # 噱头约束（与用户确认规则一致）
        self.hook_min_len = int(getattr(config.Strategy.Preview, "HOOK_MIN_LEN", 6))
        self.hook_max_len = int(getattr(config.Strategy.Preview, "HOOK_MAX_LEN", 22))
        self.hook_forbidden = [
            str(x).strip()
            for x in getattr(config.Strategy.Preview, "HOOK_FORBIDDEN_WORDS", [])
            if str(x).strip()
        ]

        # 简介约束（SHOW_SUMMARY_BLOCK=True 时强校验）
        self.summary_min = int(getattr(config.Strategy.Preview, "SUMMARY_MIN_LEN", 55))
        self.summary_max = int(getattr(config.Strategy.Preview, "SUMMARY_MAX_LEN", 80))
        self.summary_retries = max(
            1, int(getattr(config.Strategy.Preview, "SUMMARY_REWRITE_RETRIES", 3))
        )

    def run(self, theme: str, title: str, movies: list) -> dict | None:
        """
        预览文案主流程:
        1) 必填字段终检
        2) 噱头修复/重写
        3) 可选简介改写(55-80)
        4) 组装正文与 tags
        """
        print("\n✍️ [3/5 PreviewWriterAgent] 正在组装新片速递文案...")

        if len(title) > 20:
            print(f"   ⛔ [熔断] 标题超长: {len(title)}/20")
            return None

        for movie in movies:
            # 先做规则层校验，任何失败都整夹熔断。
            if not self._validate_required_fields(movie):
                return None

            # 噱头最终修正：空值/超限/禁词 -> 重写；失败则熔断
            movie["hook"] = self._ensure_hook(movie)
            if not movie["hook"]:
                print(f"   ⛔ [熔断] 《{movie['name']}》噱头生成失败")
                return None

            # 简介块开启时：必须能改写到 55-80 字
            if self.show_summary:
                summary = self._rewrite_summary(movie["name"], movie.get("overview", ""))
                if not summary:
                    print(f"   ⛔ [熔断] 《{movie['name']}》简介改写未达标 ({self.summary_min}-{self.summary_max})")
                    return None
                movie["summary"] = summary
            else:
                movie["summary"] = ""

            # 给视觉层准备统一字段
            # preview_visual 只读取这些字段，不再重复推导。
            movie["poster_date"] = movie.get("release_date", "").replace("-", ".")
            movie["poster_title_en"] = movie.get("original_title", "")
            movie["poster_title_cn"] = f"《{movie['name']}》"
            movie["poster_hook"] = movie["hook"]

        note_data = self._assemble_note(theme, title, movies)
        if not note_data:
            return None

        print(f"   ✅ 新片速递正文生成完成: {len(note_data['content'])} 字")
        return {"note_data": note_data, "movies": movies}

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
        - 不可用则最多重写 3 次
        """
        current = self._normalize_hook(movie.get("hook", ""))
        if current:
            return current

        prompt = f"""
请为电影生成一句“新片速递噱头”。
电影名：{movie.get('name','')}
原名：{movie.get('original_title','')}
类型：{movie.get('genres','')}
导演：{movie.get('director','')}
主演：{movie.get('actors','')}
简介：{movie.get('overview','')}

要求：
1) 只输出一句中文短句。
2) 字数 {self.hook_min_len}-{self.hook_max_len}。
3) 禁止出现：{",".join(self.hook_forbidden)}。
"""
        for _ in range(3):
            raw = self.brain.think(prompt, system_prompt="你是电影宣发编辑，只输出一句话。")
            candidate = self._normalize_hook(raw or "")
            if candidate:
                return candidate
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

        prompt = f"""
请把以下电影简介改写成一段 {self.summary_min}-{self.summary_max} 字的中文简介。
电影名：{movie_name}
原简介：{source}

要求：
1) 必须是自然中文，不要分点，不要换行。
2) 只输出简介正文，不要加片名，不要加引号。
"""
        # 这里严格按配置次数重试；不是“尽力而为”，而是“达标才通过”。
        for i in range(self.summary_retries):
            if i > 0:
                print(f"      🔄 《{movie_name}》简介重写重试 {i+1}/{self.summary_retries}")
            raw = self.brain.think(prompt, system_prompt="你是电影编辑，只返回简介正文。")
            if not raw:
                continue
            text = self._clean_plain_text(raw)
            if self.summary_min <= len(text) <= self.summary_max:
                return text
        return ""

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
            if movie.get("release_date"):
                extras.append(f"上映 {movie['release_date']}")
            if movie.get("release_region"):
                extras.append(f"上映地 {movie['release_region']}")
            if movie.get("genres"):
                extras.append(movie["genres"])
            if movie.get("region"):
                extras.append(movie["region"])
            if extras:
                line += f" ({' | '.join(extras)})"
            list_lines.append(line)

        sections = ["\n".join(list_lines)]

        if self.show_summary:
            summary_lines = []
            for movie in movies:
                summary_lines.append(f"《{movie['name']}》：{movie.get('summary', '')}")
            sections.append("\n".join(summary_lines))

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
        text = self._clean_plain_text(raw)
        if not text:
            return ""
        if any(word in text for word in self.hook_forbidden):
            return ""
        if len(text) < self.hook_min_len or len(text) > self.hook_max_len:
            return ""
        return text

    def _clean_plain_text(self, raw: str) -> str:
        """清理引号/代码块/换行，得到纯文本一行字符串。"""
        text = str(raw or "").strip()
        text = text.replace("```", "").replace("`", "").strip()
        text = text.replace("“", "").replace("”", "").replace('"', "").strip()
        return text.replace("\n", "").strip()
