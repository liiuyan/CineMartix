# 文件名: utils.py
import json
import os
import requests
import datetime
from openai import OpenAI
import config  # 引用配置

class HistoryManager:
    """🧠 记忆模块"""
    def __init__(self):
        self.filepath = config.HISTORY_FILE
        self.history = self._load()

    def _load(self):
        if not os.path.exists(self.filepath):
            return {}
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}

    def save(self, movie_name):
        """保存电影名和当前日期"""
        self.history[movie_name] = datetime.datetime.now().strftime("%Y-%m-%d")
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump(self.history, f, ensure_ascii=False, indent=2)

    def get_all_movies(self):
        """获取历史上发过的所有电影名单"""
        return list(self.history.keys())

    def get_recent(self, limit=10):
        """[新增] 获取最近发布的 N 部电影 (按日期倒序)"""
        try:
            if not self.history:
                return []
            # self.history 的结构是 {"电影名": "2023-10-27"}
            # 按日期(value)进行倒序排序
            sorted_items = sorted(self.history.items(), key=lambda x: x[1], reverse=True)
            # 只返回电影名列表
            return [item[0] for item in sorted_items[:limit]]
        except Exception as e:
            print(f"⚠️ 获取最近记录失败: {e}")
            return []

    def is_posted(self, movie_name):
        """[新增] 检查是否已发布 (辅助方法)"""
        return movie_name in self.history

class XHSClient:
    """HTTP API 客户端"""
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
    """DeepSeek 大脑"""
    def __init__(self):
        self.client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)

    def think(self, prompt, system_prompt="你是一个专业的小红书电影博主。"):
        try:
            print("   🧠 DeepSeek-Reasoner 正在深度思考中...")
            response = self.client.chat.completions.create(
                model="deepseek-reasoner",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                stream=False
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"❌ LLM 调用失败: {e}")
            return None