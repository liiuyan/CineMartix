# 文件名: services/clip_engine.py
import torch
from transformers import CLIPProcessor, CLIPModel


class ClipEngine:
    """
    🧬 CLIP 视觉语义引擎 (ClipEngine)
    
    [重构 板块6] 从 visual.py 中抽离的纯计算引擎。
    
    设计原则:
    1. 单例模式: 避免重复加载 ~500MB 的 CLIP 模型。
    2. 无状态: 不持有任何业务数据 (如 downloaded_embeddings)，
       由调用方 (VisualAgent) 自行管理图片指纹列表。
    3. 纯计算: 只负责特征提取与相似度比较，不做业务判断。
    """
    _instance = None
    _initialized = False

    def __new__(cls):
        """单例入口: 保证全局只有一个 ClipEngine 实例"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """懒加载: 仅在首次实例化时加载模型"""
        if ClipEngine._initialized:
            return

        print("   ⏳ 正在初始化 CLIP 视觉模型 (用于语义去重)...")
        self.model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
        self.processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
        ClipEngine._initialized = True
        print("   ✅ CLIP 模型就绪")

    def get_embedding(self, image):
        """
        提取图片的 CLIP 特征向量 (归一化后)。
        
        Args:
            image: PIL.Image 对象 (RGB 模式)
            
        Returns:
            torch.Tensor | None: 归一化的特征向量，失败返回 None
        """
        try:
            inputs = self.processor(images=image, return_tensors="pt")
            with torch.no_grad():
                outputs = self.model.get_image_features(**inputs)

                # [搬迁自 visual.py] 完整的兼容性判断逻辑，确保健壮性
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

    def is_duplicate(self, current_embedding, existing_embeddings, threshold) -> bool:
        """
        计算当前图片与已有图片的余弦相似度，判断是否语义重复。
        
        Args:
            current_embedding: 当前图片的 CLIP 特征向量 (可能为 None)
            existing_embeddings (list): 已采纳图片的特征向量列表
            threshold (float): 相似度阈值 (超过此值视为重复)
            
        Returns:
            bool: True 表示重复，应丢弃
        """
        if not existing_embeddings:
            return False
        if current_embedding is None:
            return False

        for saved_emb in existing_embeddings:
            similarity = (current_embedding @ saved_emb.T).item()
            if similarity > threshold:
                return True
        return False