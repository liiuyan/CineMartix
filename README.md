# 🎬 CineMatrix — 全自动电影内容生产流水线

> 从选题、取数、文案、视觉到发布的一体化小红书自动化系统。

---

## 🌟 项目简介

CineMatrix 采用 Agent 分工架构，当前支持四条业务赛道：

- `single`：单片推荐
- `collection`：合集盘点
- `preview`：新片速递（含 `landscape/poster` 两个子模式）
- `proxy`：代理发布（现成素材 + 现成文案 + 自动 tags）

核心能力：

- 选题：`pending.txt` 点播优先 + AI 自动选题
- 元数据：TMDB / OMDB / Codex Live Web Search / Serper / Gemini（仅 API 模式兜底）
- 文案：结构化生成 + 长度熔断 + 标签组装
- 视觉：人工素材优先 / 渲染拼接 / collection 与 preview 封面渲染 / CLIP 去重
- 代理：读取 `note.md` 与编号图片，直接复用统一发布通道
- 发布：本地发布服务调用 + 发布前决策菜单（放弃/立即/定时）+ 成功后原子收尾

---

## 📈 项目成果

**两个月打造账号总点击量达25w+，爆款点击量5w+，点击量上万作品达9部。**

以上成果数据由账号运营者统计，以下为部分作品的数据截图：

![部分作品互动数据](docs/images/account-results-interactions.jpg)

![部分作品点击量数据](docs/images/account-results-views.jpg)

---

## 🏗️ 架构总览

```text
main.py
  ├─ run_single_mode()       # 单片模式
  ├─ run_collection_mode()   # 合集模式
  ├─ run_preview_mode()      # 新片速递模式
  └─ run_proxy_mode()        # 代理发布模式

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
  ├─ preview_visual.py       # preview 视觉处理
  ├─ proxy_topic.py          # proxy 扫描
  └─ proxy_writer.py         # proxy 文案与 tags 组装

services/
  ├─ clip_engine.py          # CLIP 单例引擎
  ├─ codex_runtime.py        # Codex SDK 共享客户端与 Preview 联网会话
  ├─ cover_renderer.py       # 通用封面渲染器（preview / collection 共用）
  └─ preview_cache.py        # preview 逐电影临时缓存管理器

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
    ├── proxy/
    │   └── _done/                # proxy 成功归档
    ├── score/
    │   └── local_scores.json
    ├── cache/
    │   └── preview_cache.json     # preview 最近 5 次任务缓存
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
pip install openai openai-codex requests python-dotenv pillow torch transformers
```

### 3. 选择 LLM 运行时

在 `config.py` 中选择 API 或 Codex SDK：

```python
class Strategy:
    class System:
        LLM_RUNTIME = "codex_sdk"  # 可选: "api" / "codex_sdk"
        LLM_PROVIDER = "deepseek"  # 仅 API 模式生效: "deepseek" / "qwen"

        CODEX_MODEL = "gpt-5.6-terra"
        CODEX_REASONING_EFFORT = "high"
```

- `api`：普通文本生成保持现有 DeepSeek/Qwen API 调用。
- `codex_sdk`：普通文本生成使用本机 ChatGPT 登录态，不读取 DeepSeek 或 Qwen API Key。
- 两种运行时严格隔离，失败时不会自动切换。
- Codex SDK 模式启动前，需要先在本机 Codex 中登录 ChatGPT。
- Preview 在 `codex_sdk` 模式下使用 Codex 原生 Live Web Search，并完全绕过 Gemini；`api` 模式继续保留原 Gemini 兜底。

### 4. 配置 `.env`

仅 API 模式需要配置对应的 LLM Key；TMDB、OMDB、Serper 等数据服务 Key 仍按业务需要保留。

在项目根目录创建或编辑 `.env`：

```env
# DeepSeek (当 LLM_PROVIDER="deepseek" 时使用；默认 deepseek-v4-pro)
LLM_API_KEY=...
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-pro
LLM_THINKING_TYPE=enabled
LLM_REASONING_EFFORT=high

# Qwen / DashScope (当 LLM_PROVIDER="qwen" 时使用；以下示例为北京部署 + qwen3.5-plus)
QWEN_API_KEY=...
QWEN_MODEL=qwen3.5-plus
# 可选，不填则默认北京地域 compatible-mode 接口
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions

# Movie APIs
TMDB_API_KEY=...
OMDB_API_KEY=...
SERPER_API_KEY=...
SEARCH_API_KEY=...

# Preview API 模式专用 (Gemini Grounding)
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash
```

