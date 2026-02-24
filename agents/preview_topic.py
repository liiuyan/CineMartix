import os
import config
from utils import PendingManager


class PreviewTopicAgent:
    """
    🆕 新片速递选题 Agent

    职责:
    1. 按 SUB_MODE 扫描对应目录 (landscape/poster)。
    2. 解析任务文件夹: 主题｜标题。
    3. 严格校验图片命名:
       - 电影名｜序号
       - 电影名｜原名｜序号
    """

    def __init__(self):
        # 由配置决定当前只处理哪一条输入赛道，避免两种子模式互相污染。
        self.sub_mode = getattr(config.Strategy.Preview, "SUB_MODE", "landscape")
        if self.sub_mode == "poster":
            self.base_dir = config.PREVIEW_POSTER_DIR
        else:
            self.base_dir = config.PREVIEW_LANDSCAPE_DIR

        # 发布成功后归档到 _done/<sub_mode>/，与 collection 的“整夹归档”保持一致。
        self.done_dir = os.path.join(config.PREVIEW_DONE_DIR, self.sub_mode)
        os.makedirs(self.done_dir, exist_ok=True)
        self.pending_mgr = PendingManager()

    def run(self) -> dict | None:
        """
        扫描任务目录并返回第一条可执行任务。

        返回结构:
        {
            "sub_mode": "landscape" | "poster",
            "theme": "...",
            "title": "...",
            "folder_path": "...",
            "movies": [
                {"name": "...", "path": "...", "index": 1, "lock_original_title": "...|None"}
            ]
        }

        说明:
        - 任务目录名必须包含分隔符(主题｜标题)；
        - 图片命名必须严格合规，否则整夹跳过。
        """
        print("\n📁 [1/5 PreviewTopicAgent] 正在扫描新片速递任务目录...")
        print(f"   🧭 子模式: {self.sub_mode} | 扫描路径: {self.base_dir}")

        if not os.path.exists(self.base_dir):
            print(f"   ⚠️ 目录不存在: {self.base_dir}")
            return None

        for item in sorted(os.listdir(self.base_dir)):
            folder_path = os.path.join(self.base_dir, item)
            if not os.path.isdir(folder_path):
                continue
            if "|" not in item and "｜" not in item:
                continue

            theme, title = self._parse_name(item)
            if not theme or not title:
                print(f"   ⚠️ 任务目录格式不正确，需为 '主题｜标题': {item}")
                continue

            movies = self._scan_images_strict(folder_path)
            if movies is None:
                print(f"   ⛔ 严格模式校验失败，已跳过目录: {item}")
                continue
            if not movies:
                print(f"   ⚠️ 目录无有效图片，已跳过: {item}")
                continue

            print(f"   ✅ 命中预览任务: {item} | 共 {len(movies)} 部")
            return {
                "sub_mode": self.sub_mode,
                "theme": theme,
                "title": title,
                "folder_path": folder_path,
                "movies": movies,
            }

        print("   😴 当前无可执行的新片速递任务。")
        return None

    def finish_preview(self, folder_path: str):
        """发布成功后归档任务目录。"""
        self.pending_mgr.archive_folder(folder_path, self.done_dir)

    def _parse_name(self, folder_name: str) -> tuple[str | None, str | None]:
        """
        解析目录名:
        - 标准: 主题｜标题
        - 兼容: 主题|标题
        """
        normalized = folder_name.replace("|", "｜")
        parts = [p.strip() for p in normalized.split("｜", 1)]
        if len(parts) != 2:
            return None, None
        return parts[0], parts[1]

    def _scan_images_strict(self, folder_path: str) -> list | None:
        """
        严格扫描图片并返回按序号排序的电影列表。

        允许命名:
        1) 电影名｜序号
        2) 电影名｜原名｜序号

        返回 None 代表命名违规，触发“整夹跳过”。
        """
        valid_exts = {".jpg", ".jpeg", ".png", ".webp"}
        movies = []

        for file_name in os.listdir(folder_path):
            # 忽略隐藏文件和子目录(例如 output/)
            if file_name.startswith("."):
                continue
            full_path = os.path.join(folder_path, file_name)
            if os.path.isdir(full_path):
                continue

            # 非图片文件直接忽略，不参与校验
            ext = os.path.splitext(file_name)[1].lower()
            if ext not in valid_exts:
                continue

            # 统一分隔符处理，避免全角/半角导致解析歧义
            base_name = os.path.splitext(file_name)[0]
            parts = [p.strip() for p in base_name.replace("|", "｜").split("｜")]

            movie_name = ""
            lock_original_title = None
            index_str = ""

            if len(parts) == 2:
                movie_name, index_str = parts
            elif len(parts) == 3:
                # 三段式中第二段为“原名锁定”线索，供下游采集精确匹配
                movie_name, lock_original_title, index_str = parts
                if not lock_original_title:
                    print(f"      ⛔ 三段式命名第二段不能为空: {file_name}")
                    return None
            else:
                print(f"      ⛔ 图片命名不合规: {file_name}")
                return None

            if not movie_name or not index_str:
                print(f"      ⛔ 图片命名分段为空: {file_name}")
                return None

            try:
                index = int(index_str)
            except ValueError:
                print(f"      ⛔ 图片序号必须为阿拉伯数字: {file_name}")
                return None

            # 下游只消费标准化结构，不再关心原始文件名细节。
            movies.append(
                {
                    "name": movie_name,
                    "path": full_path,
                    "index": index,
                    "lock_original_title": lock_original_title,
                }
            )

        # 发布顺序完全由编号控制，不依赖文件系统自然顺序。
        movies.sort(key=lambda x: x["index"])
        return movies
