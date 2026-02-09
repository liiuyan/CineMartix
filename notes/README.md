# 🎬 Little Red - 小红书电影号全自动运营系统

## 📖 项目简介

本项目是一个基于 **DeepSeek (LLM)** 、 **CLIP (AI视觉模型)** 和 **github开源项目（小红书MCP）** 的全自动化小红书运营工具。它能够自动完成以下全流程：

1.  **智能选题**：基于全品类电影库（影史经典/冷门佳作/商业爽片），结合历史记录自动去重，也可以指定电影。
2.  **文案创作**：生成“杂志级排版”的电影档案，包含电影档案、荣誉、主创团队、电影简介、独家亮点、经典台词、关于电影（评论）等内容。
3.  **视觉搜集**：从 TMDB/Google 搜集高清剧照，并使用 **CLIP 模型** 进行语义级去重（防止重复或相似图片），也可以指定图片。
4.  **自动发布**：通过 MCP 协议自动将图文发布至小红书。

---

## 🏗️ 项目目录结构

```text
little_red/
├── main.py                         # [入口] 程序主入口，负责调度所有 Agent
├── config.py                       # [配置] 路径定义、API Key、算法阈值设置
├── utils.py                        # [工具] 通用类库 (LLM客户端, 历史记录管理, API请求)
├── test_clip.py                    # [测试] 用于测试 CLIP 模型相似度阈值的独立脚本
├── history.json                    # [数据] 已发布电影的历史记录 (自动去重库)
├── cookies.json                    # [数据] 小红书登录凭证
├── .env                            # [配置] 环境变量 (API Key 存放处)
├── xiaohongshu-login-darwin-arm64  # [工具] 小红书扫码登录程序 (Mac ARM64)
├── xiaohongshu-mcp-darwin-arm64    # [工具] 小红书 MCP 服务程序 (Mac ARM64)
├── agents/                         # [模块] 核心业务逻辑模块
│   ├── __init__.py
│   ├── topic.py                    # 选题 Agent
│   ├── writer.py                   # 文案 Agent
│   ├── visual.py                   # 视觉 Agent (含 CLIP)
│   └── execution.py                # 执行 Agent
├── notes/                          # [文档] 笔记与说明
│   ├── README.md                   # 本说明文档
│   └── little_red_book_notes.md    # 项目开发笔记
└── 资料/                           # [资源] 静态资源存放目录
    ├── fonts/                      # 字体文件
    ├── image/                      # 图片下载缓存目录
    └── manual_materials            # 指定电影的图片存放目录 
        └──电影名                    # 该电影名文件夹存放对应电影的图片
```

## 🛠️ 环境依赖与安装

本项目依赖 Python 环境及部分 AI 库。

### 1. Python 依赖

请在终端运行以下命令安装所需库：

```bash
pip install requests openai pillow python-dotenv torch transformers
```

* `torch` & `transformers`: 用于运行 CLIP 视觉模型。
* `openai`: 用于调用 DeepSeek API (兼容 OpenAI 格式)。
* `pillow`: 用于图片处理。
* `python-dotenv`: 用于读取 `.env` 配置文件。

### 2. 外部工具权限

如果是首次运行，可能需要给予二进制文件执行权限：

```bash
chmod +x xiaohongshu-login-darwin-arm64
chmod +x xiaohongshu-mcp-darwin-arm64
```

## 📂 文件详细说明

### 1. 根目录核心文件

* **`main.py` (指挥官)**
    * 程序的唯一入口。
    * 负责按顺序调度 `Topic` -> `Writer` -> `Visual` -> `Execution` 四大 Agent。
    * 代码量极少，只包含流程控制逻辑。

* **`config.py` (配置中心)**
    * 定海神针：定义了 `BASE_DIR`, `LOCAL_IMAGE_DIR` 等绝对路径，确保代码在任何目录下运行都能找到资源。
    * 算法参数：定义了 `CLIP_THRESHOLD = 0.75` (语义去重阈值)，相似度在0.75以上的两张图片被视为是同一张图片的不同形式（比如加里台词，图片剪切）。
    * API配置：读取 `.env` 中的密钥。

