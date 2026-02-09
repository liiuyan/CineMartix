# 文件名: main.py
import os
# 设置 Hugging Face 镜像地址
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

from agents.topic import TopicAgent
from agents.writer import WriterAgent
from agents.visual import VisualAgent
from agents.execution import ExecutionAgent
from utils import HistoryManager

def main():
    print("🤖 === 小红书电影号自动运营 (模块化企业版) === ")
    
    # 0. 初始化
    history_mgr = HistoryManager()
    
    # 1. 选题
    topic_agent = TopicAgent()
    movie = topic_agent.run()
    if not movie: return
    
    # 2. 创作
    writer_agent = WriterAgent()
    note_data = writer_agent.run(movie)
    if not note_data: return
    
    # 3. 视觉 (含 CLIP 去重)
    visual_agent = VisualAgent()
    imgs = visual_agent.run(movie)
    if not imgs: return
    
    # 4. 执行发布
    exec_agent = ExecutionAgent()
    success = exec_agent.run(note_data, imgs)
    
    # 5. 记录历史
    if success:
        history_mgr.save(movie)
        print("\n🎉 任务完成！所有文件已归档。")

if __name__ == "__main__":
    main()