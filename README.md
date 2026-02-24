# 🎬 CineMatrix — 全自动电影内容生产流水线

> 从选题、取数、文案、视觉到发布的一体化小红书自动化系统。

---

## 🌟 项目简介

CineMatrix 采用 Agent 分工架构，当前支持三条业务赛道：

- `single`：单片推荐
- `collection`：合集盘点
- `preview`：新片速递（含 `landscape/poster` 两个子模式）

核心能力：

- 选题：`pending.txt` 点播优先 + AI 自动选题
- 元数据：TMDB / OMDB / Serper / Gemini（preview 兜底）
- 文案：结构化生成 + 长度熔断 + 标签组装
- 视觉：人工素材优先 / 渲染拼接 / CLIP 去重
- 发布：本地发布服务调用 + 成功后原子收尾

---

## 🏗️ 架构总览

```text
main.py
  ├─ run_single_mode()       # 单片模式
  ├─ run_collection_mode()   # 合集模式
  └─ run_preview_mode()      # 新片速递模式

agents/
  ├─ topic.py                # single 选题
  ├─ meta.py                 # single 元数据
  ├─ writer.py               # single 文案
  ├─ visual.py               # single 视觉
  ├─ execution.py            # 发布执行
  ├─ collection_topic.py     # collection 扫描
  ├─ collection_meta.py      # collection 批量评分
  ├─ collection_writer.py    # collection 文案组装
  ├─ collection_visual.py    # collection 渲染拼接
  ├─ preview_topic.py        # preview 扫描
  ├─ preview_meta.py         # preview 元数据
  ├─ preview_writer.py       # preview 文案组装
  └─ preview_visual.py       # preview 视觉处理

services/
  └─ clip_engine.py          # CLIP 单例引擎

utils.py
  ├─ HistoryManager
  ├─ PendingManager
  ├─ XHSClient
  ├─ LLMBrain
  ├─ calculate_progress()
  └─ clean_tag()
```

---

## 📁 目录结构（当前代码）

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
    ├── image/                    # single 图片输出
    ├── manual_materials/         # single 人工素材
    ├── collections/
    │   └── _done/                # collection 成功归档
    ├── previews/
    │   ├── landscape/            # preview 横图任务
    │   ├── poster/               # preview 竖海报任务
    │   └── _done/
    │       ├── landscape/        # preview 横图归档
    │       └── poster/           # preview 竖海报归档
    ├── score/
    │   └── local_scores.json
    └── fonts/
```

---

## 🚀 快速开始

### 1. 环境要求

- Python 3.10+
- 可选 CUDA（CLIP 推理加速）

### 2. 安装依赖

项目未提供 `requirements.txt`，按当前代码依赖安装：

```bash
pip install openai requests python-dotenv pillow torch transformers
```

### 3. 配置 `.env`

在项目根目录创建或编辑 `.env`：

```env
# DeepSeek (LLMBrain)
LLM_API_KEY=...
LLM_BASE_URL=https://api.deepseek.com

# Movie APIs
TMDB_API_KEY=...
OMDB_API_KEY=...
SERPER_API_KEY=...
SEARCH_API_KEY=...

# Preview (Gemini Grounding)
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash
```

说明：

- 豆瓣/搜索链路优先使用 `SERPER_API_KEY`，未配置时回退 `SEARCH_API_KEY`。
- preview 的 Gemini 兜底仅在 `GEMINI_API_KEY` 存在且配置次数 > 0 时触发。
- 发布服务地址固定在 `config.py`：`http://localhost:18060/api/v1`。

### 4. 选择运行模式

在 `config.py` 中设置：

```python
class Strategy:
    class System:
        RUN_MODE = "single"      # 可选: "single" / "collection" / "preview"
```

启动：

```bash
python3 main.py
```

---

## 📖 使用指南

## 一、单片模式（`RUN_MODE="single"`）

### 1) pending 输入格式

`pending.txt` 第一条支持：

