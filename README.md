# 📖 自动小说生成工具

>- 目前开学了，没什么时间维护该项目，后续更新可能得等长假才能继续

<div align="center">
  
✨ **核心功能** ✨

| 功能模块          | 关键能力                          |
|-------------------|----------------------------------|
| 🎨 小说设定工坊    | 世界观架构 / 角色设定 / 剧情蓝图   |
| 📖 智能章节生成    | 多阶段生成保障剧情连贯性           |
| 🧠 状态追踪系统    | 角色发展轨迹 / 伏笔管理系统         |
| 🔍 语义检索引擎    | 基于向量的长程上下文一致性维护      |
| 📚 知识库集成      | 支持本地文档参考         |
| ✅ 自动审校机制    | 检测剧情矛盾与逻辑冲突          |
| 🖥 可视化工作台    | 全流程GUI操作，配置/生成/审校一体化 |

</div>

> 一款基于大语言模型的多功能小说生成器，助您高效创作逻辑严谨、设定统一的长篇故事

2025-03-05 添加角色库功能

2025-03-09 添加字数显示

2025-04-12 添加分卷功能，按分卷生成章节目录，修复剧情要点
---

## 📑 目录导航
1. [环境准备](#-环境准备)  
2. [项目架构](#-项目架构)  
3. [配置指南](#⚙️-配置指南)  
4. [运行说明](#🚀-运行说明)  
5. [使用教程](#📘-使用教程)  
6. [疑难解答](#❓-疑难解答)  

---

## 🛠 环境准备
确保满足以下运行条件：
- **Python 3.9+** 运行环境（推荐3.10-3.12之间）
- **pip** 包管理工具
- 有效API密钥：
  - 云端服务：OpenAI / DeepSeek 等
  - 本地服务：Ollama 等兼容 OpenAI 的接口

---


## 📥 安装说明
1. **下载项目**  
   - 通过 [GitHub](https://github.com) 下载项目 ZIP 文件，或使用以下命令克隆本项目：
     ```bash
     git clone https://github.com/YILING0013/AI_NovelGenerator
     ```

2. **安装编译工具（可选）**  
   - 如果对某些包无法正常安装，访问 [Visual Studio Build Tools](https://visualstudio.microsoft.com/zh-hans/visual-cpp-build-tools/) 下载并安装C++编译工具，用于构建部分模块包；
   - 安装时，默认只包含 MSBuild 工具，需手动勾选左上角列表栏中的 **C++ 桌面开发** 选项。

3. **安装依赖并运行**  
   - 打开终端，进入项目源文件目录：
     ```bash
     cd AI_NovelGenerator
     ```
   - 安装项目依赖：
     ```bash
     pip install -r requirements.txt
     ```
   - 安装完成后，运行主程序：
     ```bash
     python main.py
     ```

>如果缺失部分依赖，后续**手动执行**
>```bash
>pip install XXX
>```
>进行安装即可

## 🗂 项目架构
```
novel-generator/
├── main.py                      # 入口文件, 运行 GUI
├── ui.py                        # 图形界面
├── novel_generator.py           # 章节生成核心逻辑
├── consistency_checker.py       # 一致性检查, 防止剧情冲突
|—— chapter_directory_parser.py  # 目录解析
|—— embedding_adapters.py        # Embedding 接口封装
|—— llm_adapters.py              # LLM 接口封装
├── prompt_definitions.py        # 定义 AI 提示词
├── utils.py                     # 常用工具函数, 文件操作
├── config_manager.py            # 管理配置 (API Key, Base URL)
├── config.json                  # 用户配置文件 (可选)
└── vectorstore/                 # (可选) 本地向量数据库存储
```

---

## ⚙️ 配置指南
### 📌 基础配置（config.json）
```json
{
    "api_key": "sk-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
    "base_url": "https://api.openai.com/v1",
    "interface_format": "OpenAI",
    "model_name": "gpt-4o-mini",
    "temperature": 0.7,
    "max_tokens": 4096,
    "embedding_api_key": "sk-XXXXXXXXXXXXXXXXXXXXXXXXXXXXXX",
    "embedding_interface_format": "OpenAI",
    "embedding_url": "https://api.openai.com/v1",
    "embedding_model_name": "text-embedding-ada-002",
    "embedding_retrieval_k": 4,
    "topic": "星穹铁道主角星穿越到原神提瓦特大陆，拯救提瓦特大陆，并与其中的角色展开爱恨情仇的小说",
    "genre": "玄幻",
    "num_chapters": 120,
    "word_number": 4000,
    "filepath": "D:/AI_NovelGenerator/filepath"
}
```

### 🔧 配置说明
1. **生成模型配置**
   - `api_key`: 大模型服务的API密钥
   - `base_url`: API终端地址（本地服务填Ollama等地址）
   - `interface_format`: 接口模式
   - `model_name`: 主生成模型名称（如gpt-4, claude-3等）
   - `temperature`: 创意度参数（0-1，越高越有创造性）
   - `max_tokens`: 模型最大回复长度

2. **Embedding模型配置**
   - `embedding_model_name`: 模型名称（如Ollama的nomic-embed-text）
   - `embedding_url`: 服务地址
   - `embedding_retrieval_k`: 

3. **小说参数配置**
   - `topic`: 核心故事主题
   - `genre`: 作品类型
   - `num_chapters`: 总章节数
   - `word_number`: 单章目标字数
   - `filepath`: 生成文件存储路径

---

## 🚀 运行说明
### **方式 1：使用 Python 解释器**
```bash
python main.py
```
执行后，GUI 将会启动，你可以在图形界面中进行各项操作。

### **方式 2：打包为可执行文件**
如果你想在无 Python 环境的机器上使用本工具，可以使用 **PyInstaller** 进行打包：

```bash
pip install pyinstaller
pyinstaller main.spec
```
打包完成后，会在 `dist/` 目录下生成可执行文件（如 Windows 下的 `main.exe`）。

---

## 📘 使用教程
### 1. 初始配置
1. **启动软件后,先完成基本配置:**  
   - API参数设置(点击"配置"页签)
     - 选择模型接口(OpenAI/DeepSeek/Ollama等)
     - 填写API密钥和接口地址
     - 选择模型名称(如gpt-4/deepseek-chat等)
   - Embedding配置(用于知识库检索)
     - 选择嵌入向量模型接口
     - 配置相应的密钥和地址
   - 保存路径配置
     - 选择一个空白目录用于存放生成文件
   
### 2. 项目创建
1. **填写小说基本信息**
   - 主题/Topic (如"废土世界的AI叛乱"等)
   - 类型/Genre (如"科幻"/"奇幻"等)
   - 总章节数、每章字数
   - 分卷数量(默认为3卷)
   
2. **可选配置**
   - 在"用户指导"栏添加创作风格要求
   - 调整模型温度(temperature)参数
   - 配置最大生成长度(max_tokens)等

### 3. 小说生成步骤
1. **Step1. 生成架构**
   - 点击"生成设定"按钮
   - 系统生成完整的世界观架构和角色设定
   - 生成结果保存在Novel_architecture.txt中
   - 可在设定页面查看和手动修改

2. **Step2. 生成分卷**
   - 点击"生成分卷大纲"按钮
   - 基于设定生成各卷的大纲
   - 可选择全部生成或仅生成单卷
   - 支持断点续写(从指定卷开始)
   - 结果保存在Novel_Volume.txt中
   
3. **Step3. 生成目录**
   - 点击"生成章节目录"按钮
   - 基于分卷大纲生成详细章节目录
   - 可选择生成全部或单卷目录
   - 支持断点续写和自动保存
   - 结果保存在Novel_directory.txt中

4. **Step4. 生成草稿**
   - 设置当前章节号
   - 填写可选的本章指导信息
   - 点击"生成草稿"按钮
   - 草稿生成后可在左侧编辑框内查看
   
5. **一致性审校**
   - 点击"一致性审校"按钮检查当前内容
   - 审校结果可以：
     * 复制到内容指导框中，添加自己的想法后用于改写
     * 直接粘贴到改写提示词框内进行修改
   - 审校报告自动保存至plot_arcs.txt

6. **Step5. 改写章节**
   - 点击"改写章节"按钮
   - 在弹出的提示词编辑框中：
     * 可直接修改提示词
     * 可添加一致性审校的建议
     * 可加入自己的创作想法
   - 确认后生成改写内容
   
7. **Step6. 定稿章节**
   - 确认内容满意后点击"定稿"按钮
   - 系统将：
     * 更新全局摘要(global_summary.txt)
     * 更新角色状态(character_state.txt)
     * 更新剧情要点(plot_arcs.txt)
     * 保存最终章节内容

8. **后期修改**
   - 可随时修改已定稿章节：
     * 复制章节内容到主界面编辑框
     * 填写正确的章节号
     * 可以重新进行一致性审校
     * 可以重新进行章节改写
   - 建议修改后重新定稿以保持数据一致性

### 4. 辅助功能
1. **知识库管理**
   - 导入参考资料到知识库
   - 自动向量化存储便于检索
   - 生成时自动引用相关内容
   
2. **角色库系统** 
   - 记录角色信息和状态变化
   - 支持添加/编辑角色信息
   - 自动更新角色状态

3. **其他功能**
   - 支持中途暂停/继续生成
   - 错误自动保存已生成内容
   - 日志输出记录生成过程

4. **剧情要点追踪**
   - 自动记录重要剧情转折点
   - 维护伏笔埋设与回收状态
   - 追踪主要角色动机链条
   - 记录悬念和谜题解决进度
   - 支持在生成过程中实时更新
   - 可通过plot_arcs.txt查看完整记录

---

## ❓ 疑难解答
### Q1: Expecting value: line 1 column 1 (char 0)

该问题大概率由于API未正确响应造成，也许响应了一个html？其它内容，导致出现该报错；


### Q2: HTTP/1.1 504 Gateway Timeout？
确认接口是否稳定；

### Q3: 如何切换不同的Embedding提供商？
在GUI界面中对应输入即可。

---

如有更多问题或需求，欢迎在**项目 Issues** 中提出。