* **`utils.py` (基础设施)**
    * `HistoryManager`: 管理 `history.json`，负责读取和写入已发布电影记录，提供去重查询。
    * `XHSClient`: 封装了与小红书 MCP 服务的 HTTP 通信逻辑。
    * `LLMBrain`: 封装了 DeepSeek API 的调用逻辑。

* **`test_clip.py` (调试工具)**
    * 一个独立的脚本。
    * 用于手动测试两张图片的相似度分数，帮助调整 `config.py` 中的 `CLIP_THRESHOLD`。

* **`xiaohongshu-login-*` / `xiaohongshu-mcp-*`**
    * `login`: 运行后会在终端显示二维码，扫码后生成 `cookies.json`。
    * `mcp`: 后台服务进程，负责模拟浏览器环境进行笔记发布。

### 2. Agents 模块 (agents/)

* **`topic.py` (选题 Agent)**
    * 职责：从影史经典、冷门佳作、商业片等维度推荐电影。
    * 逻辑：查看用户有没有指定电影 -> 没有 -> 调用 DeepSeek 推荐 -> 读取 `history.json` -> 过滤掉已发过的电影 -> 返回最终选题。  
    查看用户有没有指定电影 -> 有 -> 使用用户指定的电影 -> 返回选题（指定电影选题逻辑：从上到下顺序）

* **`writer.py` (文案 Agent)**
    * 职责：生成小红书笔记文案。
    * 特色：
        * 采用“文艺杂志”排版风格。
        * 严格遵守“中国香港/中国台湾”等政治正确规范。
        * 从自制的emoji库中随机选取符合主题的emoji，增加笔记的趣味性和随机性。
        * 自动生成电影档案、荣誉、主创团队、电影简介、独家亮点、经典台词、关于电影（评论）等内容。
        * 独家亮点为该电影的特点及电影内容的延伸，设计了逻辑发散链
        * 自动为笔记附上tags

* **`visual.py` (视觉 Agent)**
    * 职责：搜集并筛选高质量剧照。
    * 核心逻辑：
        * 源头筛选：优先下载 TMDB 无字幕(null)和中文(zh)图片。
        * CLIP 去重：下载每张图时，计算其语义向量。如果与已存图片的相似度 > 0.75，则视为重复并删除。
        * 智能排序：确保优先展示质量最高的无字剧照。
        * 若用户指定了剧照，择从TMDB上选择一张封面，再使用用户上传的剧照（N张），再从TMDB上获取10-1-N张剧照，每张剧照之间都要CLIP去重
        * 无论电影是指定的还是ai选出的，都会去查看 **manual_materials** 文件夹里是否有与选出电影名一致的文件夹名

* **`execution.py` (执行 Agent)**
    * 职责：最后一步，将标题、正文、图片列表打包发送给 MCP 服务进行发布。

### 3. 数据与资源

* **`history.json`**
    * 格式：`{"电影名": "2023-10-27", ...}`
    * 作用：永久记忆库，保证几年内都不会重复推荐同一部电影。

* **`资料/image/`**
    * 作用：临时存放下载的电影海报和剧照。每次运行新任务时，`VisualAgent` 会复用此目录（建议定期手动清理，或保留作为素材库）。

* **`资料/manual_materials/`**  
    * 作用：存放用户指定的图片
    * 规则：**manual_materials** 文件夹里存放着以电影名为名字的文件夹，电影名文件夹里存放着对应电影的剧照

## 🚀 如何运行

1.  **配置密钥**：确保根目录下有 `.env` 文件，并填入了 DeepSeek 和 TMDB 的 API Key。
2.  **启动服务**：在终端启动小红书 MCP 服务 (保持运行)。

    ```bash
    ./xiaohongshu-mcp-darwin-arm64
    ```

