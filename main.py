# 文件名: little_red/main.py
import sys
import config
from utils import HistoryManager  # [重构 板块7] clean_tag 已下沉至 CollectionWriterAgent
from agents.meta import MetaFetcher  # [重构 板块1] 从 agents/meta.py 导入
# 导入各职能 Agent
from agents.topic import TopicAgent
from agents.writer import WriterAgent
from agents.visual import VisualAgent
from agents.execution import ExecutionAgent

# [v4.0 新增] 导入各职能 Agent (合集赛道)
from agents.collection_topic import CollectionTopicAgent
from agents.collection_meta import CollectionMetaFetcher
from agents.collection_writer import CollectionWriterAgent
from agents.collection_visual import CollectionVisualAgent

def run_single_mode():
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
    print("   🚀 Little Red Book Auto-Operator v2.8   ")
    print("==========================================")

    # === Step 1: 选题 (Topic) ===
    topic_agent = TopicAgent()
    # [修改] 接收元组: (电影名, 年份)
    movie_name, movie_year = topic_agent.run()
    
    if not movie_name:
        print("😴 今日无合适选题，程序休眠。")
        return

    # === Step 2: 数据猎取 (Meta) ===
    try:
        fetcher = MetaFetcher()
        # 获取所有评分、票房、年份等元数据
        # [修改] 传递 movie_year，进行精准锚定
        meta_data = fetcher.fetch_all(movie_name, specific_year=movie_year)
    except Exception as e:
        # 若数据猎取阶段熔断 (如无评分)，则终止流程，防止生成垃圾内容
        print(f"❌ 数据猎取失败，终止流程: {e}")
        return
    
    # === Step 2.5: 获取评论素材 (Reviews) ===  [重构 板块5]
    # 评论获取能力已从 WriterAgent 迁入 MetaFetcher，由主控统一调度
    reviews = fetcher.fetch_reviews(movie_name, tmdb_id=meta_data.get('tmdb_id'))

    # === Step 3: 文案创作 (Writer) ===
    writer_agent = WriterAgent()
    note_data = writer_agent.run(movie_name, meta_data, reviews=reviews)  # [重构 板块5] 传入评论数据
    
    if not note_data:
        print("❌ 文案生成失败 (可能是字数压缩熔断)，终止流程。")
        return

    # === Step 4: 视觉素材 (Visual) ===
    visual_agent = VisualAgent()
    # [Plan B] 传递 TMDB ID，确保视觉素材与选题一致
    target_id = meta_data.get('tmdb_id')
    image_paths = visual_agent.run(movie_name, tmdb_id=target_id)
    
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
    
    # === 收尾: 记录历史 & 清理待办 ===
    if success:
        history = HistoryManager()
        # [修改] 增加 mode="single" 标签
        history.save(movie_name, mode="single")
        
        # [Fix] 核心修复：调用 TopicAgent 移除 pending 列表中的对应项
        # [修改] 传递 movie_year (尽管 topic_agent 内部可能只用 fuzzy match，但为了接口一致性)
        topic_agent.finish_pending(movie_name, movie_year)
        
        print(f"\n🎉 恭喜！《{movie_name}》发布流程圆满完成！")
    else:
        print(f"\n❌ 发布失败，请检查 'xiaohongshu-mcp' 服务日志。")

def run_collection_mode():
    """
    🚂 合集赛道 (Collection Track)
    v4.0 完整流水线 (包含 Fail-Fast 铁血熔断机制)。
    """
    print("\n==========================================")
    print("   🚂 [合集模式] Collection Pipeline Start   ")
    print("==========================================")
    
    # === Step 1: 扫描文件夹 ===
    topic_agent = CollectionTopicAgent()
    topic_data = topic_agent.run()
    if not topic_data:
        return
        
    # === Step 2: 批量查分 ===
    meta_fetcher = CollectionMetaFetcher()
    movies_with_scores = meta_fetcher.run(topic_data['movies'])
    
    # === Step 3: AI 撰写文案与发散 ===
    writer_agent = CollectionWriterAgent()
    writer_data = writer_agent.run(topic_data['theme'], topic_data['title'], movies_with_scores)
    if not writer_data:
        return
        
    # === Step 4: 渲染 16:27 长图海报 ===
    visual_agent = CollectionVisualAgent()
    final_images = visual_agent.run(writer_data['movies'], topic_data['folder_path'])
    if not final_images:
        return
        
    # === Step 5: 执行发布 ===
    # [重构 板块7] 标签生成/长度验证已下沉至 CollectionWriterAgent._assemble_note()
    execution_agent = ExecutionAgent()
    success = execution_agent.run(writer_data['note_data'], final_images)
    
    # === Step 6: 完美归档 ===
    if success:
        # [新增] 将合集中的电影全部写入历史字典，打上 collection 标签
        history = HistoryManager()
        for m in writer_data['movies']:
            history.save(m['name'], mode="collection")
            
        topic_agent.finish_collection(topic_data['folder_path'])
        print("\n🎉 合集发布流程圆满完成，工作区已清理归档！")
    else:
        print("\n❌ 发布失败，请检查小红书接口日志。")

def main():
    """
    🔀 小红书全自动运营主程序 (v4.0 路由版)
    """
    # 读取 config 中的硬开关
    run_mode = getattr(getattr(config.Strategy, 'System', None), 'RUN_MODE', 'single')

    if run_mode == "collection":
        print("🔀 [Router] 检测到 config 设置为【合集模式 (Collection)】，驶入合集赛道...")
        run_collection_mode()
    else:
        print("🔀 [Router] 检测到 config 设置为【单片模式 (Single)】，驶入常规赛道...")
        run_single_mode()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n🛑 用户强制停止程序。")
        sys.exit(0)
    except Exception as e:
        print(f"\n💥 程序发生未捕获异常: {e}")
        sys.exit(1)