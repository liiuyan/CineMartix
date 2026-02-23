# 🎬 CineMatrix — 全自动电影种草内容工厂

> 从选题到发布，一键生成小红书电影推荐笔记的 AI 自动化流水线。

---

## 🌟 项目简介

CineMatrix 是一套面向小红书平台的自动化内容生产系统，采用 Agent 分工协作方式完成完整链路：

- 🤖 选题：待办队列优先 + AI 自动漫游
- 📊 元数据：TMDB / OMDB / Serper（豆瓣提取）+ 本地缓存
- ✍️ 文案：单片文案生成、合集批量文案生成
- 🖼️ 视觉：TMDB + 搜索补齐 + CLIP 去重 + 人工素材优先
- 📱 发布：调用本地发布服务自动发帖
- 📁 合集：支持多图素材批处理、长图拼接、发布后归档

---

## 🏗️ 系统架构

```text
main.py
  ├─ run_single_mode()      # 单片流水线
  └─ run_collection_mode()  # 合集流水线

agents/
  ├─ topic.py               # 单片选题
  ├─ meta.py                # 单片元数据获取 + 评论抓取
  ├─ writer.py              # 单片文案
  ├─ visual.py              # 单片配图（manual_materials + 自动兜底）
  ├─ execution.py           # 发布执行
  ├─ collection_topic.py    # 合集目录扫描
  ├─ collection_meta.py     # 合集批量评分
  ├─ collection_writer.py   # 合集正文与标签组装
  └─ collection_visual.py   # 合集渲染与长图拼接

services/
  └─ clip_engine.py         # CLIP 单例引擎

utils.py
  ├─ LLMBrain
  ├─ XHSClient
  ├─ HistoryManager
  ├─ PendingManager
  ├─ calculate_progress()
  └─ clean_tag()
```

---

## 📁 项目结构（当前代码）

```text
little_red/
├── main.py
├── config.py
├── utils.py
├── history.json
├── pending.txt
├── agents/
├── services/
└── 资料/
    ├── image/
    ├── manual_materials/
    ├── collections/
    │   └── _done/
    ├── score/
    │   └── local_scores.json
    └── fonts/
```

---

## 🚀 快速开始

### 1. 环境要求

- Python 3.10+
- 可选：CUDA（用于 CLIP 推理加速）

### 2. 安装依赖

当前仓库未提供 `requirements.txt`，请按代码依赖安装：

```bash
pip install openai requests python-dotenv pillow torch transformers
```

### 3. 配置 `.env`

在项目根目录创建或编辑 `.env`：

```env
LLM_API_KEY=...
LLM_BASE_URL=https://api.deepseek.com
TMDB_API_KEY=...
OMDB_API_KEY=...
SERPER_API_KEY=...
SEARCH_API_KEY=...
```

说明：

- 豆瓣提取优先走 `SERPER_API_KEY`，未配置时回退 `SEARCH_API_KEY`
- 发布服务地址在 `config.py` 固定为 `http://localhost:18060/api/v1`

### 4. 选择运行模式并启动

本项目通过 `config.py` 切换模式（不是命令行参数）：

```python
class Strategy:
    class System:
        RUN_MODE = "single"      # 或 "collection"
```

启动：

```bash
python3 main.py
```

---

## 📖 使用指南

## 单片模式（`RUN_MODE="single"`）

- 先读 `pending.txt` 第一条任务，支持：
  - `电影名`
  - `电影名 | 年份或原名`
  - `电影名 | 年份或原名 | 标题`
- 兼容全角 `｜` 与半角 `|`
- 当提供第三段标题时：
  - 该标题会强制覆盖 AI 标题生成
  - 标题字数必须 `<= 20`，超限会直接熔断
- 若 `pending.txt` 为空，走 AI 自动选题
- 仅发布成功后才会：
  - 写入 `history.json`
  - 从 `pending.txt` 移除对应任务

## 合集模式（`RUN_MODE="collection"`）

### 输入目录规范

在 `资料/collections/` 中创建待处理文件夹：

- 文件夹名：`探讨主题｜笔记标题`
- 图片名支持两种：
  - `电影名｜序号.jpg`
  - `电影名｜年份或原名｜序号.jpg`
- 第二段自动识别规则：
  - 4 位数字且在合理年份区间内：按“年份锁定”
  - 否则按“原名锁定”
- 严格模式：命名不规范会跳过整个合集

示例：

```text
资料/collections/诺兰宇宙｜烧脑天花板片单/
├── 星际穿越｜1.jpg
├── 盗梦空间｜2010｜2.jpg
└── 看不见的客人｜Contratiempo｜3.jpg
```

### 合集正文模式（当前代码）

由 `config.Strategy.Writer.COLLECTION_BODY_MODE` 控制：

- `mode_one`：片单 + 过渡语 + 发散 + CTA + 进度
  - `divergent_text` 上限校验：`<= 400`
- `mode_two`：片单 + 过渡语 + 逐片长评 + CTA + 进度
  - AI 字段：`short_summary`（海报）+ `long_summary`（正文）
  - `long_summary` 强校验区间来自配置（默认 `55-80`）
- `mode_three`（当前默认）：片单 + 核心总结陈词 + CTA + 进度
  - `intro` 上限校验：`<= 200`

---

## ⚙️ 关键配置速查

```python
class Strategy:
    class System:
        RUN_MODE = "collection"
        USE_LOCAL_SCORES = True

    class Visual:
        TARGET_TOTAL_IMAGES = 15
        MIN_COVER_WIDTH = 1000
        CLIP_THRESHOLD = 0.75
        APPEND_DETAIL_IMAGES = True
        DETAIL_IMAGE_TYPE = "original"   # original / rendered

    class Writer:
        MANUAL_TITLE_REVIEW = True
        SHOW_YEAR = False
        SHOW_DOUBAN = True
        SHOW_IMDB = False
        SHOW_ROTTEN_TOMATOES = False
        SHOW_GENRE = False
        SHOW_REGION = False
        COLLECTION_BODY_MODE = "mode_three"
        COLLECTION_SHOW_CTA = True
        COLLECTION_CTA_TEXT = "欢迎在评论区补充你喜欢的电影，后续会持续为大家整理优秀的电影片单"
        COLLECTION_SUMMARY_MIN_LEN = 55
        COLLECTION_SUMMARY_MAX_LEN = 80
        COLLECTION_SUMMARY_REWRITE_RETRIES = 3
```

---

## 🧰 人工素材优先机制

单片模式支持人工素材目录：

```text
资料/manual_materials/<电影名>/
```

存在该目录时，`VisualAgent` 会优先走人工混合模式：

1. 强制获取 TMDB 竖版封面
2. 加载人工素材
3. 不足数量再自动补充剧照

---

## 🚀 发布前提

- 本地发布服务可用：`http://localhost:18060/api/v1`
- 小红书登录态有效（`cookies.json` / 登录服务状态）
- 仓库内含 `xiaohongshu-login-darwin-arm64` 与 `xiaohongshu-mcp-darwin-arm64`

---

## 📦 输出与归档

- 单片图片输出：`资料/image/`
- 合集渲染输出：`资料/collections/<合集>/output/`
- 合集发布成功后自动归档：`资料/collections/_done/`