- `电影名`
- `电影名｜年份或原名`
- `电影名｜年份或原名｜指定标题`

兼容全角 `｜` 与半角 `|`。

行为说明：

- 第三段标题会强制覆盖 AI 标题。
- 强制标题必须 `<=20` 字，否则直接熔断。
- 发布成功后才会写 `history.json` 并删除该 pending 任务。

### 2) 自动模式

当 pending 为空时：

- AI 每轮提名 20 部
- single 维度历史去重
- 最多 5 轮，失败后诚实退出

### 3) 视觉素材优先级

- 如果存在 `资料/manual_materials/<电影名>/`：
  1. 强制获取 TMDB 竖版封面
  2. 加载人工素材
  3. 不足数量再补 TMDB 剧照
- 否则走自动模式：TMDB 优先，不足降级 Google。

---

## 二、合集模式（`RUN_MODE="collection"`）

### 1) 输入目录规范

在 `资料/collections/` 下创建任务文件夹：

- 文件夹名：`主题｜标题`
- 图片命名支持：
  - `电影名｜序号.jpg`
  - `电影名｜年份或原名｜序号.jpg`

第二段自动识别：

- 4 位合理年份 => 年份锁定
- 否则 => 原名锁定

严格模式：命名违规会整夹跳过。

示例：

```text
资料/collections/诺兰宇宙｜烧脑天花板片单/
├── 星际穿越｜1.jpg
├── 盗梦空间｜2010｜2.jpg
└── 看不见的客人｜Contratiempo｜3.jpg
```

### 2) 正文模式

由 `Strategy.Writer.COLLECTION_BODY_MODE` 控制：

- `mode_one`：片单 + 过渡语 + 发散 + CTA + 进度
- `mode_two`：片单 + 过渡语 + 每部简介 + CTA + 进度
- `mode_three`：片单 + 核心总结 + CTA + 进度

校验点：

- `mode_two` 简介长度严格校验（配置区间，默认 55-80）
- 标题 `<=20`
- `正文 + tags <= 990`

### 3) 视觉输出

- 单图渲染 16:9
- 每 3 张拼接 16:27
- 余数单图独立输出
- 发布成功归档到：`资料/collections/_done/`

---

## 三、新片速递模式（`RUN_MODE="preview"`）

preview 还分两种子模式：

- `landscape`：横图处理（渲染/拼接）
- `poster`：竖海报直发（不渲染）

通过 `Strategy.Preview.SUB_MODE` 选择。

### 1) 任务目录规范

#### `landscape` 子模式

路径：`资料/previews/landscape/`。

任务文件夹命名：

- `主题｜标题`

图片命名：

- `电影名｜序号.jpg`
- `电影名｜原名｜序号.jpg`

#### `poster` 子模式

路径：`资料/previews/poster/`。

命名规则与 `landscape` 相同。

### 2) 元数据链路

`PreviewMetaFetcher` 采集顺序：

1. TMDB
2. Serper（白名单过滤）
3. Gemini Grounding（仅在必填缺失时触发）

必填规则（当前实现）：

- 电影名必须有
- 上映日期必须有
- 噱头必须有
- 非中国电影原名必须有（中国电影原名可空）
- 当 `SHOW_SUMMARY_BLOCK=True` 时简介必须有

上映日期优先级：正式院线优先（`type=3 > type=2 > type=1`，每档取最早日期）。

### 3) 文案与标签

- 标题 `<=20`
- 正文结构：片单 +（可选简介块）+（可选CTA）
- 标签固定前三个：`新片速递`、`红书宝藏片单`、`电影推荐`
- 再追加前 3 部电影名清洗后的 tags
- `正文 + tags <= 990`

### 4) 视觉处理

#### `landscape`

- 非 16:9 会居中裁剪到 16:9
- 渲染日期/原名/中文名/噱头
- 每 3 张拼接一张 16:27
- 可配置是否追加渲染单图、原图

#### `poster`

