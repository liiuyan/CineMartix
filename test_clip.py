import torch
from PIL import Image
from transformers import CLIPProcessor, CLIPModel
import os

# === 配置区域 ===
# 测试图路径基于脚本所在项目根目录拼接，项目移动后不需要改绝对路径。
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_PATHS = [
    os.path.join(BASE_DIR, "资料", "image", "美丽人生_still_tmdb_0_1770391886.jpg"),
    os.path.join(BASE_DIR, "资料", "image", "美丽人生_still_tmdb_2_1770391890.jpg"),
    os.path.join(BASE_DIR, "资料", "image", "美丽人生_still_tmdb_3_1770391893.jpg"),
    os.path.join(BASE_DIR, "资料", "image", "美丽人生_still_tmdb_4_1770391895.jpg"),
]
# ================

def load_clip():
    print("⏳ 正在加载 CLIP 模型...")
    model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
    processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
    print("✅ 模型加载完毕")
    return model, processor

def get_similarity(model, processor, img_path1, img_path2):
    try:
        image1 = Image.open(img_path1)
        image2 = Image.open(img_path2)
        
        # 预处理
        inputs = processor(images=[image1, image2], return_tensors="pt", padding=True)
        
        with torch.no_grad():
            # 获取特征
            outputs = model.get_image_features(**inputs)
            
            # 🛠️ 兼容性修复：确保获取到的是 Tensor
            if not isinstance(outputs, torch.Tensor):
                if hasattr(outputs, 'image_embeds'):
                    outputs = outputs.image_embeds
                elif hasattr(outputs, 'pooler_output'):
                    outputs = outputs.pooler_output
                else:
                    outputs = outputs[0]
        
        # 归一化特征向量
        embeddings = outputs / outputs.norm(p=2, dim=-1, keepdim=True)
        
        # 计算余弦相似度
        similarity = (embeddings[0] @ embeddings[1].T).item()
        return similarity
    except Exception as e:
        print(f"❌ 图片处理出错 ({os.path.basename(img_path1)} vs {os.path.basename(img_path2)}): {e}")
        return 0.0

if __name__ == "__main__":
    # 简单的路径检查
    for p in IMAGE_PATHS:
        if not os.path.exists(p):
            print(f"❌ 找不到文件: {p}")
            exit()

    model, processor = load_clip()
    
    print("\n🔍 === 开始两两对比 (Pairwise Comparison) ===\n")
    
    # 双重循环进行两两对比
    count = 0
    for i in range(len(IMAGE_PATHS)):
        for j in range(i + 1, len(IMAGE_PATHS)):
            path1 = IMAGE_PATHS[i]
            path2 = IMAGE_PATHS[j]
            
            name1 = os.path.basename(path1)
            name2 = os.path.basename(path2)
            
            sim = get_similarity(model, processor, path1, path2)
            
            # 打印结果，高亮相似度高的
            mark = "🔴 重复" if sim > 0.92 else "🟢 不同"
            print(f"[{i+1} vs {j+1}] 相似度 {sim:.4f} | {mark} | {name1} <-> {name2}")
            count += 1

    print(f"\n✅ 对比完成，共进行了 {count} 组对比。")
    print("💡 建议：观察被标记为 '🔴 重复' 的组，确认 0.92 这个阈值是否符合你的预期。")
