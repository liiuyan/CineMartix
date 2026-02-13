# 文件名: little_red/config.py
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# ================= 策略配置 (User Strategy) =================
# [新增] 集中管理业务参数，方便调整
class Strategy:
    class Visual:
        # 目标图片总数 (包含封面 + 剧照)
        # [可调参数] 如果你想要更多图片，直接修改这里即可 (例如改成 18)
        TARGET_TOTAL_IMAGES = 10
        
        # CLIP 语义去重阈值 (越接近1越严格，0.75 是经验值)
        CLIP_THRESHOLD = 0.75

    class Writer:
        # 标题重写最大重试次数
        MAX_TITLE_RETRIES = 3
        
        # [新增] 票房展示双重门槛 (单位: 人民币)
        # 门槛 A: 入场券 (1亿)。超过此数值，作为无奖项时的替补。
        MIN_BOX_OFFICE_CNY = 100_000_000 
        
        # 门槛 B: 强制展示 (10亿)。超过此数值，无论有无奖项，必须展示。
        FORCE_BOX_OFFICE_CNY = 1_000_000_000

        # [新增] 美元转人民币汇率 (TMDB返回的是美元)
        # 这是一个估算值，足够用于文案展示
        USD_TO_CNY_RATE = 7.3

        # [本次新增] 是否开启人工标题审核模式
        # True: 程序会在发布前暂停，等待你确认或修改标题
        # False: 全自动模式，完全信任 AI
        MANUAL_TITLE_REVIEW = True


# ================= 路径配置 (定海神针) =================
# 获取当前文件(config.py)所在的目录，即项目根目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 图片存放绝对路径
LOCAL_IMAGE_DIR = os.path.join(BASE_DIR, "资料", "image")

# 字体存放绝对路径
LOCAL_FONT_PATH = os.path.join(BASE_DIR, "资料", "fonts", "font.ttf")

# 历史记录文件路径
HISTORY_FILE = os.path.join(BASE_DIR, "history.json")

# 自动创建必要目录
if not os.path.exists(LOCAL_IMAGE_DIR):
    try:
        os.makedirs(LOCAL_IMAGE_DIR, exist_ok=True)
    except:
        pass

# ================= API 密钥配置 =================
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
SEARCH_API_KEY = os.getenv("SEARCH_API_KEY") # Google Search / Serper
TMDB_API_KEY = os.getenv("TMDB_API_KEY")
OMDB_API_KEY = os.getenv("OMDB_API_KEY")     # [新增] OMDB Key
SERPER_API_KEY = os.getenv("SERPER_API_KEY") # [新增] Serper Key

# 小红书 API 地址
API_BASE_URL = "http://localhost:18060/api/v1"

