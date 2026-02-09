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
    
    # [修改点] 如果 AI 熔断返回 None，则直接退出程序
    if not movie: 
        print("👋 流程结束。")
        return
    
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
    
    # 5. 记录历史 & 清理待办
    if success:
        history_mgr.save(movie)
        # [修改点] 只有发布成功才删除 pending.txt 中的条目
        topic_agent.finish_pending(movie)
        print("\n🎉 任务完成！所有文件已归档。")
    else:
        print("\n❌ 发布失败，未归档，Pending 任务保留。")

if __name__ == "__main__":
    main()