说明：

- DeepSeek 官方当前推荐模型名为 `deepseek-v4-pro` / `deepseek-v4-flash`；旧 `deepseek-chat` 与 `deepseek-reasoner` 将在 `2026-07-24` 废弃。
- 项目内部对 DeepSeek 使用 OpenAI 兼容客户端调用，默认 `LLM_MODEL=deepseek-v4-pro`，并显式开启 `thinking` 与 `reasoning_effort=high`。
- `LLM_RUNTIME="api"` 且 `LLM_PROVIDER="qwen"` 时，`LLMBrain` 会默认开启 Qwen 强制联网搜索；Gemini 仍只承担 API 模式的 Preview 兜底。
- 北京部署下使用 `qwen3.5-plus` 时，请走 DashScope `compatible-mode`，不要使用旧的 `.../api/v1/services/aigc/text-generation/generation`；否则可能返回 `400 url error`。
- 项目内部对 Qwen 使用 OpenAI 兼容客户端调用；`QWEN_BASE_URL` 允许直接填写完整的 `.../compatible-mode/v1/chat/completions` 地址，程序会自动归一化处理。
- 豆瓣/搜索链路优先使用 `SERPER_API_KEY`，未配置时回退 `SEARCH_API_KEY`。
- Preview 的 Gemini 兜底仅在 `LLM_RUNTIME="api"`、`GEMINI_API_KEY` 存在且预算大于 0 时触发；`codex_sdk` 模式不会调用 Gemini。
- 发布服务地址固定在 `config.py`：`http://localhost:18060/api/v1`。

### 5. 选择业务运行模式

在 `config.py` 中设置：

