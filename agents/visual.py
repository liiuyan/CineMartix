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
    """
    🎨 视觉 Agent (支持人工混合模式 + CLIP语义去重 + 智能排序)
    
    负责下载、筛选和处理电影图片素材。
    核心逻辑:
    1. 必须包含 1 张竖版封面 (Cover)。
    2. 补充 N 张横版剧照 (Backdrops)。
    3. 支持 '人工素材优先' 策略 (Manual Override)。
    4. 使用 CLIP 模型计算图片余弦相似度，剔除重复画面。
    """
    
    def __init__(self):
        self.tmdb_key = config.TMDB_API_KEY
        self.search_key = config.SEARCH_API_KEY
        self.downloaded_embeddings = [] # 存储当前运行中所有已采纳图片的指纹 (Embedding)
        
        # 加载 CLIP 模型 (用于语义去重)
        print("   ⏳ 正在初始化 CLIP 视觉模型 (用于语义去重)...")
        self.clip_model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
        self.clip_processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
        print("   ✅ CLIP 模型就绪")

    def run(self, movie_name: str, tmdb_id: int = None) -> list | None:
        """
        执行视觉素材获取主流程。
        
        Args:
            movie_name (str): 电影名称。
            tmdb_id (int): [Plan B] 上游锁定的 TMDB ID。
            
        Returns:
            list | None: 成功返回本地图片路径列表，失败返回 None。
        """
        print(f"\n🎨 [3/5 VisualAgent] 正在搜集《{movie_name}》的视觉素材...")
        self.downloaded_embeddings = [] # 每次运行前清空指纹库
        
        # 0. 检查是否存在人工素材文件夹
        manual_dir = os.path.join(config.BASE_DIR, "资料", "manual_materials", movie_name)
        
        if os.path.exists(manual_dir) and os.path.isdir(manual_dir):
            print(f"   📂 发现人工素材库: {manual_dir}")
            return self._run_manual_mode(movie_name, manual_dir, tmdb_id)
        else:
            print(f"   🤖 未发现人工素材，进入自动兜底模式...")
            return self._run_auto_mode(movie_name, tmdb_id)

    # ================= 核心模式 A: 人工混合模式 =================
    def _run_manual_mode(self, movie_name: str, manual_dir: str, tmdb_id: int = None) -> list | None:
        """
        人工混合模式 (Manual Mixed Mode)
        
        策略:
        1. 强制 TMDB 竖版封面 (1张) -> 若失败则全流程终止。
        2. 人工素材 (N张) -> 全盘照收，不做去重，格式统一转 JPG。
        3. TMDB 剧照补充 -> 仅当人工素材不足 Target 数量时触发，且进行严格 CLIP 去重。
        """
        final_paths = []
        tmdb_data = self._get_tmdb_images_json(movie_name, tmdb_id)
        
        if not tmdb_data:
            print("   ❌ [Fatal] 无法获取 TMDB 数据，人工模式无法启动 (需要下载封面)。")
            return None

        # --- 阶段 1: 强制获取 1 张竖版封面 ---
        print("   1️⃣ [人工模式] 正在获取 TMDB 竖版封面...")
        # 封面后缀统一为 cover_tmdb
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
        # [修改] 读取配置的目标数量
        target_count = config.Strategy.Visual.TARGET_TOTAL_IMAGES
        needed = target_count - len(final_paths)
        
        if needed > 0:
            print(f"   3️⃣ [人工模式] 需要补充 {needed} 张剧照 (Backdrops)...")
            supplement_paths = self._fetch_backdrops_with_dedup(tmdb_data, movie_name, needed)
            final_paths.extend(supplement_paths)
        else:
            print(f"   3️⃣ [人工模式] 图片数量已充足，无需自动补充。")

        return final_paths

    # ================= 核心模式 B: 自动兜底模式 (原逻辑) =================
    def _run_auto_mode(self, movie_name: str, tmdb_id: int = None) -> list:
        """
        自动兜底模式 (Auto Mode)
        
        策略:
        1. 优先使用 TMDB 下载 Target 张图片 (含1张封面)。
        2. 若 TMDB 图片不足，降级使用 Google Search (Serper) 补齐。
        """
        local_paths = []
        # [修改] 读取配置的目标数量
        target_count = config.Strategy.Visual.TARGET_TOTAL_IMAGES
        
        # 1. 优先 TMDB (下载 Target 张)
        if self.tmdb_key:
            tmdb_paths = self._fetch_from_tmdb_auto(movie_name, target_count, tmdb_id)
            if tmdb_paths:
                local_paths.extend(tmdb_paths)
                print(f"   ✅ TMDB 获取成功: {len(local_paths)} 张")
                return local_paths

        # 2. 降级 Google
        if self.search_key:
            print("   ⚠️ 降级使用 Google 搜索...")
            # 保持原版 Google 搜索的后缀逻辑
            # [修改] 动态计算剧照数量 (总数 - 1张封面)
            still_count = max(1, target_count - 1)
            self._google_search(f"{movie_name} 电影海报 高清", 1, "cover", local_paths)
            self._google_search(f"{movie_name} 电影剧照 唯美", still_count, "still", local_paths)
        
        return local_paths

    # ================= 功能函数 =================

    def _get_tmdb_images_json(self, movie_name: str, tmdb_id: int = None) -> dict | None:
        """获取 TMDB 图片原始数据 (Posters + Backdrops)"""
        if not self.tmdb_key: return None
        try:
            movie_id = None
            
            # [Plan B] 优先使用传入的 ID，不再自己搜索
            if tmdb_id:
                movie_id = tmdb_id
                print(f"   🆔 [Visual] 使用 MetaFetcher 锁定的 TMDB ID: {movie_id}")
            else:
                print(f"   ⚠️ [Visual] 未收到 ID，降级执行名称搜索: {movie_name}")
                # 1. 搜 Movie ID
                search_url = "https://api.themoviedb.org/3/search/movie"
                resp = requests.get(search_url, params={"api_key": self.tmdb_key, "query": movie_name, "language": "zh-CN"})
                results = resp.json().get("results", [])
                if not results: return None
                movie_id = results[0]["id"]
            
            # 2. 获取所有图片
            # [Fix] 扩大语言覆盖范围 (null=无文字, zh/en=通用, es/fr/ja...=常见原产国语言)
            include_langs = "null,zh,en,ja,ko,es,fr,de,it,pt,ru,hi,th"
            
            img_url = f"https://api.themoviedb.org/3/movie/{movie_id}/images"
            data = requests.get(img_url, params={
                "api_key": self.tmdb_key, 
                "include_image_language": include_langs
            }).json()
            
            # [Debug] 显式打印 API 返回的原始数量，确认数据源头是否充足
            b_count = len(data.get("backdrops", []))
            p_count = len(data.get("posters", []))
            print(f"   📊 [Meta] TMDB API 返回原始数据: 剧照 {b_count} 张, 海报 {p_count} 张")
            
            return data
            
        except Exception as e:
            print(f"   ⚠️ TMDB API 出错: {e}")
            return None

    def _fetch_best_vertical_cover(self, data: dict, movie_name: str) -> str | None:
        """
        从 TMDB 数据中寻找最佳竖版海报 (5级瀑布流筛选).
        
        逻辑:
        1. 物理筛选: 必须是竖版 (height > width).
        2. 语言筛选: 仅保留中文 (zh) 和 英文 (en).
        3. 质量门槛: 优先选取宽度 >= MIN_COVER_WIDTH 的高清图.
        4. 降级策略: 中文高清 -> 英文高清 -> 中文低清 -> 英文低清 -> 熔断.
        """
        base_url = "https://image.tmdb.org/t/p/original"
        posters = data.get("posters", [])
        
        # 1. 物理筛选: 竖版
        candidates = [p for p in posters if p.get("file_path") and p.get("height", 0) > p.get("width", 0)]
        
        if not candidates:
            print("      ❌ [Visual] TMDB 未找到任何竖版海报。")
            return None

        # 2. 分组 (Groups) & 3. 排序 (按评分降序)
        group_zh = sorted([p for p in candidates if p["iso_639_1"] == "zh"], key=lambda x: x["vote_average"], reverse=True)
        group_en = sorted([p for p in candidates if p["iso_639_1"] == "en"], key=lambda x: x["vote_average"], reverse=True)
        
        # 读取清晰度阈值
        min_width = config.Strategy.Visual.MIN_COVER_WIDTH
        selected_poster = None
        log_msg = ""

        # --- 4. 瀑布流选取 (The Waterfall) ---

        # 🏆 Stage 1: 中文高清
        for p in group_zh:
            if p["width"] >= min_width:
                selected_poster = p
                log_msg = f"✅ [Visual] 命中: 中文高清封面 (w={p['width']}, score={p['vote_average']})"
                break
        
        # 🥈 Stage 2: 英文高清 (若 Stage 1 未命中)
        if not selected_poster:
            for p in group_en:
                if p["width"] >= min_width:
                    selected_poster = p
                    log_msg = f"✅ [Visual] 命中: 英文高清封面 (w={p['width']}, score={p['vote_average']})"
                    break
        
        # 🥉 Stage 3: 中文兜底 (若 Stage 1,2 未命中)
        if not selected_poster and group_zh:
            selected_poster = group_zh[0]
            log_msg = f"⚠️ [Visual] 降级: 未找到高清图，使用最佳中文低清海报 (w={selected_poster['width']})"
            
        # 🧱 Stage 4: 英文兜底 (若 Stage 1,2,3 未命中)
        if not selected_poster and group_en:
            selected_poster = group_en[0]
            log_msg = f"⚠️ [Visual] 降级: 无中文且无高清，使用最佳英文海报 (w={selected_poster['width']})"

        # ☠️ Stage 5: 熔断
        if not selected_poster:
            print("      ❌ [Visual] 熔断: TMDB 中无中文或英文海报 (仅有其他小语种或无图)。")
            return None

        # 执行下载 (check_dedup=False, 因为它是第一张)
        print(f"      {log_msg}")
        return self._download_and_process(base_url + selected_poster["file_path"], movie_name, "cover_tmdb", check_dedup=False)

    def _load_manual_files(self, manual_dir: str, movie_name: str) -> list:
        """
        加载本地人工素材。
        
        注意:
        - 仅支持 jpg, jpeg, png, webp。
        - 即使是人工素材，也会被 _process_image_obj 处理成 JPG 格式。
        - 也会计算 CLIP 特征并存入 downloaded_embeddings，防止后续 TMDB 剧照重复。
        """
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

    def _fetch_backdrops_with_dedup(self, data: dict, movie_name: str, count: int) -> list:
        """
        获取 TMDB 剧照 (Backdrops) 并严格去重。
        
        逻辑:
        1. 优先无文字(null)和中文(zh)剧照。
        2. 每下载一张，都会与 downloaded_embeddings 中的已有图片(含封面+人工图)比对。
        3. 若相似度 > CLIP_THRESHOLD，则丢弃。
        """
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
            # [修正] 后缀恢复为 still_tmdb_{i}
            saved_path = self._download_and_process(
                base_url + item["file_path"], 
                movie_name, 
                f"still_tmdb_{i}", 
                check_dedup=True
            )
            
            if saved_path:
                paths.append(saved_path)
                
        return paths

    def _fetch_from_tmdb_auto(self, movie_name: str, limit: int = 10, tmdb_id: int = None) -> list:
        """原有的自动模式逻辑 (Poster + Backdrops 混杂)"""
        tmdb_data = self._get_tmdb_images_json(movie_name, tmdb_id)
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
        
        # [Debug] 打印最终参与下载的候选数量
        print(f"   📊 [Meta] 筛选后候选池 (Candidates): {len(candidates)} 张 (目标下载: {limit})")
        
        for i, item in enumerate(candidates):
            if len(paths) >= limit: break
            # [修正] 后缀恢复为 still_tmdb_{i}
            p = self._download_and_process(base_url + item["file_path"], movie_name, f"still_tmdb_{i}", check_dedup=True)
            if p: paths.append(p)
            
        # [Fix] 耗尽警告
        if len(paths) < limit:
             print(f"   ⚠️ 警告: 素材不足，仅获取到 {len(paths)} 张 (候选池已耗尽或下载失败)。")
            
        return paths

    def _download_and_process(self, url: str, prefix: str, suffix: str, check_dedup: bool = True) -> str | None:
        """通用下载器：下载 -> 调用 _process_image_obj"""
        try:
            resp = requests.get(url, timeout=15)
            # [Fix] 显式检查状态码，非200时报错
            if resp.status_code != 200: 
                print(f"      ⚠️ 下载请求失败 [{resp.status_code}]: {url}")
                return None
            
            # 临时将字节流转为 Image 对象
            from io import BytesIO
            img = Image.open(BytesIO(resp.content))
            return self._process_image_obj(img, prefix, suffix, check_dedup)
        except Exception as e:
            # [Fix] 打印具体异常，防止静默失败
            print(f"      ⚠️ 下载或处理异常 ({suffix}): {e}")
            return None

    def _process_image_obj(self, img_obj, prefix: str, suffix: str, check_dedup: bool = True) -> str | None:
        """
        图片处理核心管道。
        
        流程:
        1. 格式转换: RGBA -> RGB.
        2. 特征提取: 调用 CLIP 模型计算 Embedding.
        3. 语义去重: 若 check_dedup=True, 计算与历史图片的余弦相似度.
        4. 文件保存: 统一保存为 JPG (Quality 95).
        """
        try:
            img = img_obj.convert("RGB")
            
            # 1. 计算特征
            curr_emb = self._get_clip_embedding(img)
            
            # 2. 去重检查
            # [修改] 读取配置的阈值
            if check_dedup and self._is_semantically_duplicate(curr_emb):
                print(f"   🚫 [CLIP] 语义重复已剔除: {suffix}")
                return None
            
            # 3. 录入指纹 (如果不是 None)
            if curr_emb is not None:
                self.downloaded_embeddings.append(curr_emb)
            
            # 4. 保存文件
            # [修正] 恢复原版文件名格式: {prefix}_{suffix}_{time}.jpg
            name = f"{prefix}_{suffix}_{int(time.time())}.jpg"
            save_path = os.path.join(config.LOCAL_IMAGE_DIR, name)
            img.save(save_path, format="JPEG", quality=95)
            
            # [修正] 恢复成功日志
            print(f"   ⬇️ [CLIP] 下载并保留: {suffix}")
            return save_path
            
        except Exception as e:
            print(f"      ⚠️ 图片处理异常: {e}")
            return None

    def _google_search(self, query: str, num: int, suffix: str, paths: list):
        """Google 搜索降级 (维持原样)"""
        url = "https://google.serper.dev/images"
        headers = {'X-API-KEY': self.search_key, 'Content-Type': 'application/json'}
        try:
            payload = json.dumps({"q": query, "gl": "cn", "num": num})
            resp = requests.post(url, headers=headers, data=payload)
            for i, item in enumerate(resp.json().get("images", [])):
                # [注意] 这里 prefix 传入 query (例如 "电影名 海报"), 与原版逻辑一致
                p = self._download_and_process(item['imageUrl'], query, f"{suffix}_{i}", check_dedup=True)
                if p: paths.append(p)
        except: pass

    def _get_clip_embedding(self, image):
        """调用 CLIP 模型提取图片特征向量"""
        try:
            inputs = self.clip_processor(images=image, return_tensors="pt")
            with torch.no_grad():
                outputs = self.clip_model.get_image_features(**inputs)
                
                # === [修复] 恢复了完整的兼容性判断逻辑，确保健壮性 ===
                if not isinstance(outputs, torch.Tensor):
                    if hasattr(outputs, 'image_embeds'):
                        outputs = outputs.image_embeds
                    elif hasattr(outputs, 'pooler_output'):
                        outputs = outputs.pooler_output
                    else:
                        outputs = outputs[0]
                # ==================================================
                        
            embedding = outputs / outputs.norm(p=2, dim=-1, keepdim=True)
            return embedding
        except Exception as e:
            print(f"   ⚠️ Embedding 计算失败: {e}")
            return None

    def _is_semantically_duplicate(self, current_embedding) -> bool:
        """计算余弦相似度，判断是否重复"""
        if not self.downloaded_embeddings:
            return False
        if current_embedding is None:
            return False

        for saved_emb in self.downloaded_embeddings:
            similarity = (current_embedding @ saved_emb.T).item()
            # [修改] 读取配置的阈值
            if similarity > config.Strategy.Visual.CLIP_THRESHOLD:
                return True 
        return False