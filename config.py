# 文件名: config.py
import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

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
SEARCH_API_KEY = os.getenv("SEARCH_API_KEY")
TMDB_API_KEY = os.getenv("TMDB_API_KEY")

# 小红书 API 地址
API_BASE_URL = "http://localhost:18060/api/v1"

# ================= 算法参数 =================
# CLIP 语义去重阈值 (越接近1越严格)
CLIP_THRESHOLD = 0.75

# 标题重写最大重试次数
MAX_TITLE_RETRIES = 3