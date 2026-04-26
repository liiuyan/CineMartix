import os
import re

import config
from utils import PendingManager


class ProxyTopicAgent:
    """
    🧩 代理模式任务扫描 Agent。

    职责:
    1. 扫描 资料/proxy/ 下排序最靠前的任务文件夹。
    2. 校验 note.md 与纯数字编号图片。
    3. 返回可直接交给 ExecutionAgent 的图片顺序。
    """

    def __init__(self):
        self.base_dir = config.PROXY_DIR
        self.done_dir = config.PROXY_DONE_DIR
        os.makedirs(self.done_dir, exist_ok=True)
        self.pending_mgr = PendingManager()  # 复用统一归档能力，保持成功收尾口径一致。

    def run(self) -> dict | None:
        """
        扫描第一条代理任务。

        返回结构:
        {
            "folder_path": "...",
            "note_path": ".../note.md",
            "image_paths": [".../1.jpg", ".../03.jpg", ...]
        }
        """
        print("\n📁 [1/3 ProxyTopicAgent] 正在扫描代理任务目录...")
        print(f"   🧭 扫描路径: {self.base_dir}")

        if not os.path.exists(self.base_dir):
            print(f"   ⚠️ 目录不存在: {self.base_dir}")
            return None

        for item in sorted(os.listdir(self.base_dir)):
            folder_path = os.path.join(self.base_dir, item)
            if item.startswith(".") or item == "_done" or not os.path.isdir(folder_path):
                continue

            print(f"\n   🎯 锁定代理任务: 【{item}】")
            # 代理模式按队列处理第一条任务；第一条非法时直接停，避免跳过错误任务误发后续任务。
            return self._build_task(folder_path)

        print("   😴 当前无可执行的代理任务。")
        return None

    def _build_task(self, folder_path: str) -> dict | None:
        """校验任务目录并返回标准化任务数据。"""
        note_path = os.path.join(folder_path, "note.md")
        if not os.path.isfile(note_path):
            print("      ⛔ [代理模式熔断] 缺少 note.md，已停止发布。")
            return None

        image_paths = self._scan_images_strict(folder_path)
        if not image_paths:
            return None

        print(f"      ✅ 成功提取 {len(image_paths)} 张图片，已按数字编号升序排序。")
        return {
            "folder_path": folder_path,
            "note_path": note_path,
            "image_paths": image_paths,
        }

    def _scan_images_strict(self, folder_path: str) -> list[str] | None:
        """
        严格扫描代理图片。

        规则:
        - 文件名主干必须是 ASCII 阿拉伯数字，例如 1 / 03 / 10。
        - 允许缺号和前导零，但数字值不能重复。
        - 编号 1 必须存在，并作为发布封面。
        """
        valid_exts = {".jpg", ".jpeg", ".png", ".webp"}
        indexed_images: dict[int, str] = {}
        indexed_names: dict[int, str] = {}

        for file_name in os.listdir(folder_path):
            if file_name.startswith("."):
                continue

            full_path = os.path.join(folder_path, file_name)
            if os.path.isdir(full_path) or file_name == "note.md":
                continue

            ext = os.path.splitext(file_name)[1].lower()
            if ext not in valid_exts:
                continue

            base_name = os.path.splitext(file_name)[0]
            if not re.fullmatch(r"[0-9]+", base_name):
                print(f"      ⛔ [代理模式熔断] 图片编号必须为纯阿拉伯数字: {file_name}")
                return None

            index = int(base_name)
            if index <= 0:
                print(f"      ⛔ [代理模式熔断] 图片编号必须从 1 开始，不能使用 0: {file_name}")
                return None

            if index in indexed_images:
                print(f"      ⛔ [代理模式熔断] 检测到重复数字编号: {indexed_names[index]} / {file_name}")
                print("         例如 1.jpg 与 01.png 会被视为同一个编号。")
                return None

            indexed_images[index] = full_path
            indexed_names[index] = file_name

        if not indexed_images:
            print("      ⛔ [代理模式熔断] 任务目录内没有有效图片。")
            return None

        if 1 not in indexed_images:
            print("      ⛔ [代理模式熔断] 必须存在编号 1 的图片作为封面。")
            return None

        # 发布顺序完全由数字值决定，允许 1、03、10 这种非连续编号。
        return [path for _, path in sorted(indexed_images.items(), key=lambda item: item[0])]

    def finish_proxy(self, folder_path: str):
        """发布成功后归档代理任务目录。"""
        self.pending_mgr.archive_folder(folder_path, self.done_dir)