```python
class Strategy:
    class System:
        RUN_MODE = "single"      # 可选: "single" / "collection" / "preview" / "proxy"
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
  - `主标题第一行\n第二行\n第三行｜0.jpg`（可选封面图，兼容 `|0` 与 `｜0`）

第二段自动识别：

- 4 位合理年份 => 年份锁定
- 否则 => 原名锁定

严格模式：命名违规会整夹跳过。

封面命名细则（严格模式）：

- `\n` 必须是文件名里的字面量两个字符（反斜杠 + n），不是实际换行符
- 封面主标题必须恰好包含两处 `\n`，因此固定拆成三行渲染
- 第二行/第三行允许为空，第一行不能为空
- 没有 `|0/｜0` 时，按普通 collection 任务处理（跳过封面逻辑）
- 同一任务目录出现多张 `|0/｜0` 封面图会直接整夹跳过

示例：

```text
资料/collections/诺兰宇宙｜烧脑天花板片单/
├── 影史级构图美学\n三部曲一次看够\n｜0.jpg
├── 星际穿越｜1.jpg
├── 盗梦空间｜2010｜2.jpg
└── 看不见的客人｜Contratiempo｜3.jpg
```

### 2) 正文模式

由 `Strategy.Writer.COLLECTION_BODY_MODE` 控制：

- `mode_one`：片单 + 过渡语 + 发散 + CTA + 进度
- `mode_two`：片单 + 过渡语 + 每部简介 + CTA + 进度
- `mode_four`：片单 + 过渡语 + 每部纯电影简介 + CTA + 进度
- `mode_five`：片单 + 过渡语 + 发散 + 每部纯电影简介 + CTA + 进度
- `mode_three`：片单 + 核心总结 + CTA + 进度

校验点：

- `mode_two` 简介长度严格校验（配置区间，默认 55-80）
- `mode_four` / `mode_five` 的正文简介也严格校验（配置区间，默认 55-80）
- `mode_two` 的相邻两部电影简介之间会空 1 行，避免正文连成一整段
- `mode_four` / `mode_five` 的正文简介块之间也会空 1 行，格式保持 `《电影名》：简介`
- `mode_one` 发散段严格校验（配置区间，默认 250-600；超出区间会重写）
- `mode_four` 的正文简介会强制写成脱离主题/标题语境的纯电影简介，接近豆瓣式剧情介绍
- `mode_five` 会保留 `mode_one` 的发散段，并在其后追加与 `mode_four` 同规则的纯电影简介块
- `movies_content` 对齐时，先做原片名精确匹配；若 AI 返回名仅存在空格差异（如 `飞驰人生2` / `飞驰人生 2`），会走标准化后的保守精确匹配
- 不再使用“片名互相包含就复用文案”的兜底规则，避免系列片（如 `飞驰人生` / `飞驰人生2` / `飞驰人生3`）误用同一条金句或简介
- 若 AI 返回的电影名无法安全对齐，对应电影会回退到默认文案兜底，而不是错误复用其他电影内容
- 标题 `<=20`
- `正文 + tags <= 990`

### 3) 视觉输出

- 默认单图渲染 16:9；当 `Strategy.Visual.COLLECTION_USE_9_4_RENDER=True` 时改为 9:4
- 默认每 3 张拼接 16:27；当 `Strategy.Visual.COLLECTION_USE_9_4_RENDER=True` 时改为 3:4
- 余数单图独立输出
- 当 `DETAIL_IMAGE_TYPE="rendered"` 时，追加的渲染单图比例会跟随上面的开关（16:9 或 9:4）；`original` 原图追加不受影响
- 若存在封面图（`|0/｜0`），会渲染为 3:4（`1200x1600`）并输出 `output/collection_cover.jpg`
- 合集封面英文名是否显示由 `Strategy.Visual.COLLECTION_COVER_SHOW_ENGLISH_NAMES` 控制；当前默认开启
- 最终发布序列中，合集封面固定插入第 1 张；后面的长图/单图追加顺序保持原逻辑
- `Strategy.Visual.COLLECTION_COVER_SHOW_WATERMARK=False` 时，只关闭电影名水印区域，封面三行主标题仍然保留
- `Strategy.Visual.COLLECTION_COVER_SHOW_ENGLISH_NAMES=False` 时，即使保留水印区域，也只显示中文名
- 当 `Strategy.Visual.COLLECTION_COVER_SHOW_ENGLISH_NAMES=True` 时，`CollectionMetaFetcher` 会补齐 `original_title / is_china_film`；即使命中 `local_scores.json` 满血缓存，也不会再因为元数据缺失而丢失英文水印
- collection 封面底图裁剪焦点维护在 `services/cover_renderer.py` 的 `CoverRenderer.cover_config["crop"]["collection"]`
  - 默认 `focus_x=0.5`、`focus_y=0.5`，等价于居中裁剪
  - `focus_y` 更小表示更偏上裁，更大表示更偏下裁
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
- `电影名｜年份或原名｜序号.jpg`
- `主标题第一行\n第二行\n第三行｜0.jpg`（封面图，兼容 `|0` 与 `｜0`）

第二段自动识别：

- 4 位合理年份 => 年份锁定
- 否则 => 原名锁定

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

`LLM_RUNTIME="codex_sdk"`：

1. TMDB 结构化数据
2. OMDB 结构化数据
3. Codex 原生 Live Web Search（每部电影至少 1 轮、最多 `CODEX_MAX_SEARCH_ROUNDS_PER_MOVIE` 轮）
4. Serper 可选后备（仅在 Codex 多轮后硬字段仍缺失时触发）

`LLM_RUNTIME="api"` 保持原顺序：TMDB → Serper → Gemini Grounding。

#### 单片采集决策流程（重点）

Codex SDK 模式下，以下逻辑按“每一部电影”独立执行：

1. 先从 TMDB、OMDB 获取结构化字段与对应数据源链接。
2. 为当前电影建立独立 Codex 线程，并至少执行一次实时联网搜索：
   - `web_search="live"`
   - `tools.web_search.context_size="high"`
   - 只读沙箱，禁用 Shell、应用、连接器、MCP 和子代理
   - 不设置硬性域名白名单，但优先片方、发行方、院线等一手来源
3. Codex 返回结构化 JSON 和来源 URL：
   - 有实际 `webSearch` 事件且存在有效来源时才采纳联网字段
   - 有来源支持的纠正值可以覆盖数据库冲突值
   - 无法确认的字段必须留空，不允许写“待定”或猜测
4. 若字段仍缺失，复用同一电影线程继续搜索，最多 3 轮。
5. 三轮后硬字段仍缺失时，可调用 Serper 作为后备；Codex SDK 模式下 Serper 同样不使用域名白名单。
6. 搜索后若仍缺少必填字段，立即熔断当前 Preview 任务；其他未确认字段写入 `unconfirmed_fields`，保留电影并将字段留空。
7. `hook` 仍沿用当前 `_generate_hookline()` 与 Writer 最终修正链路。

API 模式继续使用原有 Serper 增量补齐、Gemini 硬字段兜底和 Gemini hook 专项尝试，不受 Codex 分支影响。

#### 逐电影处理与临时缓存（本轮新增）

preview 现在不是“先把所有电影整批查完再统一写文案”，而是改成了按电影逐部完成：

1. 扫描任务并生成任务签名：
   - `run_mode=preview`
   - `sub_mode`
   - `theme`
   - `title`
   - 排序后的 `movie_keys`
2. 读取 `资料/cache/preview_cache.json`
3. 对当前任务中的每一部电影：
   - API 模式命中完整缓存时，直接复用该电影的数据
   - Codex SDK 模式命中缓存时，复用 hook/summary 等生成结果，但仍至少执行一次实时事实核验
   - 若未命中缓存，则对该电影执行完整采集与写作链路
   - 只有当该电影的元数据、hook、summary（若开启）都完成后，才立即写入缓存
4. 若在后续某部电影熔断：
   - 前面已完成并写入缓存的电影会保留
   - 当前失败这部不会写入缓存
5. 下次再次运行同一任务时，只重查未完成的电影

任务缓存匹配规则：

- `run_mode` 必须是 `preview`
- `sub_mode` 必须相同
- `theme` 必须相同
- `title` 必须相同
- `movie_keys` 集合必须相同
- 电影顺序不参与缓存匹配

单片缓存匹配规则：

- `movie_key` 优先级：
  - `电影名｜year｜年份`
  - `电影名｜original｜原名`
  - 只有电影名时则用 `电影名`

缓存范围：

- 仅保留最近 `5` 次 preview 任务
- 缓存文件路径：`资料/cache/preview_cache.json`
- 只缓存“完整电影”，不缓存半成品
- 不缓存 `path/index`，这两个字段每次都以当前任务扫描结果为准

事实缺失规则（当前实现）：

- API 与 Codex SDK 两种模式共用同一套 Meta 必填规则：
  - 电影名必须有
  - 上映日期必须有
  - 非中国电影原名必须有（中国电影原名可空）
  - 当 `SHOW_SUMMARY_BLOCK=True` 时简介必须有；关闭时简介可空
- Codex SDK 模式会在 TMDB、OMDB、Codex 最多 3 轮联网搜索与 Serper 后备全部结束后执行校验：
  - 任一必填字段仍缺失时，熔断当前 Preview 任务
  - 导演、演员、类型、地区、上映地区等可选字段缺失时，电影继续保留
  - 可选未确认字段保持为空，并记录在 `unconfirmed_fields`
- Final 阶段（Writer 兜底后发布口径）：
  - 噱头必须有（最终不可为空）
- 电影类型（`genres`）会尽量收集，但缺失不会触发熔断

说明：Writer 仍保留同样的必填字段终检，防止旧缓存或手工数据绕过 Meta 校验。

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
  - 正文里相邻两部电影的简介之间会空 1 行
- 标签固定前三个：`新片速递`、`红书宝藏片单`、`电影推荐`
- 再追加前 3 部电影名清洗后的 tags
- `正文 + tags <= 990`
- hook 禁用词与参考示例从文本文件读取：`prompts/preview/hook_forbidden_words.txt`、`prompts/preview/hook_reference_examples.txt`（文件缺失会熔断）
- 每部电影完成后，日志会统一打印一次最终采用的噱头，避免多来源重复打印

### 4) 视觉处理

#### `landscape`

- 默认按 `CoverRenderer.cover_config["crop"]["preview"]` 的 `focus_x=0.5`、`focus_y=0.5` 做居中裁剪；当 `Strategy.Preview.LANDSCAPE_USE_9_4_RENDER=True` 时改为 9:4
- 左下角自下而上渲染：`噱头 -> 原名与日期 -> 中文名`（从上到下即：中文名、原名与日期、噱头）
- 中文名 / 原名与日期 / 噱头均支持单行自适应缩放；若缩到最小字号仍超宽会触发渲染报错（熔断）
- 原名与日期合并规则：
  - 原名+日期都有：`原名 | 日期`
  - 仅原名：`原名`
  - 仅日期：`日期`（不会出现前导 `|2026.xx.xx`）
- 默认每 3 张拼接一张 16:27；当 `Strategy.Preview.LANDSCAPE_USE_9_4_RENDER=True` 时改为 3:4
- 可配置是否追加渲染单图、原图：渲染单图比例跟随开关（16:9 或 9:4），原图追加不受影响
- 若存在封面图（`|0/｜0`），会渲染为 3:4（`1200x1600`）并输出 `output/preview_cover.jpg`
- 封面主标题固定三行；纵向推进采用“当前行字号 + `line_spacing`”的层级排版逻辑（不是按真实文字高度），用于保留第一行更强的主视觉压场感
- 标题行距参数当前在 `services/cover_renderer.py` 的 `CoverRenderer.cover_config["title"]["line_spacing"]` 中维护，默认 `20`
- `Strategy.Preview.COVER_SHOW_WATERMARK=False` 时，只关闭电影名水印区域，封面三行主标题仍然保留
- preview 封面底图裁剪焦点维护在 `services/cover_renderer.py` 的 `CoverRenderer.cover_config["crop"]["preview"]`
  - 默认 `focus_x=0.5`、`focus_y=0.5`，等价于居中裁剪
  - `focus_y` 更小表示更偏上裁，更大表示更偏下裁
- 最终发布序列中，封面图固定插入第 1 张（不受拼接/追加策略影响）

#### `poster`

- 完全不渲染
- 按输入序号直发原图
- 若存在封面图（`|0/｜0`），会先渲染封面并作为第 1 张，其余按输入序号直发

#### 封面水印规则（`landscape/poster` 共用）

- 水印数据来源：同任务目录下除封面外的电影条目
- 中文名支持自适应换行，最多 2 行
- 英文名第 2 行显示条件：英文名开关开启 + 非中国电影 + 有 `original_title` + DeepSeek 判定为可展示英文名
- 英文名支持自适应换行，最多 2 行
- 非中国电影若只有非英文原名，不显示第 2 行
- 中国电影不显示英文名
- DeepSeek 判定失败会按重试配置重试，超限后回退为“不显示英文名”
- 当封面水印开关关闭时，本节整块逻辑会被跳过，但封面主标题仍照常渲染
- collection 命中 `local_scores.json` 满血缓存时，也会补齐封面英文水印所需的 `original_title / is_china_film`，避免缓存路径与非缓存路径行为不一致
- 水印块内部参数当前维护在 `services/cover_renderer.py` 的 `CoverRenderer.cover_config["watermark"]`：
  - 默认字号 `45`，统一缩字号最小下限 `30`
  - 中文/英文块内部默认行间距 `8`
  - 中文块与英文块之间默认间距 `12`
  - 相邻电影条目的最小边缘间距 `24`
  - 右侧留白当前为 `0`（即文本块可贴近画布右边界）
- 相邻电影条目采用“边缘间距等距”排布：先测量每个条目的真实块高度，再在 `start_y ~ end_y` 之间平均分配剩余空间
- 若总高度超出可用区域，会对所有水印统一缩字号；若缩到最小字号仍放不下，封面渲染会熔断失败

### 5) preview 特殊规则

- 发布成功后归档到 `资料/previews/_done/<sub_mode>/`
- 不写 `history.json`
- 不计入本地分数体系
- 临时缓存保存在 `资料/cache/preview_cache.json`

---

## 四、代理模式（`RUN_MODE="proxy"`）

代理模式用于发布已经准备好的素材和文案，不接入电影元数据、不渲染图片、不写 `history.json`。

### 1) 输入目录规范

在 `资料/proxy/` 下创建任务文件夹：

```text
资料/proxy/春日穿搭笔记/
├── note.md
├── 1.jpg
├── 03.jpg
└── 10.png
```

`note.md` 协议：

- 第 1 行是标题，不能为空，且必须 `<=20` 字
- 第 2 行起是正文，保留内部换行，首尾空行会被清理
- 正文不能为空

图片协议：

- 支持 `.jpg / .jpeg / .png / .webp`
- 图片文件名主干必须是纯阿拉伯数字，例如 `1.jpg`、`2.png`、`03.webp`
- 允许缺号和前导零，发布顺序按数字值升序排列
- 必须包含编号 `1`，编号 `1` 作为封面
- `0.jpg`、`abc.jpg`、`1.jpg + 01.png` 这类重复数字编号都会直接熔断，不发布
- 非图片文件除 `note.md` 外会被忽略；隐藏文件和子目录会被忽略

### 2) 文案与 tags

- 程序读取 `note.md` 组装 `title / content`
- tags 由当前全局 `LLM_PROVIDER` 对应模型根据标题和正文自动生成
- tags 生成失败时，会用标题和正文关键词做本地兜底
- 不强行加入 `电影推荐` 等固定领域标签
- 校验硬线保持一致：标题 `<=20`，`正文 + tags <= 990`

### 3) 发布与归档

- 一次运行只处理 `资料/proxy/` 下按目录名排序的第一个任务文件夹
- 发布前菜单复用 collection / preview 的 3 选项：放弃 / 立即发布 / 定时发布
- 发布成功后整夹归档到 `资料/proxy/_done/`
- 放弃发布或发布失败时，任务目录保持原样

---

## 五、发布前决策菜单（全模式）

由 `Strategy.System.ENABLE_PUBLISH_DECISION_MENU` 控制：

- `True`：发布前弹菜单
- `False`：不弹菜单，直接立即发布

菜单行为：

- `single`：4 选项
  1) 放弃发布  
  2) 修改标题后发布  
  3) 立即发布  
  4) 定时发布
- `collection` / `preview` / `proxy`：3 选项
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

- 菜单中的示例会按北京时间动态显示“最近一次可用的 17:30”
- 若当前北京时间尚未到 `17:30`，示例显示“当天 `17:30`”
- 若当前北京时间已过 `17:30`，示例显示“次日 `17:30`”
- 你也可以手动输入任意合法的 ISO8601 时间，例如：
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
        LLM_RUNTIME = "codex_sdk"    # api / codex_sdk
        LLM_PROVIDER = "deepseek"    # 仅 api 模式生效: deepseek / qwen
        CODEX_MODEL = "gpt-5.6-terra"
        CODEX_REASONING_EFFORT = "high"
        RUN_MODE = "single"          # single / collection / preview / proxy
        ENABLE_PUBLISH_DECISION_MENU = True  # 发布前菜单总开关
        USE_LOCAL_SCORES = True       # 仅合集模式有效
```

