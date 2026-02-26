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
       - 封面图：主标题\\n第二行\\n第三行｜0（兼容半角 | 和全角 ｜）
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
            ],
            "cover": {  # 可选，无封面时为 None
                "path": "...",
                "title_lines": ["第一行", "第二行", "第三行"],
                "raw_title": "第一行\\n第二行\\n第三行"
            } | None
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

            # 扫描结果同时返回电影素材与可选封面图，便于下游视觉层统一编排发布序列。
            scan_result = self._scan_images_strict(folder_path)
            if scan_result is None:
                print(f"   ⛔ 严格模式校验失败，已跳过目录: {item}")
                continue
            movies = scan_result["movies"]
            cover = scan_result["cover"]
            if not movies:
                print(f"   ⚠️ 目录无有效图片，已跳过: {item}")
                continue

            cover_log = " | 含封面图" if cover else " | 无封面图"
            print(f"   ✅ 命中预览任务: {item} | 共 {len(movies)} 部{cover_log}")
            return {
                "sub_mode": self.sub_mode,
                "theme": theme,
                "title": title,
                "folder_path": folder_path,
                "movies": movies,
                "cover": cover,
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

    def _scan_images_strict(self, folder_path: str) -> dict | None:
        """
        严格扫描图片并返回按序号排序的电影列表 + 可选封面图信息。

        允许命名:
        1) 电影名｜序号
        2) 电影名｜原名｜序号
        3) 封面图：主标题\\n第二行\\n第三行｜0

        返回 None 代表命名违规，触发“整夹跳过”。
        """
        valid_exts = {".jpg", ".jpeg", ".png", ".webp"}
        movies = []
        cover_data = None

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

            # 统一分隔符处理，避免全角/半角导致解析歧义。
            # 约定：后续逻辑全部按全角分隔符分段处理。
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

            # 约定：序号 0 仅用于封面图，不参与电影数据采集。
            if index == 0:
                # 封面图必须是两段式：主标题｜0
                if len(parts) != 2:
                    print(f"      ⛔ 封面图命名不合规(必须两段式): {file_name}")
                    return None
                if cover_data is not None:
                    print(f"      ⛔ 同一任务目录检测到多张封面图(|0/｜0): {file_name}")
                    return None
                if "\\n" not in movie_name:
                    print(f"      ⛔ 封面主标题必须使用字面量 \\\\n 分为三行: {file_name}")
                    return None

                # 封面标题固定三行协议（可空第二/第三行，但第一行必须有内容）。
                title_lines = [x.strip() for x in movie_name.split("\\n")]
                if len(title_lines) != 3:
                    print(f"      ⛔ 封面主标题必须恰好包含两处 \\\\n 分隔: {file_name}")
                    return None
                if not title_lines[0]:
                    print(f"      ⛔ 封面主标题第一行不能为空: {file_name}")
                    return None

                cover_data = {
                    "path": full_path,
                    "title_lines": title_lines,
                    "raw_title": movie_name,
                }
                continue

            if index < 0:
                print(f"      ⛔ 图片序号不能为负数: {file_name}")
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
        return {"movies": movies, "cover": cover_data}
