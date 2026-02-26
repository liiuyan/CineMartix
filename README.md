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
- 视觉：人工素材优先 / 渲染拼接 / preview 封面渲染 / CLIP 去重
- 发布：本地发布服务调用 + 发布前决策菜单（放弃/立即/定时）+ 成功后原子收尾

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
  ├─ clip_engine.py          # CLIP 单例引擎
  └─ cover_renderer.py       # 通用封面渲染器（preview 已接入）

utils.py
  ├─ HistoryManager
  ├─ PendingManager
  ├─ XHSClient
  ├─ LLMBrain
  ├─ calculate_progress()
  ├─ clean_tag()
  ├─ load_prompt_text()
  └─ load_prompt_lines()
```

---

## 📁 目录结构（当前代码）

```text
little_red/
├── main.py
├── config.py
├── utils.py
├── prompts/
│   └── preview/
│       ├── hook_forbidden_words.txt
│       └── hook_reference_examples.txt
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
- preview 的 Gemini 硬必填兜底仅在 `GEMINI_API_KEY` 存在且 `GEMINI_MAX_GROUNDING_PER_MOVIE > 0` 时触发；噱头专项尝试由 `GEMINI_HOOK_ATTEMPTS` 控制。
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
- `mode_one` 发散段严格校验（配置区间，默认 250-600；超出区间会重写）
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
- `主标题第一行\n第二行\n第三行｜0.jpg`（封面图，兼容 `|0` 与 `｜0`）

封面命名细则（严格模式）：

- `\n` 必须是文件名里的字面量两个字符（反斜杠 + n），不是实际换行符
- 封面主标题必须恰好包含两处 `\n`，因此固定拆成三行渲染
- 第二行/第三行允许为空（如 `xx\nxx\n` 或 `xx\n\n`），第一行不能为空
- 没有 `|0/｜0` 时，按普通 preview 任务处理（跳过封面逻辑）
- 同一任务目录出现多张 `|0/｜0` 封面图会直接熔断并整夹跳过

#### `poster` 子模式

路径：`资料/previews/poster/`。

命名规则与 `landscape` 相同（也支持 `|0/｜0` 封面图）。

### 2) 元数据链路

`PreviewMetaFetcher` 采集顺序：

1. TMDB
2. Serper（白名单过滤，逐次补齐；满足“硬必填(不含噱头)+电影类型”会提前停止，最多 `SERPER_MAX_QUERIES_PER_MOVIE` 次）
3. Gemini Grounding（补硬必填；可按 `GEMINI_HOOK_ATTEMPTS` 进行噱头专项尝试）

#### 单片采集决策流程（重点）

以下逻辑按“每一部电影”独立执行：

1. 先走 TMDB 主通道拿结构化字段（上映日期、类型、地区、演职员、简介等）。
2. 若 TMDB 已满足“硬必填(不含噱头) + `genres`”，则直接跳过 Serper。
3. 否则进入 Serper 循环（最多 `SERPER_MAX_QUERIES_PER_MOVIE` 次）：
   - 每次查询后都会增量抽取并回填字段。
   - 每次都会打印当前“硬必填缺失 + 类型状态”日志。
   - 一旦满足“硬必填(不含噱头) + `genres`”，立刻提前停止，不再跑满预算。
4. 若 Serper 到上限后 `genres` 仍缺失，只告警，不熔断（类型是“尽量收集”字段）。
5. 进入 Gemini 硬必填兜底循环（最多 `GEMINI_MAX_GROUNDING_PER_MOVIE` 次）：
   - 仅针对硬必填字段补齐。
   - 不会因为 `hook` 缺失而继续该循环。
6. 若 `hook` 仍无效，则执行 Gemini 噱头专项尝试（最多 `GEMINI_HOOK_ATTEMPTS` 次）：
   - 当 Gemini 返回的 `hook` 通过清洗校验（`clean_validate_hook`，当前实现为 `_validate_hook_candidate`）时，会打印：
     - `✅ [Gemini] 合规噱头: ...`（普通 Gemini 补字段链路）
     - `✅ [Gemini-Hook] 合规噱头: ...`（Gemini-Hook 专项链路）
7. 若噱头仍无效，再执行本地 `_generate_hookline()` 兜底生成：
   - 输入包含当前已获取的全部信息（TMDB/Serper/Gemini 字段 + snippets）。
   - 会先从信息中挑选 `1-2` 个最有噱头的点，结合示例生成 `6-22` 字噱头。
   - 句末 `。 . , ，` 不计字数，且会在清洗阶段移除。
   - 若不合规会带上“上一轮失败原因”重试，最多 `HOOK_RETRY_TIMES` 次。
