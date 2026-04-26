# 文件名: little_red/utils.py
import json
import os
import shutil  # [重构 板块3] 新增: PendingManager.archive_folder 需要
import requests
import datetime
import re # [保留] 用于正则处理
from openai import OpenAI
import config  # 引用配置

class HistoryManager:
    """🧠 记忆模块: 负责历史记录的读写，防止重复选题。"""
    def __init__(self):
        self.filepath = config.HISTORY_FILE
        self.history = self._load()

    def _load(self):
        if not os.path.exists(self.filepath):
            return {}
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # [平滑迁移] 兼容旧版的 {"电影名": "日期"} 格式
                migrated = {}
                for k, v in data.items():
                    if isinstance(v, str):
                        migrated[k] = {
                            "first_publish_date": v,
                            "published_modes": ["single"] # 历史老数据默认当做 single 处理
                        }
                    else:
                        migrated[k] = v
                return migrated
        except:
            return {}

    def save(self, movie_name, mode="single"):
        """[重塑] 保存电影名、首次发布日期，并记录发布模式(single/collection)"""
        now_str = datetime.datetime.now().strftime("%Y-%m-%d")
        if movie_name in self.history:
            # 若已存在，则追加模式标签 (去重机制)
            if mode not in self.history[movie_name].get("published_modes", []):
                self.history[movie_name].setdefault("published_modes", []).append(mode)
        else:
            # 若不存在，则新建全局记录
            self.history[movie_name] = {
                "first_publish_date": now_str,
                "published_modes": [mode]
            }
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(self.history, f, ensure_ascii=False, indent=2)

    def get_all_movies(self):
        """获取历史上发过的所有电影名单 (全局合并去重总数直接等于 len(keys))"""
        return list(self.history.keys())

    def get_recent(self, limit=10):
        """[新增] 获取最近发布的 N 部电影 (按日期倒序)"""
        try:
            if not self.history:
                return []
            # self.history 的结构已变，按 first_publish_date 进行倒序排序
            sorted_items = sorted(
                self.history.items(), 
                key=lambda x: x[1].get("first_publish_date", ""), 
                reverse=True
            )
            return [item[0] for item in sorted_items[:limit]]
        except Exception as e:
            print(f"⚠️ 获取最近记录失败: {e}")
            return []

    def is_posted(self, movie_name):
        """[全局查重] 检查是否在任一模式下发布过"""
        return movie_name in self.history
        
    def has_posted_in_mode(self, movie_name, mode):
        """[精准查重] 检查是否在指定模式下发布过"""
        if not self.is_posted(movie_name):
            return False
        return mode in self.history[movie_name].get("published_modes", [])

class XHSClient:
    """HTTP API 客户端: 封装小红书发布接口调用"""
    def __init__(self):
        self.base_url = config.API_BASE_URL

    def call_tool(self, tool_name, args=None):
        if args is None: args = {}
        url_map = {
            "check_login_status": ("/login/status", "GET"),
            "publish_content": ("/publish", "POST"),
        }
        
        if tool_name not in url_map:
            print(f"❌ 未知工具: {tool_name}")
            return None

        endpoint, method = url_map[tool_name]
        url = f"{self.base_url}{endpoint}"

        try:
            # 统一入口：把“工具名 -> HTTP 接口”映射收敛到这里，业务层只关心 tool_name。
            if method == "GET":
                resp = requests.get(url, params=args)
            else:
                resp = requests.post(url, json=args)
            
            resp.raise_for_status()
            res_json = resp.json()
            
            if res_json.get("success") is True:
                return res_json.get("data", res_json)
            if "code" in res_json and res_json["code"] != 0:
                print(f"❌ API错误: {res_json.get('error') or res_json.get('message')}")
                return None
            return res_json.get("data", res_json)
        except Exception as e:
            print(f"❌ 连接服务失败: {e}")
            return None

