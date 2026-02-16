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
        """
        [升级] 返回元组: (movie_name, specific_year)
        specific_year 为 None 表示不指定年份。
        """
        print("\n🔍 [1/4 TopicAgent] 正在进行选题决策...")

        # === 1. 优先检查手动待办列表 (Pending List) ===
        manual_result = self._check_pending_list()
        if manual_result:
            name, year = manual_result
            year_str = f" ({year})" if year else ""
            print(f"🎯 [主动点播] 检测到待办任务，强制执行: 《{name}》{year_str}")
            print("   (已跳过历史查重，默认您知道自己在做什么)")
            return name, year

        # === 2. AI 自动选题 (自主漫游模式) ===
        print("🤖 [AI 自动模式] 正在启动随机漫游探索...")
        return self._ai_auto_selection()

    def _check_pending_list(self):
        """
        检查 pending.txt
        [升级] 支持格式: "电影名 | 年份"
        """
        if not os.path.exists(self.pending_file):
            return None

        try:
            with open(self.pending_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            valid_lines = [line for line in lines if line.strip()]
            if not valid_lines:
                return None 

            # 解析第一行
            raw_line = valid_lines[0].strip()
            if "|" in raw_line:
                parts = raw_line.split("|")
                name = parts[0].strip()
                year = parts[1].strip()
                return name, year
            elif "｜" in raw_line: # [新增] 兼容全角符号
                parts = raw_line.split("｜")
                name = parts[0].strip()
                year = parts[1].strip()
                return name, year
            else:
                return raw_line, None

        except Exception as e:
            print(f"⚠️ 读取 pending.txt 出错: {e}")
            return None

    def finish_pending(self, movie_name, year=None):
        """
        [任务完成回调] 从 pending.txt 中移除该电影
        [升级] 匹配逻辑: 只要行首包含 movie_name 即可匹配，兼容有无年份的情况。
        """
        if not os.path.exists(self.pending_file):
            return

        try:
            with open(self.pending_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            valid_lines = [line for line in lines if line.strip()]
            
            # 如果文件第一行包含当前完成的电影名，则删除它
            # (注意：因为 pending.txt 是队列，理应完成的就是第一行)
            if valid_lines:
                first_line = valid_lines[0].strip()
                # 模糊匹配：如果第一行开头是这个电影名，就删掉
                # 例如 pending 是 "头号玩家 | 2018"，处理完的 name 是 "头号玩家"
                if first_line.startswith(movie_name):
                    print(f"🗑️ [Pending] 从待办列表中移除已发布的: 《{first_line}》")
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
        [升级] 强制要求返回 "电影名 | 年份" 格式，且严格过滤废话
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
            3. 【格式要求】：请严格按照 `电影名 | 年份` 的格式输出，一行一个，不要带序号。
               例如：
               霸王别姬 | 1993
               头号玩家 | 2018
            4. 严禁输出任何开场白或结束语，只输出纯列表。
            5. 即使数量要求较多，也请保证每一部都是高质量佳作，不要凑数。
            """
            
            print(f"   🧠 [第 {i+1}/{max_retries} 轮] AI 正在随机探索 (批量抽取 {batch_size} 部)...")
            response = self.brain.think(prompt)
            
            if not response: continue

            # 清洗候选名单
            candidates = []
            lines = response.split('\n')
            for line in lines:
                clean_line = line.strip().replace("《", "").replace("》", "").replace("-", "")
                if not clean_line: continue
                
                # [Fix] 严格解析模式：只接受带分隔符的行
                # 兼容半角 | 和 全角 ｜
                if "|" in clean_line:
                    parts = clean_line.split("|")
                    c_name = parts[0].strip()
                    c_year = parts[1].strip()
                    candidates.append((c_name, c_year))
                elif "｜" in clean_line:
                    parts = clean_line.split("｜")
                    c_name = parts[0].strip()
                    c_year = parts[1].strip()
                    candidates.append((c_name, c_year))
                else:
                    # [Security] 不带分隔符的行一律视为废话，直接丢弃
                    continue
            
            print(f"      📝 AI 提名了 {len(candidates)} 部电影...")

            # 本地全量去重
            for name, year in candidates:
                if not name: continue
                
                # 依然使用片名进行去重（保守策略）
                if name in all_posted_movies:
                    # 撞车 -> 加入动态黑名单，下一轮 Prompt 会带上它
                    session_avoid_list.append(name)
                else:
                    # 命中！
                    year_info = f" ({year})" if year else ""
                    print(f"      ✅ 最终入选: 《{name}》{year_info}")
                    return name, year
            
            print(f"      ⚠️ 本轮 {len(candidates)} 部推荐全部重复，AI 正在调整探索方向...")
            time.sleep(1)
        
        # 诚实熔断
        print(f"\n   🛑 经过 {max_retries} 轮探索 (审查了约 {max_retries * batch_size} 部电影)，未发现优质新片。")
        print("   😴 为保证质量，本次不强行发布。建议稍后重试。")
        return None, None