DeepSeek 相关环境变量：

```env
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-pro
LLM_THINKING_TYPE=enabled
LLM_REASONING_EFFORT=high
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
        COLLECTION_USE_9_4_RENDER = True   # False: 16:9→16:27, True: 9:4→3:4
        COLLECTION_COVER_SHOW_WATERMARK = True
        COLLECTION_COVER_SHOW_ENGLISH_NAMES = True

    class Writer:
        ENABLE_TITLE_EMOJI = True

        SHOW_YEAR = False
        SHOW_DOUBAN = True
        SHOW_IMDB = False
        SHOW_ROTTEN_TOMATOES = False
        SHOW_GENRE = False
        SHOW_REGION = False

        COLLECTION_BODY_MODE = "mode_one"  # mode_one / mode_two / mode_three / mode_four / mode_five
        COLLECTION_SHOW_CTA = True
        COLLECTION_CTA_TEXT = "..."
        COLLECTION_SUMMARY_MIN_LEN = 55  # mode_two / mode_four / mode_five 共用
        COLLECTION_SUMMARY_MAX_LEN = 80  # mode_two / mode_four / mode_five 共用
        COLLECTION_SUMMARY_REWRITE_RETRIES = 3  # mode_two / mode_four / mode_five 共用
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

        CODEX_MAX_SEARCH_ROUNDS_PER_MOVIE = 3
        SERPER_MAX_QUERIES_PER_MOVIE = 5
        GEMINI_MAX_GROUNDING_PER_MOVIE = 3  # 仅 API 模式
        GEMINI_HOOK_ATTEMPTS = 1            # 仅 API 模式
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
        SUMMARY_REWRITE_RETRIES = 10

        APPEND_RENDERED_DETAILS = False
        LANDSCAPE_USE_9_4_RENDER = False  # False: 16:9→16:27, True: 9:4→3:4
        APPEND_ORIGINAL_IMAGES = True
        COVER_SHOW_WATERMARK = True
        COVER_SHOW_ENGLISH_NAMES = True
        COVER_EN_NAME_RETRY_TIMES = 3
        PREVIEW_CACHE_MAX_TASKS = 5
```

