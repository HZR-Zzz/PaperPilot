# PaperPilot - 基于大模型与 Agent 架构的全流程科研助手

> 2026 全国高校 AI 大模型创新应用挑战赛（省赛）参赛作品
> 赛项：智领科研·意图驱动：基于大模型与 Agent 架构的全流程科研助手构建挑战赛

## 📖 项目简介
PaperPilot 是一款面向大学生与科研人员打造的全栈式智能科研助手 Agent。本项目突破了传统文献管理工具与简单对话 Chatbot 的局限，深度融合了大语言模型（LLM）的推理能力与多文献检索增强生成（RAG）技术。系统致力于实现从多模态文献解析、抗幻觉问答、跨语言溯源、到图论挖掘与学术辅助的全流程科研闭环。

## ✨ 核心特性
- [x] **模块一：多模态细粒度解析与语义去重**
  - **双引擎 PDF 解析**：基于 PyMuPDF 提取原生文本；针对扫描件，系统创新性地集成了本地轻量级离线 OCR 引擎（RapidOCR）与云端 Vision 大模型兜底，实现断网环境下的扫描件精准提取。
  - **大模型语义去重**：突破传统 SimHash 仅基于词频的局限，引入大模型进行深度语义特征对齐，精准识别同一论文的不同修订版本（如 Attention 的 v1 与 v7），并结合大模型自动生成修订差异总结。
- [x] **模块二：抗幻觉 RAG 与精准溯源**
  - **物理级溯源**：文本切块强制注入物理级页码标签，Prompt 最高指令约束回答必须附带 `[Page X]` 标记，前端以高亮胶囊形呈现。
  - **抗幻觉底线**：严守学术严谨性，对未提及的学术盲区坚决执行防幻觉拒答，甚至能指出原书相关的近似概念。
- [x] **模块三：双向联动阅读与划词三连击**
  - **双栏帧级联动**：基于 requestAnimationFrame 和物理防抖锁，实现中英双栏丝滑同步滚动，无死锁卡顿。
  - **物理级防幻觉翻译**：前端独创正则级清洗机制，强制保留英文标题，彻底斩断参考文献、图注及脚注被大模型误翻，保证翻译纯净度。
  - **无损引用溯源**：支持正文中 `[12]` 等引用标记一键平滑滚动至文末 References 并高亮闪烁。
  - **划词三连击**：精准捕捉划词位置，支持边缘碰撞自动翻转防遮挡，提供划词翻译与学术英语重写。
- [x] **模块四：arXiv 检索与智能推荐**
  - 集成真实 arXiv API 抓取最新领域论文；内置动态关键词匹配兜底库，保障断网情况下的系统高可用性。
- [x] **模块五：引用图谱挖掘与混合 RAG 综述生成**
  - **NetworkX 图论挖掘**：利用大模型真实抽取 PDF 参考文献，构建有向图并计算 PageRank 权重，挖掘领域“基石论文”。
  - **ECharts 学术级渲染**：采用强正则清洗图谱节点脏数据，完美实现 Tooltip 边缘换行与防遮挡。
  - **混合检索策略（Hybrid RAG）**：摒弃纯向量检索易跑题的缺陷，采用“全局摘要物理召回 + 局部语义细节检索”双轨策略，彻底杜绝大模型幻觉，生成零幻觉的全中文领域学术综述。
- [x] **模块六：数据可视化与学术写作 Copilot**
  - **CSV 智能图表**：自动读取用户上传的 CSV 数据并生成符合规范的 Matplotlib 图表。
  - **AI Figure Caption**：根据图表数据自动提炼核心趋势结论，生成专业学术图注。
  - **无幻觉框架生成**：输入核心 Idea，一键生成包含 Abstract, Introduction, Related Work 等结构的完整论文框架。
- [x] **扩展模块：多文献管理与上下文隔离**
  - 前端构建 DocumentList 组件，支持多文献列表渲染与高亮切换。
  - 后端通过 `doc_filter` 参数配合，实现多文献问答上下文的物理级隔离，杜绝“串台”。

## 🛠️ 技术栈选型
- **前端**：Next.js (App Router), React 19, TypeScript, ECharts, 现代深色学术风 UI
- **后端**：FastAPI (Python), Uvicorn, Tenacity (网络重试与熔断机制)
- **大模型与检索**：智谱 GLM-4 (OpenAI API 兼容), LangChain Text Splitters
- **向量数据库**：ChromaDB (本地持久化)
- **文档与图像解析**：PyMuPDF (fitz), RapidOCR (本地离线多模态引擎)

## 🚀 快速开始

### 1. 后端启动
进入 backend 目录并启动服务：
```bash
cd backend
python -m venv venv
# Windows 激活
venv\Scripts\activate
# 安装依赖 (请确保包含 pandas, matplotlib, rapidocr-onnxruntime, requests)
pip install -r requirements.txt
# 启动服务
uvicorn main:app --reload --port 8000

### 2. 环境变量配置
在 backend 目录下创建 .env 文件，填入您的 API Key（请勿上传至公开仓库）：
API_KEY=您的智谱API_KEY
BASE_URL=https://open.bigmodel.cn/api/paas/v4/
MODEL_NAME=glm-4-flash

### 3. 前端启动
进入 frontend 目录并启动：
cd frontend
npm install
npm run dev
访问 http://localhost:3000 即可体验系统。

## 👥 团队信息
- **参赛者**：黄泽柔
- **赛区/组别**：南部赛区/C组

---
### 🤝 AI 协同贡献声明

本项目在开发过程中，深度使用了 AI 编程助手（如 ChatGPT / DeepSeek / Cursor）进行协同开发。

- **系统设计**：项目全栈架构（Next.js + FastAPI）、RAG 检索管道及前后端 SSE 流式交互方案，由本人独立设计。
- **AI 辅助编码**：在代码落地过程中，通过 Prompt 调优，利用 AI 助手生成了部分 React 组件、PDF 正则清洗、System Prompt 约束等核心业务代码。
- **工程集成与验证**：本人对 AI 生成的代码进行了严格审查、本地环境调试及接口连通性测试，并针对大模型幻觉问题进行了多轮 Prompt 迭代优化，确保系统满足赛事对鲁棒性与功能闭环的要求。