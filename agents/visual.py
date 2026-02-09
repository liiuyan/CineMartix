# 文件名: agents/visual.py
import os
import json
import time
import requests
import torch
from PIL import Image
from transformers import CLIPProcessor, CLIPModel
import config # 引用配置中的路径

class VisualAgent:
    """🎨 视觉 Agent (CLIP语义去重 + 智能排序 + 修复版)"""
    def __init__(self):
        self.tmdb_key = config.TMDB_API_KEY
        self.search_key = config.SEARCH_API_KEY
        self.downloaded_embeddings = [] 
        
        # 加载 CLIP 模型
        print("   ⏳ 正在初始化 CLIP 视觉模型 (用于语义去重)...")
        self.clip_model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
        self.clip_processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
        print("   ✅ CLIP 模型就绪")

    def run(self, movie_name):
        print(f"\n🎨 [3/5 VisualAgent] 正在搜集《{movie_name}》的原版素材...")
        self.downloaded_embeddings = [] # 清空指纹库
        local_paths = []
        
        # 1. 优先 TMDB (下载 10 张)
        if self.tmdb_key:
            tmdb_paths = self._fetch_from_tmdb(movie_name, limit=10)
            if tmdb_paths:
                local_paths.extend(tmdb_paths)
                print(f"   ✅ TMDB 获取成功: {len(local_paths)} 张 (已过滤有字重复图)")
                return local_paths

        # 2. 降级 Google
        if self.search_key:
            print("   ⚠️ 降级使用 Google 搜索...")
            self._google_search(f"{movie_name} 电影海报 高清", 1, "cover", local_paths)
            self._google_search(f"{movie_name} 电影剧照 唯美", 8, "still", local_paths)
        
        return local_paths

    def _fetch_from_tmdb(self, movie_name, limit=10):
        try:
            # 1. 搜 Movie ID
            search_url = "https://api.themoviedb.org/3/search/movie"
            resp = requests.get(search_url, params={"api_key": self.tmdb_key, "query": movie_name, "language": "zh-CN"})
            results = resp.json().get("results", [])
            if not results: return []
            movie_id = results[0]["id"]
            
            # 2. 获取所有图片
            img_url = f"https://api.themoviedb.org/3/movie/{movie_id}/images"
            data = requests.get(img_url, params={"api_key": self.tmdb_key, "include_image_language": "null,zh,en"}).json()
            
            paths = []
            base = "https://image.tmdb.org/t/p/original"
            
            # --- 封面策略 ---
            posters = data.get("posters", [])
            if posters:
                zh_posters = [p for p in posters if p["iso_639_1"] == "zh"]
                best_poster = zh_posters[0] if zh_posters else posters[0]
                self._dl(base + best_poster["file_path"], movie_name, "cover_tmdb", paths)
            
            # --- 剧照策略 ---
            backdrops = data.get("backdrops", [])
            null_imgs = [x for x in backdrops if x["iso_639_1"] is None]
            zh_imgs = [x for x in backdrops if x["iso_639_1"] == "zh"]
            en_imgs = [x for x in backdrops if x["iso_639_1"] == "en"]
            
            null_imgs.sort(key=lambda x: x["vote_average"], reverse=True)
            zh_imgs.sort(key=lambda x: x["vote_average"], reverse=True)
            en_imgs.sort(key=lambda x: x["vote_average"], reverse=True)
            
            candidates = null_imgs + zh_imgs + en_imgs
            
            for i, item in enumerate(candidates):
                if len(paths) >= limit: break
                self._dl(base + item["file_path"], movie_name, f"still_tmdb_{i}", paths)
                
            return paths
        except Exception as e:
            print(f"   ⚠️ TMDB 图片失败: {e}")
            return []

    def _google_search(self, query, num, suffix, paths):
        url = "https://google.serper.dev/images"
        headers = {'X-API-KEY': self.search_key, 'Content-Type': 'application/json'}
        try:
            payload = json.dumps({"q": query, "gl": "cn", "num": num})
            resp = requests.post(url, headers=headers, data=payload)
            for i, item in enumerate(resp.json().get("images", [])):
                self._dl(item['imageUrl'], query, f"{suffix}_{i}", paths)
        except: pass

    def _get_clip_embedding(self, image):
        try:
            inputs = self.clip_processor(images=image, return_tensors="pt")
            with torch.no_grad():
                outputs = self.clip_model.get_image_features(**inputs)
                
                # 兼容性修复
                if not isinstance(outputs, torch.Tensor):
                    if hasattr(outputs, 'image_embeds'):
                        outputs = outputs.image_embeds
                    elif hasattr(outputs, 'pooler_output'):
                        outputs = outputs.pooler_output
                    else:
                        outputs = outputs[0]
                        
            embedding = outputs / outputs.norm(p=2, dim=-1, keepdim=True)
            return embedding
        except Exception as e:
            print(f"   ⚠️ Embedding 计算失败: {e}")
            return None

    def _is_semantically_duplicate(self, current_embedding):
        if not self.downloaded_embeddings:
            return False
        if current_embedding is None:
            return False

        for saved_emb in self.downloaded_embeddings:
            similarity = (current_embedding @ saved_emb.T).item()
            if similarity > config.CLIP_THRESHOLD:
                return True 
        return False

    def _dl(self, url, prefix, suffix, paths):
        try:
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                name = f"{prefix}_{suffix}_{int(time.time())}.jpg"
                path = os.path.join(config.LOCAL_IMAGE_DIR, name) # 使用 config 定义的路径
                
                with open(path, "wb") as f: f.write(resp.content)
                
                try:
                    with Image.open(path) as img:
                        img = img.convert("RGB")
                        
                        curr_emb = self._get_clip_embedding(img)
                        
                        if self._is_semantically_duplicate(curr_emb):
                            print(f"   🚫 [CLIP] 语义重复已剔除: {suffix}")
                            os.remove(path)
                            return 
                        
                        if curr_emb is not None:
                            self.downloaded_embeddings.append(curr_emb)
                        
                        img.save(path, format="JPEG", quality=95)
                        
                    paths.append(path)
                    print(f"   ⬇️ [CLIP] 下载并保留: {suffix}")
                    
                except Exception as e:
                    print(f"   ⚠️ 图片损坏或处理失败: {e}")
                    if os.path.exists(path): os.remove(path)

        except: pass