### 4) proxy 专属配置

```python
class Strategy:
    class Proxy:
        TAG_GENERATION_RETRIES = 2  # tags 生成重试次数
        MAX_TAGS = 8                # 最多保留 tags 数
        MAX_TAG_LEN = 12            # 单个 tag 最大字符数
```

### 5) config 结构说明（本轮同步）

- `config.py` 已按职责分为 `System / Writer / Visual / Preview / Proxy` 五组，便于按赛道调参
- 配置字段名与默认值保持兼容（无需改动现有业务代码调用）
- 本轮新增两个比例开关：`COLLECTION_USE_9_4_RENDER`、`LANDSCAPE_USE_9_4_RENDER`
- preview / collection 封面标题、水印与裁剪焦点参数当前未上提到 `config.py`，而是维护在 `services/cover_renderer.py` 的 `CoverRenderer.cover_config` 中，便于开发时直接微调
- 封面裁剪焦点当前分为两组独立配置：
  - `CoverRenderer.cover_config["crop"]["preview"]`
  - `CoverRenderer.cover_config["crop"]["collection"]`
- preview 与 collection 的封面水印开关已拆分：
  - `Strategy.Preview.COVER_SHOW_WATERMARK`
  - `Strategy.Visual.COLLECTION_COVER_SHOW_WATERMARK`
