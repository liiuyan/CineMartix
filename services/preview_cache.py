import copy
import datetime
import json
import os

import config


class PreviewCacheManager:
    """
    📦 preview 临时缓存管理器

    设计目标：
    1. 仅按任务维度缓存 preview 最近 N 次任务（默认 5 次）。
    2. 任务内部按“单部电影完整完成”即时写入，避免整批熔断导致前功尽弃。
    3. 匹配规则只认：run_mode + sub_mode + theme + title + movie_keys(忽略顺序但保留重复计数)。

    缓存结构（JSON）：
    {
      "tasks": [
        {
          "run_mode": "preview",
          "sub_mode": "landscape|poster",
          "theme": "...",
          "title": "...",
          "movie_keys": ["电影A｜year｜2026", "电影B｜original｜Contratiempo"],
          "movies": {
            "电影A｜year｜2026": {
              "completed": true,
              "completed_at": "...",
              "data": { ... 单部电影完整可复用字段 ... }
            }
          },
          "updated_at": "..."
        }
      ]
    }

    说明：
    - movie_keys 用于“认任务”，不用于取具体电影数据；
    - movies 用于“按 movie_key 取单部电影完整缓存”；
    - 任务一旦命中，仍要按当前顺序重组整篇 note_data，不能直接复用旧正文成品。
    """

    def __init__(self):
        self.cache_file = config.PREVIEW_CACHE_FILE
        self.max_tasks = max(
            1, int(getattr(config.Strategy.Preview, "PREVIEW_CACHE_MAX_TASKS", 5))
        )
        self.payload = self._load()

    def _load(self) -> dict:
        """安全读取缓存文件；损坏时回退为空结构，避免阻断主流程。"""
        if not os.path.exists(self.cache_file):
            return {"tasks": []}

        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("tasks"), list):
                return data
        except Exception as e:
            print(f"   ⚠️ [PreviewCache] 读取缓存失败，已回退为空缓存: {e}")
        return {"tasks": []}

    def _save(self):
        """落盘缓存 JSON。"""
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self.payload, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"   ⚠️ [PreviewCache] 写入缓存失败: {e}")

    def _now_iso(self) -> str:
        """统一时间戳格式，供 LRU 淘汰与排查使用。"""
        return datetime.datetime.now().isoformat(timespec="seconds")

    def _build_signature(self, topic_data: dict) -> dict:
        """
        构建任务签名。

        说明：
        - movie_keys 采用排序后的列表而不是 set，顺序变化不影响匹配；
        - 但若完全相同的 movie_key 出现两次，重复计数仍会保留。
        """
        movie_keys = sorted(
            [str(m.get("movie_key", "")).strip() for m in topic_data.get("movies", []) if str(m.get("movie_key", "")).strip()]
        )
        return {
            "run_mode": "preview",
            "sub_mode": str(topic_data.get("sub_mode", "")).strip(),
            "theme": str(topic_data.get("theme", "")).strip(),
            "title": str(topic_data.get("title", "")).strip(),
            "movie_keys": movie_keys,
        }

    def _find_task(self, topic_data: dict) -> dict | None:
        """
        按签名查找匹配的缓存任务。

        这里故意不看电影顺序，只比较排序后的 movie_keys。
        原因：用户允许调整同一批电影的顺序；顺序变化不应导致缓存完全失效。
        """
        signature = self._build_signature(topic_data)
        for task in self.payload.get("tasks", []):
            if (
                task.get("run_mode") == signature["run_mode"]
                and task.get("sub_mode") == signature["sub_mode"]
                and task.get("theme") == signature["theme"]
                and task.get("title") == signature["title"]
                and task.get("movie_keys") == signature["movie_keys"]
            ):
                return task
        return None

    def get_task(self, topic_data: dict) -> dict | None:
        """返回当前任务命中的缓存任务（只读语义）。"""
        return self._find_task(topic_data)

    def count_completed_movies(self, topic_data: dict) -> int:
        """统计当前任务已缓存完成的电影数量，用于日志提示。"""
        task = self._find_task(topic_data)
        if not task:
            return 0
        return len(task.get("movies", {}))

    def get_cached_movie(self, topic_data: dict, movie_key: str) -> dict | None:
        """
        读取指定电影的完整缓存；不存在或不完整则返回 None。

        只有 completed=True 的电影才允许复用。
        这样可以保证：
        - 已缓存电影一定是“元数据 + hook + summary(若需要)”都完成的完整状态；
        - 半成品电影不会污染下一次运行。
        """
        task = self._find_task(topic_data)
        if not task:
            return None

        movie_item = task.get("movies", {}).get(movie_key)
        if not isinstance(movie_item, dict):
            return None
        if not bool(movie_item.get("completed")):
            return None

        data = movie_item.get("data")
        return copy.deepcopy(data) if isinstance(data, dict) else None

    def merge_with_runtime_movie(self, runtime_movie: dict, cached_movie: dict) -> dict:
        """
        将缓存电影数据与本次扫描到的运行时字段合并。

        合并原则：
        - 以缓存为主，避免重复查询；
        - 以本次扫描的 path/index/锁定信息为准，避免目录移动或顺序变化导致脏数据。
        """
        merged = copy.deepcopy(cached_movie or {})
        for key in [
            "name",
            "path",
            "index",
            "lock_year",
            "lock_original_title",
            "movie_key",
        ]:
            if key in runtime_movie:
                merged[key] = runtime_movie.get(key)
        return merged

    def save_completed_movie(self, topic_data: dict, movie_data: dict):
        """
        保存单部完整电影缓存。

        约束：
        - 只保存“完整完成”的电影；
        - 只缓存与查询/生成相关的字段，不缓存 path/index 这类本次任务输入态字段。

        设计意图：
        - 同一任务中 A 已完成、B 熔断时，A 先落盘，B 不落盘；
        - 下次重跑时直接复用 A，只重查 B；
        - 这样就实现了“逐电影断点续跑”，而不是“整夹从头再来”。
        """
        task = self._find_task(topic_data)
        if task is None:
            signature = self._build_signature(topic_data)
            task = {
                **signature,
                "movies": {},
                "updated_at": self._now_iso(),
            }
            self.payload.setdefault("tasks", []).append(task)
            print(
                "   🆕 [PreviewCache] 已创建任务缓存: "
                f"{signature['sub_mode']} | {signature['theme']} | {signature['title']}"
            )

        movie_key = str(movie_data.get("movie_key", "")).strip()
        if not movie_key:
            return

        task["movies"][movie_key] = {
            "completed": True,
            "completed_at": self._now_iso(),
            "data": self._strip_runtime_fields(movie_data),
        }
        task["updated_at"] = self._now_iso()
        self._trim_tasks()
        self._save()

    def _strip_runtime_fields(self, movie_data: dict) -> dict:
        """
        只保留可复用字段。

        说明：
        - path/index 与当前任务输入顺序绑定，不应缓存；
        - 其余与查询、AI 生成、视觉生成相关的字段全部保留。

        为什么不缓存 path/index：
        - path 依赖本次文件夹结构，目录移动或重命名后容易失真；
        - index 只代表“这次扫描出来的当前顺序”，而用户允许改顺序；
        - 因此命中缓存时，path/index 必须以“本次扫描结果”为准，再与缓存内容合并。
        """
        keep = copy.deepcopy(movie_data)
        keep.pop("path", None)
        keep.pop("index", None)
        return keep

    def _trim_tasks(self):
        """
        仅保留最近 N 次 preview 任务缓存。

        淘汰策略采用 updated_at 倒序截断：
        - 某个任务内只要又完成了一部电影，该任务就会被视为“最近使用过”；
        - 这样更符合断点续跑场景，不会把正在逐步积累的任务提前淘汰掉。
        """
        tasks = self.payload.get("tasks", [])
        tasks.sort(key=lambda x: str(x.get("updated_at", "")), reverse=True)
        removed_tasks = tasks[self.max_tasks :]
        if removed_tasks:
            for task in removed_tasks:
                print(
                    "   🧹 [PreviewCache] 已淘汰旧任务缓存: "
                    f"{task.get('sub_mode', '')} | {task.get('theme', '')} | {task.get('title', '')}"
                )
        self.payload["tasks"] = tasks[: self.max_tasks]
