# 文件名: little_red/main.py
import os
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

from agents.topic import TopicAgent
from agents.writer import WriterAgent
from agents.visual import VisualAgent
from agents.execution import ExecutionAgent
from utils import HistoryManager, MetaFetcher # 引入新工具

def main():
    print("🤖 === 小红书电影号自动运营 (v2.1 混合增强版) === ")
    
    # 0. 初始化
    history_mgr = HistoryManager()
    
    # 1. 选题
    topic_agent = TopicAgent()
    movie = topic_agent.run()
    
    if not movie: 
        print("👋 流程结束。")
        return
    
    # [新增] 1.5 数据猎手: 获取真实评分
    # 这是连接 Topic 和 Writer 的桥梁
    meta_fetcher = MetaFetcher()
    meta_data = meta_fetcher.fetch_all(movie)
    
    # 2. 创作 (传入 meta_data)
    writer_agent = WriterAgent()
    note_data = writer_agent.run(movie, meta_data) # 传入
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
        topic_agent.finish_pending(movie)
        print("\n🎉 任务完成！所有文件已归档。")
    else:
        print("\n❌ 发布失败，未归档，Pending 任务保留。")

if __name__ == "__main__":
    main()