- 完全不渲染
- 按输入序号直发原图

### 5) preview 特殊规则

- 发布成功后归档到 `资料/previews/_done/<sub_mode>/`
- 不写 `history.json`
- 不计入本地分数体系

---

## ⚙️ 关键配置速查

### 1) 系统模式

```python
class Strategy:
    class System:
        RUN_MODE = "single"          # single / collection / preview
        USE_LOCAL_SCORES = True       # 仅合集模式有效
```

### 2) 通用视觉/文案（single + collection）

```python
class Strategy:
    class Visual:
        TARGET_TOTAL_IMAGES = 15
        MIN_COVER_WIDTH = 1000
        CLIP_THRESHOLD = 0.75
        APPEND_DETAIL_IMAGES = True
        DETAIL_IMAGE_TYPE = "original"   # original / rendered

    class Writer:
        MANUAL_TITLE_REVIEW = True
        ENABLE_TITLE_EMOJI = True

        SHOW_YEAR = False
        SHOW_DOUBAN = True
        SHOW_IMDB = False
        SHOW_ROTTEN_TOMATOES = False
        SHOW_GENRE = False
        SHOW_REGION = False

        COLLECTION_BODY_MODE = "mode_one"  # mode_one / mode_two / mode_three
        COLLECTION_SHOW_CTA = True
        COLLECTION_CTA_TEXT = "..."
        COLLECTION_SUMMARY_MIN_LEN = 55
        COLLECTION_SUMMARY_MAX_LEN = 80
        COLLECTION_SUMMARY_REWRITE_RETRIES = 3
```

### 3) preview 专属配置

```python
class Strategy:
    class Preview:
        SUB_MODE = "landscape"   # landscape / poster

        SHOW_SUMMARY_BLOCK = True
        SHOW_CTA = True
        CTA_TEXT = "欢迎大家在评论区留下你期待电影的名字～"

        SERPER_MAX_QUERIES_PER_MOVIE = 5
        GEMINI_MAX_GROUNDING_PER_MOVIE = 3
        SERPER_DOMAIN_WHITELIST = ["imdb.com", "douban.com", ...]

        HOOK_MIN_LEN = 6
        HOOK_MAX_LEN = 22
        HOOK_FORBIDDEN_WORDS = ["炸裂", "必看"]

        SUMMARY_MIN_LEN = 55
        SUMMARY_MAX_LEN = 80
        SUMMARY_REWRITE_RETRIES = 6

        APPEND_RENDERED_DETAILS = False
        APPEND_ORIGINAL_IMAGES = True
```

---

## 🚀 发布前提

- 本地发布服务可用：`http://localhost:18060/api/v1`
- 小红书登录态有效（`cookies.json` / 登录服务状态）
- 本地包含对应二进制：`xiaohongshu-login-*` 与 `xiaohongshu-mcp-*`

---

## 📦 输出与归档

- single 图片输出：`资料/image/`
- collection 输出：`资料/collections/<任务>/output/`
- collection 成功归档：`资料/collections/_done/`
- preview 输出（landscape）：`资料/previews/<sub_mode>/<任务>/output/`
- preview 成功归档：`资料/previews/_done/<sub_mode>/`

---

## ⚠️ 常见问题

### 1. 日志显示：`😴 当前无可执行的新片速递任务`

常见原因：

- `RUN_MODE` 不是 `preview`
- `SUB_MODE` 对应目录下没有符合 `主题｜标题` 的任务文件夹
- 图片命名不符合严格规则（`电影名｜序号` 或 `电影名｜原名｜序号`）

### 2. preview 简介改写反复失败

- 默认要求严格命中长度区间（例如 55-80）
- 可调小区间或调大 `SUMMARY_REWRITE_RETRIES`
- 或关闭 `SHOW_SUMMARY_BLOCK`

### 3. 程序卡在终端等待输入

- `MANUAL_TITLE_REVIEW=True` 时会进行人工标题审核
- 无人值守时请设为 `False`