8. 进入 Writer 阶段后，`_ensure_hook()` 会做最终兜底与同口径重试（同样基于 `1-2` 个噱头点 + 示例）。
9. Meta 阶段最终必填校验不会因 `hook` 缺失提前熔断；`hook` 最终由 Writer 阶段判定，失败才整夹熔断。

必填规则（当前实现）：

- Meta 阶段硬必填：
  - 电影名必须有
  - 上映日期必须有
  - 非中国电影原名必须有（中国电影原名可空）
  - 当 `SHOW_SUMMARY_BLOCK=True` 时简介必须有
- Final 阶段（Writer 兜底后发布口径）：
  - 噱头必须有（最终不可为空）
- 电影类型（`genres`）会尽量收集，但缺失不会触发熔断

上映日期优先级：正式院线优先（`type=3 > type=2 > type=1`，每档取最早日期）。

### 3) 文案与标签

- 标题 `<=20`
- 正文结构：片单 +（可选简介块）+（可选CTA）
- 片单行附加信息支持开关控制（默认全关闭）：
  - `SHOW_LIST_RELEASE_DATE`
  - `SHOW_LIST_RELEASE_REGION`
  - `SHOW_LIST_GENRES`
  - `SHOW_LIST_REGION`
- 当 `SHOW_SUMMARY_BLOCK=True` 时，简介采用“双区间”策略：
  - 生成目标区间：`SUMMARY_TARGET_MIN_LEN ~ SUMMARY_TARGET_MAX_LEN`（用于提示 AI 优先写到该范围）
  - 校验通过区间：`SUMMARY_MIN_LEN ~ SUMMARY_MAX_LEN`（仅超出该范围才触发重写）
  - 每轮都基于原始查询到的简介事实改写（不基于上一轮 AI 文本扩写/缩写）
  - 日志会打印每轮实际字数、目标区间和校验区间
- 标签固定前三个：`新片速递`、`红书宝藏片单`、`电影推荐`
- 再追加前 3 部电影名清洗后的 tags
- `正文 + tags <= 990`
- hook 禁用词与参考示例从文本文件读取：`prompts/preview/hook_forbidden_words.txt`、`prompts/preview/hook_reference_examples.txt`（文件缺失会熔断）

### 4) 视觉处理

#### `landscape`

- 非 16:9 会居中裁剪到 16:9
- 左下角自下而上渲染：`噱头 -> 原名与日期 -> 中文名`（从上到下即：中文名、原名与日期、噱头）
- 中文名 / 原名与日期 / 噱头均支持单行自适应缩放；若缩到最小字号仍超宽会触发渲染报错（熔断）
- 原名与日期合并规则：
  - 原名+日期都有：`原名 | 日期`
  - 仅原名：`原名`
  - 仅日期：`日期`（不会出现前导 `|2026.xx.xx`）
- 每 3 张拼接一张 16:27
- 可配置是否追加渲染单图、原图
- 若存在封面图（`|0/｜0`），会渲染为 3:4（`1200x1600`）并输出 `output/preview_cover.jpg`
- 最终发布序列中，封面图固定插入第 1 张（不受拼接/追加策略影响）

#### `poster`

- 完全不渲染
- 按输入序号直发原图
- 若存在封面图（`|0/｜0`），会先渲染封面并作为第 1 张，其余按输入序号直发

#### 封面水印规则（`landscape/poster` 共用）

- 水印数据来源：同任务目录下除封面外的电影条目
- 每条默认显示 1 行中文电影名
- 英文名第 2 行显示条件：非中国电影 + 有 `original_title` + DeepSeek 判定为可展示英文名
- 非中国电影若只有非英文原名，不显示第 2 行
- 中国电影不显示英文名
- DeepSeek 判定失败会按重试配置重试，超限后回退为“不显示英文名”

### 5) preview 特殊规则

- 发布成功后归档到 `资料/previews/_done/<sub_mode>/`
- 不写 `history.json`
- 不计入本地分数体系

---

## 四、发布前决策菜单（全模式）

由 `Strategy.System.ENABLE_PUBLISH_DECISION_MENU` 控制：

- `True`：发布前弹菜单
- `False`：不弹菜单，直接立即发布

菜单行为：

- `single`：4 选项
  1) 放弃发布  
  2) 修改标题后发布  
  3) 立即发布  
  4) 定时发布