- preview 与 collection 的封面英文水印开关已拆分：
  - `Strategy.Preview.COVER_SHOW_ENGLISH_NAMES`
  - `Strategy.Visual.COLLECTION_COVER_SHOW_ENGLISH_NAMES`
- preview 临时缓存文件路径为 `资料/cache/preview_cache.json`
- 未使用配置项 `LOCAL_FONT_PATH` 已移除，避免误导
- 注释已恢复为“可操作型说明”，短说明优先同行注释，便于快速阅读

封面调试脚本：

- `test_cover_layout.py` 现在支持直接切换测试赛道与封面参数，便于调封面裁剪
- 可在脚本顶部直接修改：
  - `TEST_COVER_MODE = "preview" / "collection"`
  - `TEST_SHOW_WATERMARK = True / False`
  - `TEST_SHOW_ENGLISH_NAMES = None / True / False`（`None` 表示跟随 `config.py` 当前正式默认值）
  - `TEST_FOCUS_X = None / 0.0-1.0`
  - `TEST_FOCUS_Y = None / 0.0-1.0`
- 当 `TEST_FOCUS_X/Y = None` 时，会沿用 `CoverRenderer.cover_config` 的正式配置
- 当填入数值时，只对本次测试生效，适合先试 `focus_y` 再回写正式配置