class LLMBrain:
    """统一 LLM 大脑：按配置切换 DeepSeek / Qwen 调用逻辑"""
    def __init__(self):
        provider = str(
            getattr(getattr(config.Strategy, "System", None), "LLM_PROVIDER", "deepseek")
        ).strip().lower()
        if provider not in {"deepseek", "qwen"}:
            print(f"⚠️ 未知 LLM_PROVIDER: {provider}，已回退为 deepseek。")
            provider = "deepseek"

        self.provider = provider
        self.client = None
        if self.provider == "deepseek":
            self.client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)
        elif self.provider == "qwen" and config.QWEN_API_KEY:
            self.client = OpenAI(
                api_key=config.QWEN_API_KEY,
                base_url=self._normalize_qwen_base_url(config.QWEN_BASE_URL),
            )

    def _normalize_qwen_base_url(self, base_url):
        """兼容配置完整 chat/completions URL 或 compatible-mode 基础路径。"""
        url = str(base_url or "").strip().rstrip("/")
        if not url:
            return "https://dashscope.aliyuncs.com/compatible-mode/v1"

        suffix = "/chat/completions"
        if url.endswith(suffix):
            return url[:-len(suffix)]
        return url

    def think(self, prompt, system_prompt="你是一个专业的小红书电影博主。"):
        if self.provider == "qwen":
            return self._think_with_qwen(prompt, system_prompt)
        return self._think_with_deepseek(prompt, system_prompt)

    def _think_with_deepseek(self, prompt, system_prompt):
        if not config.LLM_API_KEY:
            print("❌ DeepSeek 调用失败: 缺少 LLM_API_KEY")
            return None

        if not self.client:
            print("❌ DeepSeek 调用失败: DeepSeek 客户端初始化失败")
            return None

        try:
            # DeepSeek V4 官方仍走 OpenAI 兼容 chat/completions；模型名集中在 config.py，便于后续升级。
            print(f"   🧠 DeepSeek ({config.LLM_MODEL}) 正在思考中...")
            response = self.client.chat.completions.create(
                model=config.LLM_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                stream=False,
                reasoning_effort=config.LLM_REASONING_EFFORT,
                extra_body={"thinking": {"type": config.LLM_THINKING_TYPE}},
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"❌ DeepSeek 调用失败: {e}")
            return None

    def _think_with_qwen(self, prompt, system_prompt):
        if not config.QWEN_API_KEY:
            print("❌ Qwen 调用失败: 缺少 QWEN_API_KEY")
            return None

        if not self.client:
            print("❌ Qwen 调用失败: Qwen 客户端初始化失败")
            return None

        try:
            # 统一走 OpenAI 兼容客户端，规避 requests 在当前环境下的不稳定链路。
            print("   🧠 Qwen 正在联网思考中...")
            response = self.client.chat.completions.create(
                model=config.QWEN_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                stream=False,
                extra_body={
                    "enable_search": True,
                    "search_options": {
                        "forced_search": True,
                    },
                },
                timeout=120,
            )
            choices = getattr(response, "choices", None) or []
            if not choices:
                print("❌ Qwen 调用失败: 未返回 choices")
                return None

            message = getattr(choices[0], "message", None)
            content = getattr(message, "content", None)
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                text_parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("text"):
                        text_parts.append(str(item["text"]))
                if text_parts:
                    return "\n".join(text_parts)

            print("❌ Qwen 调用失败: 返回内容为空")
            return None
        except Exception as e:
            print(f"❌ Qwen 调用失败: {e}")
            return None


