import os
# [重构 板块8] 删除 import shutil — 归档逻辑已于板块4迁入 PendingManager
import config
from utils import PendingManager

class CollectionTopicAgent:
    """
    📁 合集选题与解析 Agent (CollectionTopicAgent)
    
    负责扫描 config.COLLECTION_DIR，寻找符合规范的合集文件夹。
    规范：
    1. 文件夹命名：探讨主题｜笔记标题 (或半角|)
    2. 图片命名：电影名｜阿拉伯数字.jpg
    3. 严格模式：一旦发现命名不规范的图片，直接跳过整个文件夹。
    """
    def __init__(self):
        self.base_dir = config.COLLECTION_DIR
        self.done_dir = os.path.join(self.base_dir, "_done")
        
        # 确保归档区存在
        if not os.path.exists(self.done_dir):
            os.makedirs(self.done_dir, exist_ok=True)
        
        self.pending_mgr = PendingManager()  # [重构 板块4] 委托 PendingManager 执行归档

    def run(self) -> dict | None:
        """
        执行合集扫描逻辑。
        返回字典: {"theme": 主题, "title": 标题, "folder_path": 路径, "movies": [排序后的电影列表]}
        """
        print("\n📁 [1/5 CollectionTopicAgent] 正在扫描合集目录...")
        
        if not os.path.exists(self.base_dir):
            print(f"   ⚠️ 找不到合集目录: {self.base_dir}")
            return None
            
        # 读取目录下所有项
        items = sorted(os.listdir(self.base_dir))
        
        for item in items:
            folder_path = os.path.join(self.base_dir, item)
            
            # --- 1. 过滤区 ---
            # 跳过非文件夹
            if not os.path.isdir(folder_path): 
                continue
            # 跳过素材库和归档区 (免疫保护)
            if item.lower() == "store" or item.lower() == "_done": 
                continue
            
            # --- 2. 白名单区 ---
            # 只处理名字里带有 | 或 ｜ 的文件夹
            if "|" not in item and "｜" not in item:
                continue
                
            print(f"\n   🎯 锁定目标合集: 【{item}】")
            
            # 解析探讨主题和笔记标题
            theme, title = self._parse_name(item)
            if not theme or not title:
                print(f"      ⚠️ 文件夹名称格式不完整，需为'主题｜标题'。已跳过。")
                continue
                
            # --- 3. 严格模式扫描内部图片 ---
            movies = self._scan_images_strict(folder_path, item)
            
            if movies is None:
                # 触发了严格模式熔断，放弃当前合集，去看看别的文件夹
                continue
                
            if len(movies) == 0:
                print(f"      ⚠️ 文件夹内没有有效图片，跳过。")
                continue
                
            print(f"      ✅ 成功提取 {len(movies)} 部电影原图，已按编号严谨排序。")
            
            # 返回提取到的所有干净数据
            return {
                "theme": theme,
                "title": title,
                "folder_path": folder_path,
                "movies": movies  # 格式: [{'name': '星际穿越', 'path': '...', 'index': 1}, ...]
            }
            
        print("   😴 未发现待处理的有效合集任务。")
        return None

    def _parse_name(self, name: str):
        """兼容解析全半角分隔符，返回 (左侧, 右侧)"""
        if "｜" in name:
            parts = name.split("｜")
        elif "|" in name:
            parts = name.split("|")
        else:
            return None, None
            
        if len(parts) >= 2:
            return parts[0].strip(), parts[1].strip()
        return None, None

    def _scan_images_strict(self, folder_path: str, folder_name: str) -> list | None:
        """
        [严格模式] 扫描图片并排序
        只要有一张图片命名不合规，立刻返回 None 熔断。
        """
        valid_exts = {".jpg", ".jpeg", ".png", ".webp"}
        movies = []
        
        for file_name in os.listdir(folder_path):
            # 跳过隐藏文件 (如 .DS_Store) 或内部子文件夹 (如 output)
            if file_name.startswith(".") or os.path.isdir(os.path.join(folder_path, file_name)):
                continue
                
            ext = os.path.splitext(file_name)[1].lower()
            if ext not in valid_exts:
                continue # 忽略非图片文件
                
            # 严格命名校验
            base_name = os.path.splitext(file_name)[0]
            movie_name, index_str = self._parse_name(base_name)
            
            # 查杀 1：没有分隔符
            if not movie_name or not index_str:
                print(f"      ⛔ [严格模式熔断] 发现不规范文件: {file_name}")
                print(f"         必须为 '电影名|阿拉伯数字.jpg'。已跳过该合集！")
                return None
                
            # 查杀 2：后缀不是数字
            try:
                index = int(index_str)
            except ValueError:
                print(f"      ⛔ [严格模式熔断] 发现非数字编号: {file_name}")
                print(f"         后缀必须为纯阿拉伯数字。已跳过该合集！")
                return None
                
            full_path = os.path.join(folder_path, file_name)
            movies.append({
                "name": movie_name,
                "path": full_path,
                "index": index
            })
            
        # 根据数字编号进行严谨的升序排列 (1, 2, 3...)
        movies.sort(key=lambda x: x["index"])
        return movies

    def finish_collection(self, folder_path: str):
        """
        [集装箱归档] [重构 板块4] 委托 PendingManager 执行归档
        被 main.py 在发布成功后调用。
        """
        self.pending_mgr.archive_folder(folder_path, self.done_dir)