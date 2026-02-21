## 📄 文件一：`README.md`

```markdown
# 🎬 CineMatrix — 全自动电影种草内容工厂

> 从选题到发布，一键生成小红书电影推荐笔记的 AI 自动化流水线。

---

## 🌟 项目简介

CineMatrix 是一套面向小红书平台的 **全自动电影内容生产系统**。它模拟了一个完整的内容创作团队——选题编辑、资料员、文案写手、美术设计师、发布运营——全部由 AI Agent 协同完成。

**核心能力：**

- 🤖 **AI 驱动选题**：基于 LLM（DeepSeek）自动生成电影话题，或从待办队列读取
- 📊 **多源元数据**：自动抓取 TMDB / 豆瓣评分、类型、年份、地区等信息
- ✍️ **杂志级文案**：生成克制、专业的电影专栏风格文案（非营销号口吻）
- 🖼️ **智能图片引擎**：TMDB 官方剧照 + Google 搜索补充 + CLIP 语义去重
- 📱 **自动发布**：模拟真人操作，自动发布到小红书平台
- 📁 **合集模式**：支持"多部电影 → 一篇盘点笔记"的批量生产

---

## 🏗️ 系统架构

```
┌─────────────────────────────────────────────────────┐
│                    main.py (主控调度器)                │
│          ┌─ run_single_mode()  单片流水线            │
│          └─ run_collection_mode()  合集流水线         │
└────────┬──────────┬──────────┬──────────┬────────────┘
         │          │          │          │
    ┌────▼───┐ ┌───▼────┐ ┌──▼───┐ ┌───▼──────┐
    │ Topic  │ │  Meta  │ │Writer│ │  Visual  │
    │ Agent  │ │Fetcher │ │Agent │ │  Agent   │
    └────────┘ └───┬────┘ └──────┘ └────┬─────┘
                   │                     │
              ┌────▼────┐          ┌────▼──────┐
              │  TMDB   │          │   CLIP    │
              │  豆瓣   │          │  Engine   │
              └─────────┘          └───────────┘
                                  (services 层)
```

**分层设计原则：**

| 层级 | 目录 | 职责 | 规则 |
|------|------|------|------|
| 主控层 | `main.py` | 调度各 Agent 的执行顺序 | 仅做"传话筒"，不含业务逻辑 |
| Agent 层 | `agents/` | 各司其职的业务单元 | 每个 Agent 只做一件事 |
| 服务层 | `services/` | 重型计算引擎（如 CLIP） | 无状态单例，纯计算 |
| 工具层 | `utils.py` | 跨 Agent 的公共能力 | 无副作用的纯函数 / 通用管理器 |
| 配置层 | `config.py` | 所有可调参数 | 全局唯一真相源 |

---

## 📁 项目结构

```
CineMatrix/
│
├── main.py                        # 🎯 主控调度器 (单片/合集双模式)
├── config.py                      # ⚙️ 全局配置 (API Key、路径、策略参数)
├── utils.py                       # 🔧 公共工具集 (LLMBrain, HistoryManager, PendingManager 等)
│
├── agents/                        # 🤖 Agent 集群
│   ├── __init__.py
│   ├── topic.py                   # 📋 单片选题 Agent
│   ├── collection_topic.py        # 📁 合集选题 Agent (文件夹扫描 + 严格模式)
│   ├── meta.py                    # 📊 元数据抓取 Agent (TMDB + 豆瓣)
│   ├── collection_meta.py         # 📊 合集元数据 Agent (批量分数查询)
│   ├── writer.py                  # ✍️ 单片文案 Agent
│   ├── collection_writer.py       # ✍️ 合集文案 Agent (批量台词/简介 + 标签组装)
│   ├── visual.py                  # 🖼️ 视觉素材 Agent (图片搜索/下载/去重)
│   └── execution.py               # 📱 发布执行 Agent (小红书自动化)
│
├── services/                      # 🧬 独立服务层
│   ├── __init__.py
│   └── clip_engine.py             # 🧠 CLIP 视觉语义引擎 (单例模式)
│
├── data/                          # 💾 数据文件
│   ├── pending.txt                # 📝 待办电影队列
│   ├── local_scores.json          # 📦 本地评分缓存
│   └── history.json               # 📜 已发布历史记录
│
└── collections/                   # 📁 合集素材目录
    ├── _done/                     # 🗃️ 已归档的合集
    └── 探讨主题｜笔记标题/          # 📂 待处理的合集文件夹
        ├── 电影名｜1.jpg
        ├── 电影名｜2.jpg
        └── output/                # 🖼️ 生成的成品图 (自动创建)
```

---

## 🚀 快速开始

### 1. 环境要求

- Python 3.10+
- CUDA（可选，用于加速 CLIP 推理）

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

**核心依赖：**

| 库 | 用途 |
|---|---|
| `openai` | 调用 DeepSeek LLM API |
| `requests` | TMDB / 豆瓣 / Google API 请求 |
| `torch` + `transformers` | CLIP 视觉模型推理 |
| `Pillow` | 图片处理 |
| `beautifulsoup4` | 豆瓣评分网页解析 |

### 3. 配置

编辑 `config.py`，填入必要的 API 密钥：

```python
TMDB_API_KEY = "your_tmdb_api_key"
SEARCH_API_KEY = "your_google_search_api_key"
DEEPSEEK_API_KEY = "your_deepseek_api_key"
```

### 4. 运行

```bash
# 单片模式 (自动选题或从 pending.txt 读取)
python main.py

# 合集模式 (扫描 collections/ 目录)
python main.py --collection
```

---

## 📖 使用指南

### 单片模式

**自动选题：** 直接运行，AI 会根据历史记录自动选择一部电影。

**手动指定：** 在 `pending.txt` 中添加电影：

```
盗梦空间 | 2010
星际穿越 | 2014
肖申克的救赎
```

> 格式：`电影名 | 年份`（年份可选，支持全角/半角分隔符）

### 合集模式

1. 在 `collections/` 下创建文件夹，命名格式：`探讨主题｜笔记标题`
2. 放入电影剧照，命名格式：`电影名｜序号.jpg`
3. 运行 `python main.py --collection`

```
collections/
└── 诺兰宇宙｜烧脑天花板的5部必看神作/
    ├── 盗梦空间｜1.jpg
    ├── 星际穿越｜2.jpg
    ├── 信条｜3.jpg
    ├── 记忆碎片｜4.jpg
    └── 致命魔术｜5.jpg
```

---

## ⚙️ 策略配置速查

在 `config.py` 的 `Strategy` 类中可调整各项行为：

```python
class Strategy:
    class Visual:
        CLIP_THRESHOLD = 0.92      # CLIP 语义去重阈值 (越高越宽松)
        MAX_IMAGES = 9             # 每篇笔记最大图片数
      
    class Writer:
        SHOW_DOUBAN = True         # 正文中显示豆瓣评分
        SHOW_IMDB = True           # 正文中显示 IMDb 评分
        SHOW_YEAR = True           # 正文中显示年份
        SHOW_GENRE = True          # 正文中显示类型
        SHOW_REGION = False        # 正文中显示地区
      
    class System:
        USE_LOCAL_SCORES = True    # 启用本地评分缓存
```

---