# ==========================================
# [重构 板块3] 任务队列管理器 (PendingManager)
# ==========================================
class PendingManager:
    """
    📋 任务队列管理器 (PendingManager)
    
    统一负责:
    1. pending.txt 的读取、解析、删除 (单片模式的点播队列)
    2. 合集文件夹的归档移动 (合集模式的完成收尾)
    
    设计目的:
    作为公共基础设施，供 TopicAgent / CollectionTopicAgent / main.py 调用，
    避免文件 I/O 操作散落在多个 Agent 中。
    
    当前状态: 板块3 预埋，板块4 将正式接入消费方。
    """
    def __init__(self):
        self.pending_file = os.path.join(config.BASE_DIR, "pending.txt")

    def read_next(self):
        """
        读取 pending.txt 中的第一条有效任务。
        支持格式 (兼容全角/半角分隔符):
        1) 电影名
        2) 电影名 | 年份或原名
        3) 电影名 | 年份或原名 | 标题
           - 标题中允许继续包含 | 或 ｜，解析时只切前两个分隔符。
        
        Returns:
            tuple | None: 成功返回 (movie_name, specific_year, specific_original_title, forced_title)
                          无任务时返回 None
        """
        if not os.path.exists(self.pending_file):
            return None

        try:
            with open(self.pending_file, "r", encoding="utf-8") as f:
                lines = f.readlines()

            valid_lines = [line for line in lines if line.strip()]
            if not valid_lines:
                return None

            raw_line = valid_lines[0].strip()
            normalized = raw_line.replace("｜", "|")
            # [本次新增] 只切前两个分隔符，允许标题中继续出现 "|"。
            parts = [p.strip() for p in normalized.split("|", 2)]

            # Case 1: 仅电影名
            if len(parts) == 1:
                movie_name = parts[0]
                return movie_name, None, None, None

            # Case 2/3: 电影名 + 锁定信息 + (可选标题)
            movie_name = parts[0]
            lock_hint = parts[1] if len(parts) >= 2 else ""
            forced_title = parts[2] if len(parts) == 3 else None

            if not movie_name:
                print(f"⚠️ pending 第一条任务格式异常（缺少电影名）: {raw_line}")
                return None

            specific_year = None
            specific_original_title = None
            if lock_hint:
                # [本次新增] 自动识别第二段：四位数字为年份，否则视为原名
                if len(lock_hint) == 4 and lock_hint.isdigit():
                    specific_year = lock_hint
                else:
                    specific_original_title = lock_hint

            # 标题允许为空串时回退为 None
            if forced_title is not None and not forced_title:
                forced_title = None

            return movie_name, specific_year, specific_original_title, forced_title

        except Exception as e:
            print(f"⚠️ 读取 pending.txt 出错: {e}")
            return None

    def remove(self, movie_name):
        """
        从 pending.txt 中移除已完成的任务。
        匹配逻辑: 只要第一行的开头包含 movie_name 即视为匹配 (兼容有/无年份)。
        
        Args:
            movie_name (str): 已完成的电影名
        """
        if not os.path.exists(self.pending_file):
            return

        try:
            with open(self.pending_file, "r", encoding="utf-8") as f:
                lines = f.readlines()

            valid_lines = [line for line in lines if line.strip()]

            if valid_lines:
                first_line = valid_lines[0].strip()
                # 仅按“首条任务”删除，维持 pending 的队列语义（FIFO）。
                # 这里保留 startswith 兼容历史格式（电影名 / 电影名|年份 / 电影名|原名|标题）。
                if first_line.startswith(movie_name):
                    print(f"🗑️ [Pending] 从待办列表中移除已发布的: 《{first_line}》")
                    remaining_lines = valid_lines[1:]
                    with open(self.pending_file, "w", encoding="utf-8") as f:
                        f.writelines(remaining_lines)

        except Exception as e:
            print(f"⚠️ 更新 pending.txt 失败: {e}")

    def archive_folder(self, folder_path, done_dir):
        """
        [合集归档] 将文件夹整体移动到归档目录。
        
        Args:
            folder_path (str): 要归档的源文件夹绝对路径
            done_dir (str): 归档目标目录绝对路径
        """
        try:
            folder_name = os.path.basename(folder_path)
            target_path = os.path.join(done_dir, folder_name)

            # 防覆盖: 如果目标已存在同名文件夹，先删除旧的
            # 语义：归档目录始终保留“本次最新产物”，避免旧残留误导排查。
            if os.path.exists(target_path):
                shutil.rmtree(target_path)

            shutil.move(folder_path, done_dir)
            print(f"\n📦 [归档] 合集集装箱已整体移至: _done/{folder_name}")
        except Exception as e:
            print(f"\n⚠️ 归档失败: {e}")


