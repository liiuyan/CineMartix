# 文件名: agents/topic.py
import os
import time
import random
import config
from utils import LLMBrain, HistoryManager

class TopicAgent:
    """选题 Agent (支持 pending.txt 主动点播 + AI 自主漫游选题)"""
    def __init__(self):
        self.brain = LLMBrain()
        self.history = HistoryManager()
        self.pending_file = os.path.join(config.BASE_DIR, "pending.txt")

    def run(self):
        print("\n🔍 [1/4 TopicAgent] 正在进行选题决策...")

        # === 1. 优先检查手动待办列表 (Pending List) ===
        manual_topic = self._check_pending_list()
        if manual_topic:
            print(f"🎯 [主动点播] 检测到待办任务，强制执行: 《{manual_topic}》")
            print("   (已跳过历史查重，默认您知道自己在做什么)")
            return manual_topic

        # === 2. AI 自动选题 (自主漫游模式) ===
        print("🤖 [AI 自动模式] 正在启动随机漫游探索...")
        return self._ai_auto_selection()

    def _check_pending_list(self):
        """
        检查 pending.txt
        逻辑：仅读取第一行有效内容，不进行删除操作
        """
        if not os.path.exists(self.pending_file):
            return None

        try:
            with open(self.pending_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            valid_lines = [line for line in lines if line.strip()]
            if not valid_lines:
                return None 

            # 返回第一行指令
            return valid_lines[0].strip()

        except Exception as e:
            print(f"⚠️ 读取 pending.txt 出错: {e}")
            return None

    def finish_pending(self, movie_name):
        """
        [任务完成回调] 从 pending.txt 中移除该电影
        """
        if not os.path.exists(self.pending_file):
            return

        try:
            with open(self.pending_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            valid_lines = [line for line in lines if line.strip()]
            
            # 如果文件第一行确实是当前完成的电影，则删除它
            if valid_lines and valid_lines[0].strip() == movie_name:
                print(f"🗑️ [Pending] 从待办列表中移除已发布的: 《{movie_name}》")
                remaining_lines = valid_lines[1:]
                with open(self.pending_file, "w", encoding="utf-8") as f:
                    f.writelines(remaining_lines)
            
        except Exception as e:
            print(f"⚠️ 更新 pending.txt 失败: {e}")

    def _ai_auto_selection(self):
        """
        [终极版] AI 选题逻辑：
        1. AI 自主随机锁定领域 (无限广度)
        2. 批量提名 (20部) + 本地全量去重
        3. 动态负面反馈 (越试越准)
        4. 诚实熔断 (找不到就报告失败，不硬发)
        """
        max_retries = 5  # 最大重试轮数
        batch_size = 20  # [修改点] 增加到 20 部，提高命中率
        
        # 1. 获取全量历史 (用于本地严格判定)
        all_posted_movies = set(self.history.get_all_movies())
        
        # 2. 初始化“本轮会话避雷名单” 
        #    (包含最近已发的 20 部 + 本次运行中 AI 猜错的)
        session_avoid_list = self.history.get_recent(20)
        
        print(f"   📊 历史库已收录 {len(all_posted_movies)} 部电影")
        
        for i in range(max_retries):
            # 构建避雷字符串 (防止 Prompt 过长，只取最后 50 个)
            avoid_str = "、".join(session_avoid_list[-50:])
            
            prompt = f"""
            请推荐 {batch_size} 部适合做小红书解说的高分电影。
            
            【思考步骤】：
            1. 请先在你的数据库中随机锁定一个**具体的电影标签**（例如：冷门佳作、90年代港片、北欧犯罪、奥斯卡遗珠、赛博朋克、治愈系... 任何标签都可以）。
            2. 基于该标签推荐电影。
            
            【绝对限制】：
            1. 严禁推荐以下电影（已列入黑名单）：{avoid_str}
            2. 豆瓣评分 7.5 以上。
            3. 【格式要求】：只返回电影名列表，一行一个，不要带序号，不要书名号，不要解释标签是什么。
            4. 即使数量要求较多，也请保证每一部都是高质量佳作，不要凑数。
            """
            
            print(f"   🧠 [第 {i+1}/{max_retries} 轮] AI 正在随机探索 (批量抽取 {batch_size} 部)...")
            response = self.brain.think(prompt)
            
            if not response: continue

            # 清洗候选名单
            candidates = [
                line.strip().replace("《", "").replace("》", "").replace("-", "") 
                for line in response.split('\n') if line.strip()
            ]
            
            print(f"      📝 AI 提名了 {len(candidates)} 部电影...")

            # 本地全量去重
            for movie in candidates:
                if not movie: continue
                
                if movie in all_posted_movies:
                    # 撞车 -> 加入动态黑名单，下一轮 Prompt 会带上它
                    session_avoid_list.append(movie)
                else:
                    # 命中！
                    print(f"      ✅ 最终入选: 《{movie}》")
                    return movie
            
            print(f"      ⚠️ 本轮 {len(candidates)} 部推荐全部重复，AI 正在调整探索方向...")
            time.sleep(1)
        
        # 诚实熔断
        print(f"\n   🛑 经过 {max_retries} 轮探索 (审查了约 {max_retries * batch_size} 部电影)，未发现优质新片。")
        print("   😴 为保证质量，本次不强行发布。建议稍后重试。")
        return None