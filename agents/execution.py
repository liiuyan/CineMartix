# 文件名: agents/execution.py
from datetime import datetime, timedelta, timezone
import sys

import config
from utils import XHSClient

class ExecutionAgent:
    """🚀 执行 Agent"""
    def __init__(self):
        self.client = XHSClient()
        # 最近一次发布执行状态: success | cancelled | failed
        self.last_status = "failed"

    def run(self, note_data, image_paths, run_mode="single"):
        print("\n🚀 [5/5 ExecutionAgent] 准备发布...")
        self.last_status = "failed"
        
        # 第一道防线：登录态校验失败直接返回，避免无意义的发布请求。
        status = self.client.call_tool("check_login_status")
        is_logged_in = False
        if isinstance(status, dict) and (status.get("is_logged_in") is True or status.get("logged_in") is True):
            is_logged_in = True
        elif status is True:
            is_logged_in = True
            
        if not is_logged_in:
            print(f"❌ 未登录 (API返回: {status})")
            return False 

        if not image_paths:
            print("❌ 无图片")
            return False

        print(f"   标题: {note_data['title']}")
        print(f"   图片数: {len(image_paths)}")

        # 发布前统一决策入口: single=4选项，collection/preview=3选项
        # 返回值语义：
        # - False: 用户放弃发布（上游按 success is None 处理收尾）
        # - None: 立即发布
        # - str: 定时发布时间（ISO8601）
        schedule_at = self._ask_publish_decision(run_mode, note_data)
        if schedule_at is False:
            self.last_status = "cancelled"
            return None
        
        payload = {
            "title": note_data['title'],
            "content": note_data['content'],
            "images": image_paths, 
            "tags": note_data.get('tags', [])
        }
        if schedule_at:
            payload["schedule_at"] = schedule_at
            print(f"   ⏰ 本次定时发布时间: {schedule_at}")

        result = self.client.call_tool("publish_content", payload)
        
        if result:
            self.last_status = "success"
            print(f"✅ 发布成功！")
            return True
        self.last_status = "failed"
        return False

    def _ask_publish_decision(self, run_mode: str, note_data: dict):
        """
        发布前交互式选择（受总开关控制）：
        - single: 放弃 / 修改标题后发布 / 立即发布 / 定时发布
        - collection|preview: 放弃 / 立即发布 / 定时发布

        Returns:
            False: 放弃发布
            None: 立即发布
            str: 定时发布时间 (ISO8601)
        """
        # 总开关关闭时直接立即发布
        if not bool(getattr(getattr(config.Strategy, "System", None), "ENABLE_PUBLISH_DECISION_MENU", True)):
            return None

        # 非交互环境自动走立即发布，避免无人值守任务卡在 input。
        # 这条规则保障 cron/CI 下不会因为等待输入而僵死。
        if not sys.stdin.isatty():
            print("   ℹ️ 检测到非交互环境，自动选择“立即发布”。")
            return None

        if str(run_mode).strip().lower() == "single":
            return self._ask_publish_decision_single(note_data)
        return self._ask_publish_decision_common()

    def _ask_publish_decision_single(self, note_data: dict):
        """
        single 专属发布菜单：
        1) 放弃发布
        2) 修改标题后发布（不做 20 字限制）
        3) 立即发布
        4) 定时发布
        """
        print("\n🧭 请选择发布方式：")
        print("   1) 放弃发布")
        print("   2) 修改标题后发布")
        print("   3) 立即发布")
        print("   4) 定时发布")

        while True:
            choice = input("   请输入选项 (1/2/3/4，默认3): ").strip()
            if not choice or choice == "3":
                return None
            if choice == "1":
                print("   🚫 已放弃本次发布。")
                return False
            if choice == "2":
                new_title = self._ask_single_new_title(note_data.get("title", ""))
                if new_title is None:
                    continue
                note_data["title"] = new_title
                print(f"   ✅ 标题已修改为: {note_data['title']}")
                return None
            if choice == "4":
                schedule_at = self._ask_schedule_time()
                if schedule_at:
                    return schedule_at
                continue
            print("   ⚠️ 选项无效，请输入 1 / 2 / 3 / 4。")

    def _ask_publish_decision_common(self):
        """
        collection / preview 发布菜单：
        1) 放弃发布
        2) 立即发布
        3) 定时发布
        """
        print("\n🧭 请选择发布方式：")
        print("   1) 放弃发布")
        print("   2) 立即发布")
        print("   3) 定时发布")

        while True:
            choice = input("   请输入选项 (1/2/3，默认2): ").strip()
            if not choice or choice == "2":
                return None
            if choice == "1":
                print("   🚫 已放弃本次发布。")
                return False
            if choice == "3":
                schedule_at = self._ask_schedule_time()
                if schedule_at:
                    return schedule_at
                continue
            print("   ⚠️ 选项无效，请输入 1 / 2 / 3。")

    def _ask_single_new_title(self, current_title: str):
        """
        single 模式下修改标题输入。
        说明：按需求不做 20 字限制校验。
        """
        print(f"   🏷️ 当前标题: {current_title}")
        print("   ✍️ 请输入新标题（输入 q 返回上一步）")
        while True:
            new_title = input("   新标题: ").strip()
            if new_title.lower() == "q":
                return None
            if not new_title:
                print("   ⚠️ 标题不能为空，请重新输入。")
                continue
            return new_title

    def _ask_schedule_time(self):
        """
        输入并校验 schedule_at。
        要求 ISO8601 且必须包含时区，例如:
        2026-02-26T21:30:00+08:00
        """
        # 动态示例：始终给出北京时间“最近一次可用的 17:30”（当天未到则当天，已过则次日）。
        cst_tz = timezone(timedelta(hours=8))
        now_cst = datetime.now(cst_tz)
        example_dt = now_cst.replace(hour=17, minute=30, second=0, microsecond=0)
        if now_cst >= example_dt:
            example_dt = example_dt + timedelta(days=1)
        example_iso = example_dt.isoformat(timespec="seconds")

        print(f"   ⏰ 请输入定时发布时间 (ISO8601)，示例: {example_iso}")
        print("   ↩️ 输入 q 返回上一步。")

        while True:
            raw = input("   schedule_at: ").strip()
            if raw.lower() == "q":
                return None
            if not raw:
                print("   ⚠️ 时间不能为空，请重新输入。")
                continue

            try:
                dt = datetime.fromisoformat(raw)
            except ValueError:
                print("   ⚠️ 时间格式错误，请使用 ISO8601。")
                continue

            if dt.tzinfo is None:
                print("   ⚠️ 必须包含时区偏移，例如 +08:00。")
                continue

            # 统一使用输入时区做“未来时间”判定，避免本地时区差异导致误判。
            now = datetime.now(dt.tzinfo)
            if dt <= now:
                print("   ⚠️ 定时时间必须晚于当前时间。")
                continue

            return dt.isoformat(timespec="seconds")
