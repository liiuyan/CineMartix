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
        # 运行模式选择: "single" (单片模式) / "collection" (合集盘点模式) / "preview" (新片速递模式)
        RUN_MODE: str = "preview" 
        
        # [新增] 发布前决策菜单总开关
        # True: 启用发布前菜单（single=4选项，collection/preview=3选项）
        # False: 直接立即发布（不弹菜单）
        ENABLE_PUBLISH_DECISION_MENU: bool = False

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

        # [本次新增] 标题 Emoji 开关
        # True: 允许标题包含 Emoji (如 "🎬 教父")
        # False: 标题必须是纯文字 (如 "教父：黑帮史诗")，且降级策略中不包含删除 Emoji 步骤。
        ENABLE_TITLE_EMOJI: bool = True

        # =========================================================
        # [新增] 合集模式：片单拼接内容控制开关
        # =========================================================
        SHOW_YEAR: bool = False         # [本次新增] 是否在片单后追加电影年份
        SHOW_DOUBAN: bool = True       # 是否在片单后追加豆瓣评分
        SHOW_IMDB: bool = False        # 是否在片单后追加IMDb评分
        SHOW_ROTTEN_TOMATOES: bool = False  # [本次新增] 是否在片单后追加烂番茄评分
        SHOW_GENRE: bool = False       # 是否在片单后追加电影类型
        SHOW_REGION: bool = False       # 是否在片单后追加国家/地区

        # [新增] 合集模式正文拼接模式 (仅 collection 模式使用)
        # mode_one: 片单 + 开场白 + 发散 + 引导语 + 进度
        # mode_two: 片单 + 开场白 + 简介列表 + 引导语 + 进度
        # mode_three: 片单 + 开场白 + 引导语 + 进度
        COLLECTION_BODY_MODE: str = "mode_one"

        # [新增] 合集模式正文引导语控制 (仅 collection 模式使用)
        COLLECTION_SHOW_CTA: bool = True
        COLLECTION_CTA_TEXT: str = "欢迎在评论区补充你喜欢的电影，后续会持续为大家整理优秀的电影片单"

        # [新增] mode_two 的电影简介长度与重写控制 (仅 collection 模式使用)
        COLLECTION_SUMMARY_MIN_LEN: int = 55
        COLLECTION_SUMMARY_MAX_LEN: int = 80
        COLLECTION_SUMMARY_REWRITE_RETRIES: int = 3

        # [新增] mode_one 的主题发散字数控制 (仅 collection 模式使用)
        # 不在该区间会触发重写
        COLLECTION_DIVERGENT_MIN_LEN: int = 250
        COLLECTION_DIVERGENT_MAX_LEN: int = 600

        # [新增] 1000部阅片计划配置
        # 计划总目标
        PROJECT_TOTAL_COUNT: int = 1000
        # 进度条文案模板 
        # 变量: {current}代表当前第几部, {total}代表总数
        # 建议保留换行符 \n 以确保与正文隔开
        PROGRESS_BAR_TEMPLATE: str = "\n📅 1000部电影推荐计划：{current}/{total}"

    class Preview:
        """[v5.0 新增] 新片速递模式配置 (Preview Mode)"""
        # 子模式:
        # - "landscape": 读取 资料/previews/landscape 下的任务，执行横图渲染+拼接发布
        # - "poster": 读取 资料/previews/poster 下的任务，竖版海报按序直发(不做渲染)
        # 建议:
        # - 你提供横版剧照时用 landscape
        # - 你提供竖版海报时用 poster
        SUB_MODE: str = "landscape"

        # ================= 文案展示策略 =================
        # 说明：以下配置只影响 preview 模式，不会影响 single/collection。
        # 是否展示“每部电影简介块”
        # True: 会对简介做 SUMMARY_MIN_LEN-SUMMARY_MAX_LEN 字重写与强校验；任何一部不达标即熔断整夹
        # False: 不展示简介块，同时不因简介缺失而熔断
        SHOW_SUMMARY_BLOCK: bool = True

        # 是否在正文末尾显示 CTA 引导语
        # True: 显示 CTA_TEXT
        # False: 不显示 CTA_TEXT
        SHOW_CTA: bool = True

        # CTA 文案内容 (SHOW_CTA=True 时生效)
        CTA_TEXT: str = "欢迎大家在评论区留下你期待电影的名字～"

        # ================= preview 片单附加信息开关 =================
        # 控制“电影名后括号信息”是否展示，默认全关闭。
        # 示例: 1️⃣电影名 (上映 2026-01-01 | 上映地 中国内地 | 剧情/犯罪 | 美国)
        SHOW_LIST_RELEASE_DATE: bool = False    # 是否显示上映日期
        SHOW_LIST_RELEASE_REGION: bool = False  # 是否显示上映地
        SHOW_LIST_GENRES: bool = False         # 是否显示电影类型
        SHOW_LIST_REGION: bool = False          # 是否显示国家/地区

        # ================= 外部检索预算(按单部电影计数) =================
        # Serper 最多请求次数。
        # 例如设为 5：每部电影最多向 Serper 发起 5 次搜索请求（达到后停止）。
        # 次数越高，补齐信息机会越大，但 API 消耗更高。
        SERPER_MAX_QUERIES_PER_MOVIE: int = 5

        # Gemini(Google Grounding)最多兜底次数。
        # 仅当“必填字段仍缺失”时才会触发 Gemini 补齐；建议 <=3 控成本。
        GEMINI_MAX_GROUNDING_PER_MOVIE: int = 3

        # Gemini 噱头补写尝试次数（独立于硬必填补齐）。
        # 触发时机：硬必填补齐流程结束后，若 hook 仍无效则执行。
        # 说明：补写失败不会熔断，后续仍会走本地噱头兜底生成与 Writer 校验重写链路。
        GEMINI_HOOK_ATTEMPTS: int = 1

        # ================= Serper 搜索白名单 =================
        # 只保留这些域名的搜索结果，避免低质量来源污染信息。
        # 注意：白名单用于“过滤结果质量”，不减少一次 Serper 请求本身的计费。
        # 如需扩展来源，直接在列表中追加域名字符串即可。
        SERPER_DOMAIN_WHITELIST: list[str] = [
            "imdb.com",
            "douban.com",
            "boxofficemojo.com",
            "the-numbers.com",
            "deadline.com",
            "variety.com",
            "hollywoodreporter.com",
            "youtube.com",
        ]

        # ================= 噱头文案约束 =================
        # 噱头长度区间(单位: 字符)。超出范围会视为无效并触发重写/熔断。
        # 你当前确认规则：最短 6，最长 22。
        HOOK_MIN_LEN: int = 6
        HOOK_MAX_LEN: int = 22

        # 噱头生成重试次数（默认 5 次）。
        # 说明：每次失败都会带上“上一轮不合格原因”反馈给模型，直到达标或耗尽重试次数。
        HOOK_RETRY_TIMES: int = 5

        # ================= 简介重写约束 =================
        # 仅当 SHOW_SUMMARY_BLOCK=True 时生效。
        # SUMMARY_TARGET_MIN_LEN/SUMMARY_TARGET_MAX_LEN: 生成目标区间（给 AI 的写作要求）
        # SUMMARY_MIN_LEN/SUMMARY_MAX_LEN: 校验通过区间（仅超出才触发重写）
        SUMMARY_TARGET_MIN_LEN: int = 60
        SUMMARY_TARGET_MAX_LEN: int = 70
        # 简介必须落在 [SUMMARY_MIN_LEN, SUMMARY_MAX_LEN]，否则重写；
        # 超过 SUMMARY_REWRITE_RETRIES 仍不达标时，熔断整夹并停止发布。
        SUMMARY_MIN_LEN: int = 55
        SUMMARY_MAX_LEN: int = 80
        SUMMARY_REWRITE_RETRIES: int = 6

        # ================= 预览模式图片发布策略 =================
        # 仅 landscape 子模式生效。
        # APPEND_RENDERED_DETAILS:
        # - True: 在长图/余数图后，追加每部电影渲染后的 16:9 单图
        # - False: 不追加渲染单图
        APPEND_RENDERED_DETAILS: bool = False

        # APPEND_ORIGINAL_IMAGES:
        # - True: 在最后追加你放入任务文件夹的原图
        # - False: 不追加原图
        # 说明：poster 子模式本身就是直发原图，此开关仅影响 landscape 子模式。
        APPEND_ORIGINAL_IMAGES: bool = True

        # ================= 封面水印英文名判定重试 =================
        # 说明：preview 封面渲染时，会把“电影原名”批量发给 DeepSeek 判定是否应显示英文行。
        # 若调用失败或返回不可解析 JSON，会按该次数自动重试；重试后仍失败则回退为“不显示英文行”。
        COVER_EN_NAME_RETRY_TIMES: int = 3

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