### 5) Prompt 管理建议（建议方案，未全量落地）

当前已落地：
- `preview` 的 hook 语料已外置到 `prompts/preview/*.txt`

建议继续外置（优先级从高到低）：
- `agents/writer.py`：`AESTHETICS_PROTOCOL`、主生成 Prompt、标题重写 Prompt
- `agents/collection_writer.py`：`MAGAZINE_AESTHETICS_PROTOCOL`、`mode_one/two/three/four/five` 大模板
- `agents/preview_meta.py` 与 `agents/preview_writer.py`：hook 生成大模板（两端保持同口径）
- `agents/preview_meta.py`：Codex 联网核查、Serper 抽取与 API 模式 Gemini Grounding Prompt

建议暂时保留内联：
- 明显短小且与运行时变量强绑定的 Prompt（改动频率低、抽离收益小）

---

## 🧪 自动化测试

完成依赖安装后，激活运行项目所用的虚拟环境，在项目根目录执行：

```bash
python3 -m unittest test_llm_runtime test_preview_codex_search -v
```

当前包含两个测试脚本，共 12 项测试：

- `test_llm_runtime.py`（4 项）：验证 API/Codex 运行时分流、共享运行时复用与非法配置处理。
- `test_preview_codex_search.py`（8 项）：验证 Preview 搜索结果采纳、冲突字段纠正、来源记录、必填与可选字段处理、缓存生成内容复用，以及 API 模式的 Gemini 兜底。

