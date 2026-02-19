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
    
    class System:
        """[v4.0 新增] 系统运行模式与全局配置"""
        # 运行模式选择: "single" (单片模式) 或 "collection" (合集盘点模式)
        RUN_MODE: str = "single" 
        
        # 本地分数兜底开关 (仅对合集模式有效)
        USE_LOCAL_SCORES: bool = True

    class Visual:
        """视觉策略配置 (VisualAgent)"""
        
        # 目标图片总数 (包含封面 + 剧照)
        # [可调参数] 建议范围 9-18。数量过多可能导致小红书发布失败或处理超时。
        TARGET_TOTAL_IMAGES: int = 15
        
        # [本次新增] 封面清晰度门槛 (单位: px)
        # 只有宽度 >= 此值的海报才会被视为"高清封面"优先录用。
        # 推荐: 1000 (标准高清), 1200 (极致), 700 (最低容忍)
        MIN_COVER_WIDTH: int = 1000
        
        # CLIP 语义去重阈值 (Range: 0.0 - 1.0)
        # 0.75 是经验值：
        # - 大于 0.8: 只有几乎一样的图才会被去重 (宽松)
        # - 小于 0.7: 构图相似的图也会被去重 (严格)
        CLIP_THRESHOLD: float = 0.75
        
        # [v4.0 新增] 合集排版：倒三角视觉平衡折行比例
        # 0.5 为均分。0.6 表示第一行占 60% 宽度，第二行占 40%，形成上宽下窄的高级感。
        TOP_HEAVY_RATIO: float = 0.55

        # [v4.0 新增] 是否在合集长图后追加单部电影的详情图 (总分排版法)
        # True: 列表将呈现 [长图1, 长图2, ..., 单图1, 单图2...]，适合 12 部以内的合集 (极大提升阅读体验)。
        # False: 列表仅呈现 [长图1, 长图2...]，适合 13-18 部的超大合集 (防止触发小红书图片超限报错)。
        APPEND_DETAIL_IMAGES: bool = True
        
        # [v4.0 新增] 追加的单图类型 (仅当 APPEND_DETAIL_IMAGES 为 True 时生效)
        # "rendered": 渲染图 (经过 16:9 居中裁剪，并带有台词、评分、阴影排版的高级图)
        # "original": 原图 (直接使用文件夹里最原始的、无任何文字的纯净剧照，零I/O开销)
        DETAIL_IMAGE_TYPE: str = "original"

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

        # [新增] 1000部阅片计划配置
        # 计划总目标
        PROJECT_TOTAL_COUNT: int = 1000
        # 进度条文案模板 
        # 变量: {current}代表当前第几部, {total}代表总数
        # 建议保留换行符 \n 以确保与正文隔开
        PROGRESS_BAR_TEMPLATE: str = "\n📅 1000部电影推荐计划：{current}/{total}"


# ================= 路径配置 (定海神针) =================
# 获取当前文件(config.py)所在的目录，即项目根目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 图片存放绝对路径 (自动创建)
LOCAL_IMAGE_DIR = os.path.join(BASE_DIR, "资料", "image")

# 字体存放绝对路径
LOCAL_FONT_PATH = os.path.join(BASE_DIR, "资料", "fonts", "font.ttf")

# 历史记录文件路径 (用于去重)
HISTORY_FILE = os.path.join(BASE_DIR, "history.json")

# [v4.0 新增] 合集模式相关路径
COLLECTION_DIR = os.path.join(BASE_DIR, "资料", "collections")

# [修改] 独立 score 文件夹，存放本地分数
SCORE_DIR = os.path.join(BASE_DIR, "资料", "score")
LOCAL_SCORES_FILE = os.path.join(SCORE_DIR, "local_scores.json")

# [v4.0 新增] 字体精确路径配置 (Adobe 官方命名规范)
FONT_TITLE_PATH = os.path.join(BASE_DIR, "资料", "fonts", "思源黑体", "SourceHanSansSC-Bold.otf")
FONT_SCORE_PATH = os.path.join(BASE_DIR, "资料", "fonts", "思源黑体", "SourceHanSansSC-Medium.otf")
FONT_QUOTE_PATH = os.path.join(BASE_DIR, "资料", "fonts", "思源宋体", "SourceHanSerifSC-Bold.otf")
FONT_SUMMARY_PATH = os.path.join(BASE_DIR, "资料", "fonts", "思源宋体", "SourceHanSerifSC-Regular.otf")

# 自动创建必要目录
if not os.path.exists(LOCAL_IMAGE_DIR):
    try:
        os.makedirs(LOCAL_IMAGE_DIR, exist_ok=True)
    except:
        pass

# [v4.0 新增] 自动创建合集存放目录
if not os.path.exists(COLLECTION_DIR):
    try:
        os.makedirs(COLLECTION_DIR, exist_ok=True)
    except:
        pass

# [新增] 自动创建 score 存放目录及初始 JSON
if not os.path.exists(SCORE_DIR):
    try:
        os.makedirs(SCORE_DIR, exist_ok=True)
    except:
        pass

if not os.path.exists(LOCAL_SCORES_FILE):
    try:
        with open(LOCAL_SCORES_FILE, 'w', encoding='utf-8') as f:
            f.write("{}")
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