# [v5.0 新增] 新片速递模式相关路径
# PREVIEW_DIR: 新片速递根目录
# PREVIEW_LANDSCAPE_DIR: landscape 子模式任务目录
# PREVIEW_POSTER_DIR: poster 子模式任务目录
# PREVIEW_DONE_DIR: 发布成功后的归档目录
PREVIEW_DIR = os.path.join(BASE_DIR, "资料", "previews")
PREVIEW_LANDSCAPE_DIR = os.path.join(PREVIEW_DIR, "landscape")
PREVIEW_POSTER_DIR = os.path.join(PREVIEW_DIR, "poster")
PREVIEW_DONE_DIR = os.path.join(PREVIEW_DIR, "_done")

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

# [v5.0 新增] 自动创建新片速递目录结构
# 目录结构:
# 资料/previews/
#   ├─ landscape/   (横图任务)
#   ├─ poster/      (竖海报任务)
#   └─ _done/
#      ├─ landscape/  (横图任务归档)
#      └─ poster/     (竖海报任务归档)
for _dir in [
    PREVIEW_DIR,
    PREVIEW_LANDSCAPE_DIR,
    PREVIEW_POSTER_DIR,
    PREVIEW_DONE_DIR,
    os.path.join(PREVIEW_DONE_DIR, "landscape"),
    os.path.join(PREVIEW_DONE_DIR, "poster"),
]:
    if not os.path.exists(_dir):
        try:
            os.makedirs(_dir, exist_ok=True)
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
# 必须在 .env 文件中配置这些 Key（项目启动时会读取）
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
SEARCH_API_KEY = os.getenv("SEARCH_API_KEY") # 搜索 API 兼容 Key (可作为 SERPER_API_KEY 备用)
TMDB_API_KEY = os.getenv("TMDB_API_KEY")
OMDB_API_KEY = os.getenv("OMDB_API_KEY")     # [新增] OMDB Key (用于烂番茄/MTC分数)
SERPER_API_KEY = os.getenv("SERPER_API_KEY") # Serper 搜索 Key (preview 模式用于检索 IMDb/豆瓣/宣发信息)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") # Gemini Key (preview 模式用于 Google Grounding 兜底补齐字段)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash") # Gemini 模型名，默认 gemini-2.5-flash

# 小红书 API 地址 (本地服务)
API_BASE_URL = "http://localhost:18060/api/v1"
