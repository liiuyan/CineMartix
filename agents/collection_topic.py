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
    2. 图片命名支持两种：
       - 旧格式：电影名｜阿拉伯数字.jpg
       - 新格式：电影名｜年份或原名｜阿拉伯数字.jpg
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
        返回字典:
        {
            "theme": 主题,
            "title": 标题,
            "folder_path": 路径,
            "movies": [排序后的电影列表],
            "cover": {可选封面数据} | None
        }
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
            scan_result = self._scan_images_strict(folder_path, item)
            if scan_result is None:
                # 触发了严格模式熔断，放弃当前合集，去看看别的文件夹
                continue

            movies = scan_result["movies"]
            cover = scan_result["cover"]
            if len(movies) == 0:
                print(f"      ⚠️ 文件夹内没有有效图片，跳过。")
                continue

            cover_log = " | 含封面图" if cover else " | 无封面图"
            print(f"      ✅ 成功提取 {len(movies)} 部电影原图，已按编号严谨排序。{cover_log}")
            
            # 返回提取到的所有干净数据
            return {
                "theme": theme,
                "title": title,
                "folder_path": folder_path,
                "movies": movies,  # 格式: [{'name': '星际穿越', 'path': '...', 'index': 1}, ...]
                # 与 preview 对齐：封面缺失时返回 None，存在时返回标准化结构。
                "cover": cover,
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

    def _scan_images_strict(self, folder_path: str, folder_name: str) -> dict | None:
        """
        [严格模式] 扫描图片并排序，同时识别可选封面图。
        只要有一张图片命名不合规，立刻返回 None 熔断。
        """
        valid_exts = {".jpg", ".jpeg", ".png", ".webp"}
        movies = []
        cover_data = None
        
        for file_name in os.listdir(folder_path):
            # 跳过隐藏文件 (如 .DS_Store) 或内部子文件夹 (如 output)
            if file_name.startswith(".") or os.path.isdir(os.path.join(folder_path, file_name)):
                continue
                
            ext = os.path.splitext(file_name)[1].lower()
            if ext not in valid_exts:
                continue # 忽略非图片文件
                
            # 严格命名校验
            base_name = os.path.splitext(file_name)[0]
            parts = self._split_by_pipe(base_name)

            # 支持两种格式：
            # 1) 电影名｜序号
            # 2) 电影名｜年份或原名｜序号
            if len(parts) == 2:
                movie_name, index_str = parts
                lock_year = None
                lock_original_title = None
            elif len(parts) == 3:
                movie_name, lock_hint, index_str = parts
                if not lock_hint:
                    print(f"      ⛔ [严格模式熔断] 发现不规范文件: {file_name}")
                    print(f"         三段式命名的第二段(年份或原名)不能为空。已跳过该合集！")
                    return None
                # [本次新增] 自动识别：第二段是4位合理年份则按年份锁定，否则按原名锁定
                if self._is_reasonable_year(lock_hint):
                    lock_year = lock_hint
                    lock_original_title = None
                else:
                    lock_year = None
                    lock_original_title = lock_hint
            else:
                print(f"      ⛔ [严格模式熔断] 发现不规范文件: {file_name}")
                print(f"         必须为 '电影名|阿拉伯数字.jpg' 或 '电影名|年份或原名|阿拉伯数字.jpg'。已跳过该合集！")
                return None

            # 查杀 1：分段为空
            if not movie_name or not index_str:
                print(f"      ⛔ [严格模式熔断] 发现不规范文件: {file_name}")
                print(f"         文件名分段不能为空。已跳过该合集！")
                return None
                
            # 查杀 2：后缀不是数字
            try:
                index = int(index_str)
            except ValueError:
                print(f"      ⛔ [严格模式熔断] 发现非数字编号: {file_name}")
                print(f"         后缀必须为纯阿拉伯数字。已跳过该合集！")
                return None
                
            # 序号 0 专用于合集封面，协议与 preview 完全一致。
            if index == 0:
                if len(parts) != 2:
                    print(f"      ⛔ [严格模式熔断] 封面图命名不合规(必须两段式): {file_name}")
                    print(f"         封面必须为 '主标题第一行\\n第二行\\n第三行|0.jpg'。已跳过该合集！")
                    return None
                if cover_data is not None:
                    print(f"      ⛔ [严格模式熔断] 同一合集检测到多张封面图(|0/｜0): {file_name}")
                    print(f"         同一合集只允许 1 张封面。已跳过该合集！")
                    return None
                if "\\n" not in movie_name:
                    print(f"      ⛔ [严格模式熔断] 封面主标题必须使用字面量 \\\\n 分为三行: {file_name}")
                    print(f"         已跳过该合集！")
                    return None

                title_lines = [x.strip() for x in movie_name.split("\\n")]
                if len(title_lines) != 3:
                    print(f"      ⛔ [严格模式熔断] 封面主标题必须恰好包含两处 \\\\n: {file_name}")
                    print(f"         已跳过该合集！")
                    return None
                if not title_lines[0]:
                    print(f"      ⛔ [严格模式熔断] 封面主标题第一行不能为空: {file_name}")
                    print(f"         已跳过该合集！")
                    return None

                cover_data = {
                    "path": os.path.join(folder_path, file_name),
                    "title_lines": title_lines,
                    "raw_title": movie_name,
                }
                continue

            if index < 0:
                print(f"      ⛔ [严格模式熔断] 发现负数编号: {file_name}")
                print(f"         图片编号不能为负数。已跳过该合集！")
                return None

            full_path = os.path.join(folder_path, file_name)
            movies.append({
                "name": movie_name,
                "path": full_path,
                "index": index,
                # [本次新增] 精准锁定参数，供 CollectionMetaFetcher -> MetaFetcher 透传
                "lock_year": lock_year,
                "lock_original_title": lock_original_title
            })
            
        # 根据数字编号进行严谨的升序排列 (1, 2, 3...)
        movies.sort(key=lambda x: x["index"])
        return {"movies": movies, "cover": cover_data}

    def _split_by_pipe(self, raw_name: str) -> list:
        """统一兼容全角/半角分隔符，返回去首尾空格后的分段列表。"""
        normalized = raw_name.replace("|", "｜")
        return [p.strip() for p in normalized.split("｜")]

    def _is_reasonable_year(self, value: str) -> bool:
        """
        判断是否为“可作为电影年份”的四位数字。
        采用合理区间，避免把普通数字误判成年份。
        """
        if not value or len(value) != 4 or (not value.isdigit()):
            return False
        year = int(value)
        return 1888 <= year <= 2030

    def finish_collection(self, folder_path: str):
        """
        [集装箱归档] [重构 板块4] 委托 PendingManager 执行归档
        被 main.py 在发布成功后调用。
        """
        self.pending_mgr.archive_folder(folder_path, self.done_dir)
