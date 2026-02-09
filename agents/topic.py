# 文件名: agents/topic.py
import os  # 必须导入 os 模块
import time
import config
from utils import LLMBrain, HistoryManager

class TopicAgent:
    """选题 Agent (支持 pending.txt 主动点播 + 强制插队)"""
    def __init__(self):
        self.brain = LLMBrain()
        self.history = HistoryManager()
        # [修改点1] 使用 os.path.join 拼接路径，修复 TypeError 报错
        self.pending_file = os.path.join(config.BASE_DIR, "pending.txt")

    def run(self):
        print("\n🔍 [1/4 TopicAgent] 正在进行选题决策...")

        # === 1. 优先检查手动待办列表 (Pending List) ===
        manual_topic = self._check_pending_list()
        if manual_topic:
            print(f"🎯 [主动点播] 检测到待办任务，强制执行: 《{manual_topic}》")
            print("   (已跳过历史查重，默认您知道自己在做什么)")
            return manual_topic

        # === 2. 如果没有手动任务，则进行 AI 自动选题 (Fallback) ===
        print("🤖 [AI 自动模式] 正在思考新的电影选题...")
        return self._ai_auto_selection()

    def _check_pending_list(self):
        """
        检查 pending.txt
        逻辑：读取第一行有效内容 -> 从文件中删除该行 -> 返回电影名
        """
        # [修改点2] 使用 os.path.exists 判断文件是否存在
        if not os.path.exists(self.pending_file):
            return None

        try:
            # 读取所有行
            with open(self.pending_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            # 过滤掉空行和只有空格的行
            valid_lines = [line for line in lines if line.strip()]
            
            if not valid_lines:
                return None # 文件为空或只有回车

            # 取出第一部电影 (去掉首尾空格)
            target_movie = valid_lines[0].strip()
            
            # === 核心逻辑：看完即焚 ===
            # 将剩余的行写回文件 (更新待办列表)
            remaining_lines = valid_lines[1:]
            with open(self.pending_file, "w", encoding="utf-8") as f:
                f.writelines(remaining_lines)
            
            return target_movie

        except Exception as e:
            print(f"⚠️ 读取 pending.txt 出错 (将自动降级为AI选题): {e}")
            return None

    def _ai_auto_selection(self):
        """
        原有的 AI 选题逻辑 (DeepSeek + 历史查重)
        """
        max_retries = 3
        # 获取最近 5 个已发电影，避免近期重复风格
        recent_movies = self.history.get_recent(5)
        
        for i in range(max_retries):
            prompt = f"""
            请推荐一部适合发小红书的电影。
            
            【限制条件】：
            1. 绝对不能是以下电影（最近已发）：{recent_movies}
            2. 可以在“影史经典”、“冷门佳作”、“商业爽片”、“高分悬疑”中随机选择一种风格。
            3. 直接返回电影名称，不要任何标点符号，不要书名号，不要任何解释。
            """
            
            # 调用 DeepSeek
            response = self.brain.think(prompt)
            
            # 清洗数据
            movie_candidate = response.strip().replace("《", "").replace("》", "").replace('"', '').replace("'", "")
            
            # 查重 (AI 选的必须查重)
            if not self.history.is_posted(movie_candidate):
                return movie_candidate
            
            print(f"🔄 选题《{movie_candidate}》已重复，正在重试 ({i+1}/{max_retries})...")
            time.sleep(1)
        
        return "肖申克的救赎" # 兜底策略