# ==========================================
# [重构 板块2] 公共进度条计算器
# ==========================================
def calculate_progress(movie_names):
    """
    📊 公共进度条计算器 (板块2 归一)
    
    统一计算 "1000部阅片计划" 的当前进度。
    消除 writer.py 和 collection_writer.py 中各自重复的进度条计算逻辑。
    
    Args:
        movie_names (str | list): 
            - 单片模式: 传入电影名字符串 (如 "星际穿越")
            - 合集模式: 传入电影名列表 (如 ["星际穿越", "盗梦空间", ...])
    
    Returns:
        str: 格式化的进度条字符串 (如 "\\n📅 1000部电影推荐计划：42/1000")
             失败时返回空字符串 ""，不影响主流程
    """
    try:
        # 统一转为列表处理
        if isinstance(movie_names, str):
            movie_names = [movie_names]

        history = HistoryManager()
        past_count = len(history.get_all_movies())

        # 计算本批次中有多少部是全新的 (未在任何模式下发布过)
        new_count = sum(1 for name in movie_names if not history.is_posted(name))

        current_index = past_count + new_count
        total_target = config.Strategy.Writer.PROJECT_TOTAL_COUNT
        progress_str = config.Strategy.Writer.PROGRESS_BAR_TEMPLATE.format(
            current=current_index,
            total=total_target
        )

        # 差异化日志: 单片 vs 合集
        if len(movie_names) == 1:
            print(f"   📊 [Project] 进度计算: {current_index}/{total_target} (已去重)")
        else:
            print(f"   📊 [Project] 进度计算: {past_count} (历史) + {new_count} (新增) = {current_index}/{total_target}")

        return progress_str
    except Exception as e:
        print(f"   ⚠️ 进度条生成失败 (非致命): {e}")
        return ""


# ==========================================
# [新增] 标签清洗与泛流量截流器 (Tag Cleaner)
# ==========================================
def clean_tag(raw_str: str) -> str:
    """
    [新增] 标签清洗器 (Tag Cleaner)
    核心策略：主标题截断 + 尾号抹除 (泛流量截流)
    解决小红书标点符号断层及续集流量分散问题。
    """
    if not raw_str:
        return ""
        
    # 预处理：去掉书名号等绝对不能出现在 tag 里的包裹符号
    raw_str = raw_str.replace("《", "").replace("》", "")
        
    # 1. 符号截断：遇到冒号、破折号、空格、括号等直接截断，取前半截 (主 IP)
    # 注意包含了全角和半角的标点符号
    parts = re.split(r'[:：\-——(（\s]', raw_str)
    base_name = parts[0] if parts else raw_str
    
    # 2. 尾号抹除：去掉末尾的数字 (如 银翼杀手2049 -> 银翼杀手, 指环王3 -> 指环王)
    cleaned_name = re.sub(r'\d+$', '', base_name)
    
    # 3. 防误杀兜底：如果抹除数字后变成了空字符串 (说明原片名就是纯数字，如 1917 或 2012)，则退回 base_name
    if not cleaned_name:
        return base_name
        
    return cleaned_name


# ==========================================
# [新增] Prompt 语料文件加载器
# ==========================================
def load_prompt_text(relative_path: str) -> str:
    """
    读取 prompts 目录下的文本语料。
    设计要求：文件缺失时直接抛异常，触发上游熔断。
    """
    abs_path = os.path.join(config.BASE_DIR, relative_path)
    if not os.path.exists(abs_path):
        raise FileNotFoundError(f"Prompt 文件缺失: {abs_path}")

    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception as e:
        raise RuntimeError(f"读取 Prompt 文件失败: {abs_path} | {e}") from e


def load_prompt_lines(relative_path: str) -> list[str]:
    """
    按行读取文本语料并忽略空行。
    """
    text = load_prompt_text(relative_path)
    return [line.strip() for line in text.splitlines() if line.strip()]
