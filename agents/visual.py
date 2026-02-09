# 文件名: agents/visual.py
import os
import json
import time
import shutil
import requests
import torch
from PIL import Image
from transformers import CLIPProcessor, CLIPModel
import config # 引用配置中的路径

class VisualAgent:
    """🎨 视觉 Agent (支持人工混合模式 + CLIP语义去重 + 智能排序)"""
    def __init__(self):
        self.tmdb_key = config.TMDB_API_KEY
        self.search_key = config.SEARCH_API_KEY
        self.downloaded_embeddings = [] # 存储当前运行中所有已采纳图片的指纹
        
        # 加载 CLIP 模型
        print("   ⏳ 正在初始化 CLIP 视觉模型 (用于语义去重)...")
        self.clip_model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
        self.clip_processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
        print("   ✅ CLIP 模型就绪")

    def run(self, movie_name):
        print(f"\n🎨 [3/5 VisualAgent] 正在搜集《{movie_name}》的视觉素材...")
        self.downloaded_embeddings = [] # 清空指纹库
        
        # 0. 检查是否存在人工素材文件夹
        manual_dir = os.path.join(config.BASE_DIR, "资料", "manual_materials", movie_name)
        
        if os.path.exists(manual_dir) and os.path.isdir(manual_dir):
            print(f"   📂 发现人工素材库: {manual_dir}")
            return self._run_manual_mode(movie_name, manual_dir)
        else:
            print(f"   🤖 未发现人工素材，进入自动兜底模式...")
            return self._run_auto_mode(movie_name)

    # ================= 核心模式 A: 人工混合模式 =================
    def _run_manual_mode(self, movie_name, manual_dir):
        """
        逻辑：
        1. 强制 TMDB 竖版封面 (1张) -> 失败则退出
        2. 人工素材 (N张) -> 全盘照收，格式转 JPG
        3. TMDB 剧照补充 (10 - 1 - N) -> CLIP 严格去重
        """
        final_paths = []
        tmdb_data = self._get_tmdb_images_json(movie_name)
        
        if not tmdb_data:
            print("   ❌ [Fatal] 无法获取 TMDB 数据，人工模式无法启动 (需要下载封面)。")
            return None

        # --- 阶段 1: 强制获取 1 张竖版封面 ---
        print("   1️⃣ [人工模式] 正在获取 TMDB 竖版封面...")
        cover_path = self._fetch_best_vertical_cover(tmdb_data, movie_name)
        if not cover_path:
            print("   ❌ [Fatal] TMDB 未找到合适的竖版海报，程序终止。")
            return None # 返回 None 会导致 main.py 退出
        
        final_paths.append(cover_path)
        print("      ✅ 封面已就位")

        # --- 阶段 2: 加载人工素材 ---
        print("   2️⃣ [人工模式] 正在加载人工精选素材...")
        manual_paths = self._load_manual_files(manual_dir, movie_name)
        final_paths.extend(manual_paths)
        print(f"      ✅ 已加载 {len(manual_paths)} 张人工图片")

        # --- 阶段 3: 自动补充剧照 ---
        needed = 10 - len(final_paths)
        if needed > 0:
            print(f"   3️⃣ [人工模式] 需要补充 {needed} 张剧照 (Backdrops)...")
            supplement_paths = self._fetch_backdrops_with_dedup(tmdb_data, movie_name, needed)
            final_paths.extend(supplement_paths)
        else:
            print("   3️⃣ [人工模式] 图片数量已充足，无需自动补充。")

        return final_paths

    # ================= 核心模式 B: 自动兜底模式 (原逻辑) =================
    def _run_auto_mode(self, movie_name):
        local_paths = []
        
        # 1. 优先 TMDB (下载 10 张)
        if self.tmdb_key:
            tmdb_paths = self._fetch_from_tmdb_auto(movie_name, limit=10)
            if tmdb_paths:
                local_paths.extend(tmdb_paths)
                print(f"   ✅ TMDB 获取成功: {len(local_paths)} 张")
                return local_paths

        # 2. 降级 Google
        if self.search_key:
            print("   ⚠️ 降级使用 Google 搜索...")
            self._google_search(f"{movie_name} 电影海报 高清", 1, "cover", local_paths)
            self._google_search(f"{movie_name} 电影剧照 唯美", 8, "still", local_paths)
        
        return local_paths

    # ================= 功能函数 =================

    def _get_tmdb_images_json(self, movie_name):
        """获取 TMDB 图片原始数据"""
        if not self.tmdb_key: return None
        try:
            # 1. 搜 Movie ID
            search_url = "https://api.themoviedb.org/3/search/movie"
            resp = requests.get(search_url, params={"api_key": self.tmdb_key, "query": movie_name, "language": "zh-CN"})
            results = resp.json().get("results", [])
            if not results: return None
            movie_id = results[0]["id"]
            
            # 2. 获取所有图片
            img_url = f"https://api.themoviedb.org/3/movie/{movie_id}/images"
            return requests.get(img_url, params={"api_key": self.tmdb_key, "include_image_language": "null,zh,en"}).json()
        except Exception as e:
            print(f"   ⚠️ TMDB API 出错: {e}")
            return None

    def _fetch_best_vertical_cover(self, data, movie_name):
        """从 TMDB 数据中寻找最佳竖版海报"""
        base_url = "https://image.tmdb.org/t/p/original"
        posters = data.get("posters", [])
        
        # 筛选条件：有文件路径 且 高度 > 宽度 (竖版)
        valid_posters = [p for p in posters if p.get("file_path") and p.get("height", 0) > p.get("width", 0)]
        
        if not valid_posters:
            return None
            
        # 优先找中文，没有则找英文/其他，按评分排序
        zh_posters = [p for p in valid_posters if p["iso_639_1"] == "zh"]
        other_posters = [p for p in valid_posters if p["iso_639_1"] != "zh"]
        
        zh_posters.sort(key=lambda x: x["vote_average"], reverse=True)
        other_posters.sort(key=lambda x: x["vote_average"], reverse=True)
        
        best = zh_posters[0] if zh_posters else other_posters[0]
        
        # 下载并处理 (check_dedup=False, 因为它是第一张)
        return self._download_and_process(base_url + best["file_path"], movie_name, "cover_tmdb", check_dedup=False)

    def _load_manual_files(self, manual_dir, movie_name):
        """加载本地人工素材"""
        paths = []
        files = sorted(os.listdir(manual_dir)) # 排序保证顺序
        valid_exts = {'.jpg', '.jpeg', '.png', '.webp'}
        
        for i, filename in enumerate(files):
            ext = os.path.splitext(filename)[1].lower()
            if ext not in valid_exts:
                continue
                
            src_path = os.path.join(manual_dir, filename)
            
            # 读取图片对象
            try:
                img = Image.open(src_path)
                # 处理并保存 (不去重，但录入指纹)
                saved_path = self._process_image_obj(img, movie_name, f"manual_{i}", check_dedup=False)
                if saved_path:
                    paths.append(saved_path)
            except Exception as e:
                print(f"      ⚠️ 读取人工图片失败 {filename}: {e}")
                
        return paths

    def _fetch_backdrops_with_dedup(self, data, movie_name, count):
        """获取 TMDB 剧照 (Backdrops) 并严格去重"""
        paths = []
        base_url = "https://image.tmdb.org/t/p/original"
        backdrops = data.get("backdrops", [])
        
        # 简单排序：优先无字/中文
        null_imgs = [x for x in backdrops if x["iso_639_1"] is None]
        zh_imgs = [x for x in backdrops if x["iso_639_1"] == "zh"]
        en_imgs = [x for x in backdrops if x["iso_639_1"] == "en"]
        
        # 按评分降序
        candidates = sorted(null_imgs, key=lambda x: x["vote_average"], reverse=True) + \
                     sorted(zh_imgs, key=lambda x: x["vote_average"], reverse=True) + \
                     sorted(en_imgs, key=lambda x: x["vote_average"], reverse=True)
        
        for i, item in enumerate(candidates):
            if len(paths) >= count: break
            
            # 下载并处理 (开启 check_dedup)
            saved_path = self._download_and_process(
                base_url + item["file_path"], 
                movie_name, 
                f"still_tmdb_{i}", 
                check_dedup=True
            )
            
            if saved_path:
                paths.append(saved_path)
                
        return paths

    def _fetch_from_tmdb_auto(self, movie_name, limit=10):
        """原有的自动模式逻辑 (Poster + Backdrops 混杂)"""
        tmdb_data = self._get_tmdb_images_json(movie_name)
        if not tmdb_data: return []
        
        paths = []
        base_url = "https://image.tmdb.org/t/p/original"
        
        # 1. 封面
        cover_path = self._fetch_best_vertical_cover(tmdb_data, movie_name)
        if cover_path: paths.append(cover_path)
        
        # 2. 剧照 (Backdrops)
        backdrops = tmdb_data.get("backdrops", [])
        # 简单排序逻辑同上...
        null_imgs = [x for x in backdrops if x["iso_639_1"] is None]
        other_imgs = [x for x in backdrops if x["iso_639_1"] is not None]
        candidates = sorted(null_imgs, key=lambda x: x["vote_average"], reverse=True) + other_imgs
        
        for i, item in enumerate(candidates):
            if len(paths) >= limit: break
            p = self._download_and_process(base_url + item["file_path"], movie_name, f"still_auto_{i}", check_dedup=True)
            if p: paths.append(p)
            
        return paths

    def _download_and_process(self, url, movie_name, suffix, check_dedup=True):
        """通用下载器：下载 -> 调用 _process_image_obj"""
        try:
            resp = requests.get(url, timeout=15)
            if resp.status_code != 200: return None
            
            # 临时将字节流转为 Image 对象
            from io import BytesIO
            img = Image.open(BytesIO(resp.content))
            return self._process_image_obj(img, movie_name, suffix, check_dedup)
        except:
            return None

    def _process_image_obj(self, img_obj, movie_name, suffix, check_dedup=True):
        """
        核心处理逻辑：
        1. 格式统一转 RGB
        2. CLIP 特征计算
        3. 语义去重 (可选)
        4. 保存为 JPG
        """
        try:
            img = img_obj.convert("RGB")
            
            # 1. 计算特征
            curr_emb = self._get_clip_embedding(img)
            
            # 2. 去重检查
            if check_dedup and self._is_semantically_duplicate(curr_emb):
                print(f"      🚫 [CLIP] 语义重复已剔除: {suffix}")
                return None
            
            # 3. 录入指纹 (如果不是 None)
            if curr_emb is not None:
                self.downloaded_embeddings.append(curr_emb)
            
            # 4. 保存文件
            name = f"{suffix}_{int(time.time())}.jpg"
            save_path = os.path.join(config.LOCAL_IMAGE_DIR, name)
            img.save(save_path, format="JPEG", quality=95)
            
            # print(f"      ⬇️ 已保存: {suffix}") 
            return save_path
            
        except Exception as e:
            print(f"      ⚠️ 图片处理异常: {e}")
            return None

    def _google_search(self, query, num, suffix, paths):
        """Google 搜索降级 (维持原样)"""
        url = "https://google.serper.dev/images"
        headers = {'X-API-KEY': self.search_key, 'Content-Type': 'application/json'}
        try:
            payload = json.dumps({"q": query, "gl": "cn", "num": num})
            resp = requests.post(url, headers=headers, data=payload)
            for i, item in enumerate(resp.json().get("images", [])):
                p = self._download_and_process(item['imageUrl'], query, f"{suffix}_{i}", check_dedup=True)
                if p: paths.append(p)
        except: pass

    def _get_clip_embedding(self, image):
        try:
            inputs = self.clip_processor(images=image, return_tensors="pt")
            with torch.no_grad():
                outputs = self.clip_model.get_image_features(**inputs)
                if not isinstance(outputs, torch.Tensor):
                    outputs = outputs[0]
            return outputs / outputs.norm(p=2, dim=-1, keepdim=True)
        except: return None

    def _is_semantically_duplicate(self, current_embedding):
        if not self.downloaded_embeddings or current_embedding is None:
            return False
        for saved_emb in self.downloaded_embeddings:
            similarity = (current_embedding @ saved_emb.T).item()
            if similarity > config.CLIP_THRESHOLD:
                return True 
        return False