测试使用 Python 标准库 `unittest` 和模拟对象，不会发起真实模型调用、联网搜索或小红书发布，也不需要真实 API Key 或 Codex 登录态。全部通过时，输出中会显示 `Ran 12 tests` 和 `OK`。

这两个脚本应随对应功能代码一起维护。它们验证运行时分流和 Preview 业务逻辑；真实 Codex 登录、外部数据服务与小红书发布仍需单独进行集成验证。

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
- preview 临时缓存：`资料/cache/preview_cache.json`

---

## ⚠️ 常见问题

### 1. 日志显示：`😴 当前无可执行的新片速递任务`

常见原因：

- `RUN_MODE` 不是 `preview`
- `SUB_MODE` 对应目录下没有符合 `主题｜标题` 的任务文件夹
- 图片命名不符合严格规则（`电影名｜序号` / `电影名｜年份或原名｜序号` / `主标题第一行\n第二行\n第三行｜0`）
- 同一任务目录出现多张 `|0/｜0` 封面图（会触发整夹跳过）

### 2. preview 缓存没有复用

常见原因：

- 当前任务的 `sub_mode`、`theme`、`title` 与缓存中的任务不一致
- 当前任务的电影集合和缓存不一致（顺序不影响，但电影身份必须一致）
- 同名电影的年份锁定/原名锁定不同，导致 `movie_key` 不同
- 旧缓存不满足当前配置（例如之前没写简介，这次开启了 `SHOW_SUMMARY_BLOCK=True`），此时程序会只重查当前电影
- 超过最近 `5` 次任务上限后，较旧的任务缓存会被自动淘汰

### 3. preview 简介改写反复失败

- 当前采用双区间：目标 `SUMMARY_TARGET_MIN_LEN~SUMMARY_TARGET_MAX_LEN`（默认 60-70），校验 `SUMMARY_MIN_LEN~SUMMARY_MAX_LEN`（默认 55-80）
- 只要简介落在校验区间就会通过；只有超出校验区间才会继续重写
- 日志会输出每轮实际字数，并提示下一轮“写更长”或“写更短”
- 可调 `SUMMARY_TARGET_*`、`SUMMARY_*` 或 `SUMMARY_REWRITE_RETRIES`
- 或关闭 `SHOW_SUMMARY_BLOCK`

补充：降低重写次数的建议策略（未落地）

- 问题根因：即使提示“写到 N 字”，模型也常把 `N` 当软约束，导致反复重试
- 建议改为“预算优先”：
  - 先扣除片单/CTA/tags 长度，计算简介总预算，再按电影分配目标
  - 先生成，再按偏差做定向修正（小偏差微调，大偏差整段重写）
  - 最后仅对最长的 1-2 条简介做全局兜底压缩
- 约束不变：始终保持 `content + tags <= 990`

### 4. 程序卡在终端等待输入

- `ENABLE_PUBLISH_DECISION_MENU=True` 时，发布前会弹出决策菜单
- `single` 下会出现 4 选项（放弃 / 改标题后发 / 立即 / 定时）
- `collection` 与 `preview` 下会出现 3 选项（放弃 / 立即 / 定时）
- 无人值守可设 `ENABLE_PUBLISH_DECISION_MENU=False`；非交互环境也会自动立即发布
