# 文件名: little_red/main.py
import sys
import config
from utils import HistoryManager, MetaFetcher
# 导入各职能 Agent
from agents.topic import TopicAgent
from agents.writer import WriterAgent
from agents.visual import VisualAgent
from agents.execution import ExecutionAgent

def main():
    """
    🚀 小红书全自动运营主程序 (Main Pipeline)
    
    流程:
    1. TopicAgent: 确定选题 (点播 or 漫游).
    2. MetaFetcher: 获取全球元数据 (身份/票房/评分).
    3. WriterAgent: 撰写文案 (Prompt工程 + 长度熔断).
    4. VisualAgent: 搜集素材 (人工混合 + CLIP去重).
    5. ExecutionAgent: 最终发布 (API调用).
    """
    print("==========================================")
    print("   🚀 Little Red Book Auto-Operator v2.5   ")
    print("==========================================")

    # === Step 1: 选题 (Topic) ===
    topic_agent = TopicAgent()
    movie_name = topic_agent.run()
    
    if not movie_name:
        print("😴 今日无合适选题，程序休眠。")
        return

    # === Step 2: 数据猎取 (Meta) ===
    try:
        fetcher = MetaFetcher()
        # 获取所有评分、票房、年份等元数据
        meta_data = fetcher.fetch_all(movie_name)
    except Exception as e:
        # 若数据猎取阶段熔断 (如无评分)，则终止流程，防止生成垃圾内容
        print(f"❌ 数据猎取失败，终止流程: {e}")
        return

    # === Step 3: 文案创作 (Writer) ===
    writer_agent = WriterAgent()
    note_data = writer_agent.run(movie_name, meta_data)
    
    if not note_data:
        print("❌ 文案生成失败 (可能是字数压缩熔断)，终止流程。")
        return

    # === Step 4: 视觉素材 (Visual) ===
    visual_agent = VisualAgent()
    image_paths = visual_agent.run(movie_name)
    
    if not image_paths or len(image_paths) == 0:
        print("❌ 视觉素材不足 (未找到封面或人工素材缺失)，终止流程。")
        return

    # === [关键] 人工标题审核 (Manual Review) ===
    # 依据 config.Strategy.Writer.MANUAL_TITLE_REVIEW 开关决定是否暂停
    if config.Strategy.Writer.MANUAL_TITLE_REVIEW:
        print("\n" + "="*40)
        print(f"👮 [人工审核拦截] 当前标题: {note_data['title']}")
        print("="*40)
        user_input = input("   回车确认发布，或输入新标题进行修改 (输入 'q' 弃单): ").strip()
        
        if user_input.lower() == 'q':
            print("   🚫 用户手动取消发布。")
            return
        elif user_input:
            note_data['title'] = user_input
            print(f"   ✅ 标题已修改为: {note_data['title']}")

    # === Step 5: 执行发布 (Execution) ===
    execution_agent = ExecutionAgent()
    success = execution_agent.run(note_data, image_paths)
    
    # === 收尾: 记录历史 ===
    if success:
        history = HistoryManager()
        history.save(movie_name)
        print(f"\n🎉 恭喜！《{movie_name}》发布流程圆满完成！")
    else:
        print(f"\n❌ 发布失败，请检查 'xiaohongshu-mcp' 服务日志。")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n🛑 用户强制停止程序。")
        sys.exit(0)
    except Exception as e:
        print(f"\n💥 程序发生未捕获异常: {e}")
        sys.exit(1)