3.  **运行程序**：打开新终端窗口，运行主程序。

    ```bash
    python main.py
    ```

4.  **观察日志**：

    ```text
    [1/4] 正在选题...
    [2/4] 正在写文案...
    [3/4] 正在搜集图片 (CLIP 语义去重中)...
    [4/4] 正在发布...
    ```
  

## 🛠️ 快速开始

### 1. 环境准备

确保已安装 Python 3.10+。安装项目依赖：

```bash
pip install requests openai pillow python-dotenv torch transformers

```

> ⚠️ **注意**：`torch` 和 `transformers` 用于运行 CLIP 模型，文件较大，请保持网络通畅。

### 2. 配置文件

在项目根目录创建 `.env` 文件，填入你的 API Key：

```ini
# DeepSeek / OpenAI 兼容接口
LLM_API_KEY=sk-xxxxxx
LLM_BASE_URL=[https://api.deepseek.com](https://api.deepseek.com)

# TMDB 电影数据库 (用于获取资料和图片)
TMDB_API_KEY=xxxxxx

# 搜索引擎 (可选)
SEARCH_API_KEY=xxxxxx

```

### 3. 登录小红书

首次使用需要扫码登录。运行登录工具（根据你的系统选择对应的版本）：

```bash
# 赋予执行权限
chmod +x xiaohongshu-login-darwin-arm64
# 运行
./xiaohongshu-login-darwin-arm64

```

扫码成功后，根目录会生成 `cookies.json`。

### 4. 启动 MCP 服务

发布功能依赖后台服务，请**保持此终端窗口开启**：

```bash
chmod +x xiaohongshu-mcp-darwin-arm64
./xiaohongshu-mcp-darwin-arm64

```

---

## 🖥️ 使用指南

### 启动全自动流程

新建一个终端窗口，运行主程序：

```bash
python main.py

```

程序将依次执行：`选题` -> `写文案` -> `搜图(去重)` -> `发布` -> `写入历史`。

### 进阶用法

#### 1. 🎯 插队模式 (手动指定电影)

如果你想发一部特定电影（例如《疯狂动物城2》），不需要改代码。
只需在根目录创建 `pending.txt`，写入电影名：

```text
疯狂动物城2
肖申克的救赎

```

**逻辑**：程序启动时会优先读取第一行《疯狂动物城2》。发布成功后，会自动将其从文件中删除。

#### 2. 🎨 投喂独家素材 (防止撞图)

如果你手头有一些独家的电影截图或海报，想优先使用：

1. 在 `资料/manual_materials/` 下创建**同名文件夹**，例如 `资料/manual_materials/疯狂动物城2/`。
2. 将图片放进去（支持 jpg/png/webp）。
3. **效果**：`VisualAgent` 会先加载这些图，如果数量不够 10 张，再去 TMDB 下载补齐。同时，TMDB 下载的图会和你的本地图进行 CLIP 比对，太像的会被自动丢弃。

#### 3. ⚙️ 调整去重严格度

在 `config.py` 中修改 `CLIP_THRESHOLD`：

* `0.75` (默认)：适中。
* `0.85`：非常宽松（只有几乎一模一样的图才会被删）。
* `0.65`：非常严格（构图、色调相似的也会被删）。

---

## ❓ 常见问题

**Q: 第一次运行下载模型很慢？**
A: `VisualAgent` 初始化时会从 HuggingFace 下载 CLIP 模型（约 500MB）。如果是国内网络，建议在代码开头设置 HF 镜像（代码中已内置 `hf-mirror.com`）。

**Q: 为什么生成的图片少于 10 张？**
A: 可能是 CLIP 阈值设得太低，导致大量 TMDB 的图被判定为“重复”并删除了；或者是 TMDB 本身该电影的剧照较少。

---

## 📜 免责声明

本项目仅供学习交流使用。请遵守小红书平台规范，合理使用自动化工具。