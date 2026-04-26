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

# [v5.0 新增] 新片速递赛道 Agent
from agents.preview_topic import PreviewTopicAgent
from agents.preview_meta import PreviewMetaFetcher
from agents.preview_writer import PreviewWriterAgent
from agents.preview_visual import PreviewVisualAgent
from services.preview_cache import PreviewCacheManager

# [v5.1 新增] 代理发布赛道 Agent
from agents.proxy_topic import ProxyTopicAgent
from agents.proxy_writer import ProxyWriterAgent

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
    # [修改] 接收元组: (电影名, 年份锁定, 原名锁定, 指定标题)
    movie_name, movie_year, movie_original_title, forced_title = topic_agent.run()
    
    if not movie_name:
        print("😴 今日无合适选题，程序休眠。")
        return

    # === Step 2: 数据猎取 (Meta) ===
    try:
        fetcher = MetaFetcher()
        # 获取所有评分、票房、年份等元数据
        # [修改] 传递年份/原名锁定参数，进行精准锚定
        meta_data = fetcher.fetch_all(
            movie_name,
            specific_year=movie_year,
            specific_original_title=movie_original_title
        )
    except Exception as e:
        # 若数据猎取阶段熔断 (如无评分)，则终止流程，防止生成垃圾内容
        print(f"❌ 数据猎取失败，终止流程: {e}")
        return
    
    # === Step 2.5: 获取评论素材 (Reviews) ===  [重构 板块5]
    # 评论获取能力已从 WriterAgent 迁入 MetaFetcher，由主控统一调度
    reviews = fetcher.fetch_reviews(movie_name, tmdb_id=meta_data.get('tmdb_id'))

    # === Step 3: 文案创作 (Writer) ===
    writer_agent = WriterAgent()
    note_data = writer_agent.run(
        movie_name,
        meta_data,
        reviews=reviews,
        forced_title=forced_title
    )  # [重构 板块5] 传入评论数据 + [本次新增] 可选指定标题
    
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

    # === Step 5: 执行发布 (Execution) ===
    execution_agent = ExecutionAgent()
    success = execution_agent.run(note_data, image_paths, run_mode="single")
    
    # === 收尾: 记录历史 & 清理待办 ===
    if success is None:
        print("\n🚫 已放弃发布，本次任务未入历史且不清理待办。")
        return

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
    final_images = visual_agent.run(
        writer_data['movies'],
        topic_data['folder_path'],
        cover_data=topic_data.get('cover'),
    )
    if not final_images:
        return
        
    # === Step 5: 执行发布 ===
    # [重构 板块7] 标签生成/长度验证已下沉至 CollectionWriterAgent._assemble_note()
    execution_agent = ExecutionAgent()
    success = execution_agent.run(writer_data['note_data'], final_images, run_mode="collection")
    
    # === Step 6: 完美归档 ===
    if success is None:
        print("\n🚫 已放弃发布，合集任务保持原样。")
        return

    if success:
        # [新增] 将合集中的电影全部写入历史字典，打上 collection 标签
        history = HistoryManager()
        for m in writer_data['movies']:
            history.save(m['name'], mode="collection")
            
        topic_agent.finish_collection(topic_data['folder_path'])
        print("\n🎉 合集发布流程圆满完成，工作区已清理归档！")
    else:
        print("\n❌ 发布失败，请检查小红书接口日志。")