- `collection` / `preview`：3 选项
  1) 放弃发布  
  2) 立即发布  
  3) 定时发布

定时发布时间输入规则：

- 必须是 ISO8601 且包含时区（推荐格式：`YYYY-MM-DDTHH:MM:SS+08:00`）
- 必须晚于当前时间（按你输入的时区做比较）
- 可输入 `q` 返回上一步，不发布

定时发布操作步骤：

1. 在发布菜单里选择“定时发布”
2. 按提示输入 `schedule_at`
3. 校验通过后会把 `schedule_at` 写入发布请求并执行发布

可直接用的格式示例：

- `2026-03-01T21:30:00+08:00`
- `2026-03-01T09:00:00+00:00`

常见错误示例：

- `2026-03-01T21:30:00`（缺少时区）
- `2026/03/01 21:30`（非 ISO8601）
- 早于当前时间的时间戳（会被拒绝）

收尾规则：

- 选择“放弃发布”时，任务不会进入成功收尾（不写历史、不删 pending、不归档）
- 非交互环境（无 TTY）会自动走“立即发布”

---

## ⚙️ 关键配置速查

### 1) 系统模式

```python
class Strategy:
    class System:
        RUN_MODE = "single"          # single / collection / preview
        ENABLE_PUBLISH_DECISION_MENU = True  # 发布前菜单总开关
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
        COLLECTION_DIVERGENT_MIN_LEN = 250
        COLLECTION_DIVERGENT_MAX_LEN = 600
```

### 3) preview 专属配置

```python
class Strategy:
    class Preview:
        SUB_MODE = "landscape"   # landscape / poster

        SHOW_SUMMARY_BLOCK = True
        SHOW_CTA = True
        CTA_TEXT = "欢迎大家在评论区留下你期待电影的名字～"
        SHOW_LIST_RELEASE_DATE = False
        SHOW_LIST_RELEASE_REGION = False
        SHOW_LIST_GENRES = False
        SHOW_LIST_REGION = False

        SERPER_MAX_QUERIES_PER_MOVIE = 5
        GEMINI_MAX_GROUNDING_PER_MOVIE = 3
        GEMINI_HOOK_ATTEMPTS = 1
        SERPER_DOMAIN_WHITELIST = ["imdb.com", "douban.com", ...]

        HOOK_MIN_LEN = 6
        HOOK_MAX_LEN = 22
        HOOK_RETRY_TIMES = 5
        # hook 语料改为外部文本文件（缺失会熔断）
        # prompts/preview/hook_forbidden_words.txt
        # prompts/preview/hook_reference_examples.txt

        # 简介双区间：
        # 生成目标区间（提示 AI 优先写到该范围）
        SUMMARY_TARGET_MIN_LEN = 60
        SUMMARY_TARGET_MAX_LEN = 70
        # 校验通过区间（仅超出该范围才触发重写）
        SUMMARY_MIN_LEN = 55
        SUMMARY_MAX_LEN = 80
        SUMMARY_REWRITE_RETRIES = 6

        APPEND_RENDERED_DETAILS = False
        APPEND_ORIGINAL_IMAGES = True
        COVER_EN_NAME_RETRY_TIMES = 3
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
- 图片命名不符合严格规则（`电影名｜序号` / `电影名｜原名｜序号` / `主标题第一行\n第二行\n第三行｜0`）
- 同一任务目录出现多张 `|0/｜0` 封面图（会触发整夹跳过）

### 2. preview 简介改写反复失败

- 当前采用双区间：目标 `SUMMARY_TARGET_MIN_LEN~SUMMARY_TARGET_MAX_LEN`（默认 60-70），校验 `SUMMARY_MIN_LEN~SUMMARY_MAX_LEN`（默认 55-80）
- 只要简介落在校验区间就会通过；只有超出校验区间才会继续重写
- 日志会输出每轮实际字数，并提示下一轮“写更长”或“写更短”
- 可调 `SUMMARY_TARGET_*`、`SUMMARY_*` 或 `SUMMARY_REWRITE_RETRIES`
- 或关闭 `SHOW_SUMMARY_BLOCK`

### 3. 程序卡在终端等待输入

- `ENABLE_PUBLISH_DECISION_MENU=True` 时，发布前会弹出决策菜单
- `single` 下会出现 4 选项（放弃 / 改标题后发 / 立即 / 定时）
- `collection` 与 `preview` 下会出现 3 选项（放弃 / 立即 / 定时）
- 无人值守可设 `ENABLE_PUBLISH_DECISION_MENU=False`；非交互环境也会自动立即发布
