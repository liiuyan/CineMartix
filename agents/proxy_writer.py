import json
import re

import config
from utils import LLMBrain


class ProxyWriterAgent:
    """
    📝 代理模式文案 Agent。

    职责:
    1. 读取用户提供的 note.md。
    2. 基于标题与正文自动生成泛内容 tags。
    3. 输出 ExecutionAgent 需要的 {title, content, tags}。
    """

    def __init__(self):
        self.brain = None  # 懒加载 LLM；初始化失败时仍可走本地 tags 兜底。
        proxy_config = getattr(config.Strategy, "Proxy", None)
        self.tag_retries = int(getattr(proxy_config, "TAG_GENERATION_RETRIES", 2))
        self.max_tags = int(getattr(proxy_config, "MAX_TAGS", 8))
        self.max_tag_len = int(getattr(proxy_config, "MAX_TAG_LEN", 12))

    def run(self, note_path: str) -> dict | None:
        """读取 note.md，生成 tags，并执行发布前硬线校验。"""
        print("\n📝 [2/3 ProxyWriterAgent] 正在读取代理文案...")

        parsed = self._read_note(note_path)
        if not parsed:
            return None

        title, content = parsed
        tags = self._generate_tags(title, content)
        if not tags:
            print("   ⛔ [代理模式熔断] tags 生成失败，已停止发布。")
            return None

        note_data = {"title": title, "content": content, "tags": tags}
        if not self._validate_note_data(note_data):
            return None

        print(f"   ✅ 代理文案准备完成: 标题 {len(title)}/20，正文 {len(content)} 字，tags {len(tags)} 个")
        return note_data

    def _read_note(self, note_path: str) -> tuple[str, str] | None:
        """
        读取 note.md。

        协议:
        - 第 1 行为标题。
        - 第 2 行起为正文，保留内部换行，仅清理首尾空白。
        """
        try:
            with open(note_path, "r", encoding="utf-8") as f:
                raw_text = f.read()
        except Exception as e:
            print(f"   ⛔ [代理模式熔断] 读取 note.md 失败: {e}")
            return None

        lines = raw_text.splitlines()
        if not lines:
            print("   ⛔ [代理模式熔断] note.md 为空。")
            return None

        title = lines[0].strip().lstrip("\ufeff")
        content = "\n".join(lines[1:]).strip()

        if not title:
            print("   ⛔ [代理模式熔断] note.md 第一行标题不能为空。")
            return None
        if not content:
            print("   ⛔ [代理模式熔断] note.md 第二行起正文不能为空。")
            return None
        if len(title) > 20:
            print(f"   ⛔ [代理模式熔断] 标题长度超限: {len(title)}/20")
            return None

        return title, content

    def _generate_tags(self, title: str, content: str) -> list[str]:
        """优先使用 LLM 生成语义 tags，失败时回退到本地关键词兜底。"""
        prompt = self._build_tag_prompt(title, content)
        system_prompt = "你是小红书内容运营，只返回严格 JSON。"
        brain = self._get_brain()

        if brain:
            for attempt in range(1, self.tag_retries + 1):
                raw = brain.think(prompt, system_prompt=system_prompt)
                tags = self._parse_tags_response(raw)
                if tags:
                    print(f"   🏷️ LLM tags 生成成功: {tags}")
                    return tags
                print(f"   ⚠️ LLM tags 第 {attempt}/{self.tag_retries} 次生成失败，准备重试或兜底。")

        fallback_tags = self._build_fallback_tags(title, content)
        print(f"   🏷️ 已启用本地兜底 tags: {fallback_tags}")
        return fallback_tags

    def _get_brain(self):
        """安全获取 LLMBrain；失败时返回 None，让调用方走本地兜底。"""
        if self.brain:
            return self.brain
        try:
            self.brain = LLMBrain()
            return self.brain
        except Exception as e:
            print(f"   ⚠️ LLM 初始化失败，将使用本地 tags 兜底: {e}")
            return None

    def _build_tag_prompt(self, title: str, content: str) -> str:
        """构造 tags 生成 Prompt，正文截断只影响标签语义抽取，不改变最终发布正文。"""
        content_preview = content[:1200]
        return f"""
请根据下面的小红书标题和正文，生成 {self.max_tags} 个以内的中文 tags。

要求：
1. 只返回 JSON，不要解释。
2. JSON 格式必须是：{{"tags": ["tag1", "tag2"]}}
3. tag 不要带 #，不要包含空格。
4. tags 必须贴合标题和正文，不要强行加入电影、好物等固定领域标签。
5. 每个 tag 尽量不超过 {self.max_tag_len} 个字符。

标题：
{title}

正文：
{content_preview}
""".strip()

    def _parse_tags_response(self, raw: str | None) -> list[str]:
        """解析 LLM 返回的 JSON tags；不可解析时返回空列表触发重试/兜底。"""
        if not raw:
            return []

        text = raw.replace("```json", "").replace("```", "").strip()
        data = None
        for candidate in self._json_candidates(text):
            try:
                data = json.loads(candidate)
                break
            except Exception:
                continue

        if data is None:
            return []

        if isinstance(data, dict):
            raw_tags = data.get("tags", [])
        elif isinstance(data, list):
            raw_tags = data
        else:
            raw_tags = []

        return self._clean_tags(raw_tags)

    def _json_candidates(self, text: str) -> list[str]:
        """按可信度返回可能的 JSON 片段，兼容模型偶尔包一层解释文本。"""
        candidates = [text]
        object_match = re.search(r"\{.*\}", text, re.S)
        if object_match:
            candidates.append(object_match.group(0))
        list_match = re.search(r"\[.*\]", text, re.S)
        if list_match:
            candidates.append(list_match.group(0))
        return candidates

    def _clean_tags(self, raw_tags: list) -> list[str]:
        """统一清洗 tags：去 #、去空白、去重、截断过长项。"""
        tags = []
        for raw in raw_tags:
            tag = self._normalize_tag(str(raw))
            if not tag or tag in tags:
                continue
            tags.append(tag)
            if len(tags) >= self.max_tags:
                break
        return tags

    def _normalize_tag(self, raw: str) -> str:
        """把任意候选词清洗成小红书可用 tag。"""
        tag = raw.strip().lstrip("#").strip()
        tag = re.sub(r"\s+", "", tag)
        tag = tag.strip("，,。.!！?？；;：:、|/\\()（）[]【】《》\"'`")
        if not tag:
            return ""
        return tag[:self.max_tag_len]

    def _build_fallback_tags(self, title: str, content: str) -> list[str]:
        """本地关键词兜底：不依赖外部模型，也不注入电影固定标签。"""
        candidates = []
        title_tag = self._normalize_tag(title)
        if title_tag:
            candidates.append(title_tag)

        text = f"{title}\n{content}"
        # 只提取 ASCII 字母数字与 CJK 汉字，避免把标点、emoji 误塞进 tags。
        for token in re.findall(r"[A-Za-z0-9\u4e00-\u9fff]{2,20}", text):
            tag = self._normalize_tag(token)
            if tag and tag not in candidates:
                candidates.append(tag)
            if len(candidates) >= self.max_tags:
                break

        if not candidates:
            candidates.append("内容分享")  # 最后兜底，保证发布数据仍有 tags 字段。

        return candidates[:self.max_tags]

    def _validate_note_data(self, note_data: dict) -> bool:
        """沿用项目硬线：标题 <=20，正文 + tags <=990，超限直接熔断。"""
        title = note_data.get("title", "")
        content = note_data.get("content", "")
        tags = note_data.get("tags", [])
        tags_str = " ".join([f"#{tag}" for tag in tags])

        if len(title) > 20:
            print(f"   ⛔ [代理模式熔断] 标题长度超限: {len(title)}/20")
            return False

        total_len = len(content) + len(tags_str)
        if total_len > 990:
            print(f"   ⛔ [代理模式熔断] 正文+tags 超长: {total_len}/990")
            return False

        print(f"   [安全检查] 正文+tags 长度合规: {total_len}/990")
        return True