def run_preview_mode():
    """
    🆕 新片速递赛道 (Preview Track)

    设计原则:
    1) 与 single/collection 完全解耦，互不影响。
    2) 主控保持薄调度：校验与业务细节下沉到 preview_* Agent。
    3) preview 发布不写 history，不计本地分数缓存。
    """
    print("\n==========================================")
    print("   🆕 [预告模式] Preview Pipeline Start   ")
    print("==========================================")

    sub_mode = getattr(getattr(config.Strategy, 'Preview', None), 'SUB_MODE', 'landscape')
    if sub_mode not in ("landscape", "poster"):
        print(f"❌ [Preview] SUB_MODE 配置非法: {sub_mode}，仅支持 'landscape' 或 'poster'")
        return

    print(f"🧭 [Preview] 当前子模式: {sub_mode}")

    # === Step 1: 任务扫描 ===
    # 从 资料/previews/<sub_mode>/ 扫描“主题｜标题”任务目录与图片序列。
    topic_agent = PreviewTopicAgent()
    topic_data = topic_agent.run()
    if not topic_data:
        return

    # === Step 2: 逐电影采集 + 临时缓存 ===
    # 新规则：按电影逐部完成“元数据 -> hook -> summary”，完整即落缓存；
    # 某一部失败时，只重跑当前失败项，不再让前面已完成电影全部重查。
    cache_mgr = PreviewCacheManager()
    meta_fetcher = PreviewMetaFetcher()
    writer_agent = PreviewWriterAgent()
    cached_count = cache_mgr.count_completed_movies(topic_data)
    if cached_count > 0:
        print(f"📦 [PreviewCache] 命中当前任务缓存，已完成电影 {cached_count} 部。")
    else:
        print("📦 [PreviewCache] 当前任务暂无可复用缓存，将从头开始逐电影处理。")

    completed_movies = []
    total_movies = len(topic_data["movies"])
    for idx, movie in enumerate(topic_data["movies"]):
        movie_name = movie["name"]
        movie_key = movie.get("movie_key", "")
        print(f"\n🧩 [Preview] 正在处理第 {idx + 1}/{total_movies} 部: 《{movie_name}》")

        cached_movie = cache_mgr.get_cached_movie(topic_data, movie_key)
        if cached_movie:
            print(f"   📥 [PreviewCache] 复用单片缓存: {movie_key}")
            # 运行时字段以本次扫描结果为准：顺序、图片路径、锁定信息都不能从旧缓存盲信。
            working_movie = cache_mgr.merge_with_runtime_movie(movie, cached_movie)
            if writer_agent.needs_meta_refresh(working_movie):
                print("   🔄 [PreviewCache] 旧缓存不满足当前配置，正在仅重查当前电影...")
                try:
                    working_movie = meta_fetcher.collect_one(movie)
                except Exception as e:
                    print(f"   ⛔ [熔断] 《{movie_name}》元数据不完整: {e}")
                    return
        else:
            print(f"   🆕 [PreviewCache] 当前电影未命中缓存，开始完整采集: {movie_key or movie_name}")
            try:
                # 未命中缓存时，才走完整外部查询链路。
                working_movie = meta_fetcher.collect_one(movie)
            except Exception as e:
                print(f"   ⛔ [熔断] 《{movie_name}》元数据不完整: {e}")
                return

        finalized_movie = writer_agent.finalize_movie(working_movie)
        if not finalized_movie:
            return

        # 统一在单部电影完成时打印最终采用的噱头，避免不同来源分支重复打印。
        print(f"   ✅ [Preview] 《{movie_name}》最终噱头: {finalized_movie.get('hook', '')}")
        # 单部电影一旦完整，就立刻写缓存；后续若下一部熔断，这一部也无需重查。
        cache_mgr.save_completed_movie(topic_data, finalized_movie)
        print(f"   💾 [PreviewCache] 已写入单片缓存: {movie_key}")
        completed_movies.append(finalized_movie)

    # === Step 3: 文案与标签组装 ===
    # 说明：电影顺序允许变化，因此整篇 note_data 每次都按“当前顺序”重新拼装。
    note_data = writer_agent.build_note(
        topic_data["theme"],
        topic_data["title"],
        completed_movies,
    )
    if not note_data:
        return

    writer_data = {"note_data": note_data, "movies": completed_movies}

    # === Step 4: 视觉处理 ===
    # landscape: 渲染+拼接；poster: 原图直发。
    visual_agent = PreviewVisualAgent()
    final_images = visual_agent.run(
        writer_data["movies"],
        topic_data["folder_path"],
        cover_data=topic_data.get("cover"),
    )
    if not final_images:
        print("❌ [Preview] 视觉处理失败，终止流程。")
        return

    # === Step 5: 发布 ===
    # 复用统一 ExecutionAgent 发布通道。
    execution_agent = ExecutionAgent()
    success = execution_agent.run(writer_data["note_data"], final_images, run_mode="preview")

    # === Step 6: 归档 ===
    # 仅发布成功后归档；preview 不写 history。
    if success is None:
        print("\n🚫 已放弃发布，预告任务保持原样。")
        return

    if success:
        # preview 模式不写历史，不计本地分数
        topic_agent.finish_preview(topic_data["folder_path"])
        print("\n🎉 新片速递发布成功，任务目录已归档。")
    else:
        print("\n❌ 新片速递发布失败，请检查发布服务日志。")

def run_proxy_mode():
    """
    🧩 代理发布赛道 (Proxy Track)

    设计原则:
    1) 只代理发布用户已准备好的图片与文案，不接入电影元数据、历史或渲染链路。
    2) 仍复用统一 ExecutionAgent，保持发布菜单、定时发布和失败收尾语义一致。
    3) 发布成功后才归档任务目录，避免失败或放弃发布时误清理素材。
    """
    print("\n==========================================")
    print("   🧩 [代理模式] Proxy Pipeline Start   ")
    print("==========================================")

    # === Step 1: 扫描代理任务 ===
    topic_agent = ProxyTopicAgent()
    topic_data = topic_agent.run()
    if not topic_data:
        return

    # === Step 2: 读取 note.md 并生成 tags ===
    writer_agent = ProxyWriterAgent()
    note_data = writer_agent.run(topic_data["note_path"])
    if not note_data:
        return

    # === Step 3: 统一发布 ===
    execution_agent = ExecutionAgent()
    success = execution_agent.run(note_data, topic_data["image_paths"], run_mode="proxy")

    # === Step 4: 成功后归档 ===
    if success is None:
        print("\n🚫 已放弃发布，代理任务保持原样。")
        return

    if success:
        topic_agent.finish_proxy(topic_data["folder_path"])
        print("\n🎉 代理模式发布成功，任务目录已归档。")
    else:
        print("\n❌ 代理模式发布失败，请检查发布服务日志。")

def main():
    """
    🔀 小红书全自动运营主程序 (v4.0 路由版)
    """
    # 读取 config 中的硬开关
    run_mode = getattr(getattr(config.Strategy, 'System', None), 'RUN_MODE', 'single')

    if run_mode == "proxy":
        print("🔀 [Router] 检测到 config 设置为【代理模式 (Proxy)】，驶入代理发布赛道...")
        run_proxy_mode()
    elif run_mode == "preview":
        print("🔀 [Router] 检测到 config 设置为【新片速递模式 (Preview)】，驶入预告赛道...")
        run_preview_mode()
    elif run_mode == "collection":
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
