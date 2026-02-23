# 文件名: agents/execution.py
from utils import XHSClient

class ExecutionAgent:
    """🚀 执行 Agent"""
    def __init__(self):
        self.client = XHSClient()

    def run(self, note_data, image_paths):
        print("\n🚀 [5/5 ExecutionAgent] 准备发布...")
        
        status = self.client.call_tool("check_login_status")
        is_logged_in = False
        if isinstance(status, dict) and (status.get("is_logged_in") is True or status.get("logged_in") is True):
            is_logged_in = True
        elif status is True:
            is_logged_in = True
            
        if not is_logged_in:
            print(f"❌ 未登录 (API返回: {status})")
            return False 

        if not image_paths:
            print("❌ 无图片")
            return False

        print(f"   标题: {note_data['title']}")
        print(f"   图片数: {len(image_paths)}")
        
        result = self.client.call_tool("publish_content", {
            "title": note_data['title'],
            "content": note_data['content'],
            "images": image_paths, 
            "tags": note_data.get('tags', [])
        })
        
        if result:
            print(f"✅ 发布成功！")
            return True
        return False
