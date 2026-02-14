# 文件名: little_red/config.py
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# ================= 策略配置 (User Strategy) =================
# [新增] 集中管理业务参数，方便调整
class Strategy:
    """
    全局业务策略配置类。
    用于集中管理视觉、文案等模块的核心参数，避免硬编码。
    """
    
    class Visual:
        """视觉策略配置 (VisualAgent)"""
        
        # 目标图片总数 (包含封面 + 剧照)
        # [可调参数] 建议范围 9-18。数量过多可能导致小红书发布失败或处理超时。
        TARGET_TOTAL_IMAGES: int = 15
        
        # CLIP 语义去重阈值 (Range: 0.0 - 1.0)
        # 0.75 是经验值：
        # - 大于 0.8: 只有几乎一样的图才会被去重 (宽松)
        # - 小于 0.7: 构图相似的图也会被去重 (严格)
        CLIP_THRESHOLD: float = 0.75

    class Writer:
        """文案策略配置 (WriterAgent)"""
        
        # 标题重写最大重试次数
        # 若 AI 写的标题连续 N 次超过 20 字，将强制熔断，不再重试。
        MAX_TITLE_RETRIES: int = 3
        
        # [新增] 票房展示双重门槛 (单位: 人民币)
        # 门槛 A: 入场券 (5亿)。
        # 逻辑: 当无重磅奖项时，若票房超过此值，则作为替补荣誉展示。
        MIN_BOX_OFFICE_CNY: int = 500_000_000 
        
        # 门槛 B: 强制展示 (10亿)。
        # 逻辑: 无论有无奖项，只要超过此值，必须在荣誉栏展示票房。
        FORCE_BOX_OFFICE_CNY: int = 1_000_000_000

        # [新增] 美元转人民币汇率
        # 用于将 TMDB 的美元票房 (Revenue) 折算为人民币，仅用于文案展示估算。
        USD_TO_CNY_RATE: int = 7

        # [本次新增] 是否开启人工标题审核模式
        # True: 程序会在发布前暂停 (input阻塞)，等待用户在终端确认或修改标题。
        # False: 全自动模式，完全信任 AI，适合无人值守运行。
        MANUAL_TITLE_REVIEW: bool = True
        
        # [本次新增] 标题 Emoji 开关
        # True: 允许标题包含 Emoji (如 "🎬 教父")
        # False: 标题必须是纯文字 (如 "教父：黑帮史诗")，且降级策略中不包含删除 Emoji 步骤。
        ENABLE_TITLE_EMOJI: bool = True


# ================= 路径配置 (定海神针) =================
# 获取当前文件(config.py)所在的目录，即项目根目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 图片存放绝对路径 (自动创建)
LOCAL_IMAGE_DIR = os.path.join(BASE_DIR, "资料", "image")

# 字体存放绝对路径
LOCAL_FONT_PATH = os.path.join(BASE_DIR, "资料", "fonts", "font.ttf")

# 历史记录文件路径 (用于去重)
HISTORY_FILE = os.path.join(BASE_DIR, "history.json")

# 自动创建必要目录
if not os.path.exists(LOCAL_IMAGE_DIR):
    try:
        os.makedirs(LOCAL_IMAGE_DIR, exist_ok=True)
    except:
        pass

# ================= API 密钥配置 =================
# 必须在 .env 文件中配置这些 Key
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
SEARCH_API_KEY = os.getenv("SEARCH_API_KEY") # Google Search / Serper
TMDB_API_KEY = os.getenv("TMDB_API_KEY")
OMDB_API_KEY = os.getenv("OMDB_API_KEY")     # [新增] OMDB Key (用于烂番茄/MTC分数)
SERPER_API_KEY = os.getenv("SERPER_API_KEY") # [新增] Serper Key (用于搜索豆瓣分)

# 小红书 API 地址 (本地服务)
API_BASE_URL = "http://localhost:18060/api/v1"
