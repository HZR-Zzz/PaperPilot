# PaperPilot - 基于大模型与 Agent 架构的全流程科研助手

> 2026 全国高校 AI 大模型创新应用挑战赛（省赛）参赛作品
> 赛项：智领科研·意图驱动：基于大模型与 Agent 架构的全流程科研助手构建挑战赛

## 📖 项目简介
PaperPilot 是一款面向大学生与科研人员打造的全栈式智能科研助手 Agent。本项目突破了传统文献管理工具与简单对话 Chatbot 的局限，深度融合了大语言模型（LLM）的推理能力与多文献检索增强生成（RAG）技术。系统致力于实现从文献解析、抗幻觉问答、跨语言溯源到学术辅助的全流程科研闭环。

## ✨ 核心特性（持续开发中）
- [x] **模块一：细粒度解析与语义去重**
  - 基于 PyMuPDF 的高效 PDF 解析机制。
  - 引入 SimHash 算法进行文献语义级去重，精准识别同一论文的不同版本（如 v1 与 v7），并结合大模型自动生成修订差异总结。
- [x] **模块二：抗幻觉 RAG 与精准溯源**
  - 基于 ChromaDB 构建混合检索策略，支持中英跨语言检索优化。
  - 文本切块强制注入物理级页码标签，回答强制附带 `[Page X]` 溯源标记，前端高亮显示。
  - 严守学术底线，结合自定义 Prompt 规则，对未提及的学术盲区坚决执行防幻觉拒答。
- [x] **模块三：双向联动阅读与划词翻译**
  - **双栏帧级联动**：基于 requestAnimationFrame 和防抖锁，实现中英双栏丝滑同步滚动。
  - **物理级防幻觉拦截**：前端独创正则级清洗机制，强制保留英文标题，彻底斩断参考文献（References）、图注（Figure/Table）及杂乱脚注被误翻，保证翻译纯净度。
  - **无损引用溯源**：支持正文中 `[12]` 等引用标记一键平滑滚动跳转至文末参考文献并高亮闪烁。
  - **划词三连击**：精准捕捉划词位置，支持边缘碰撞翻转防遮挡，提供划词翻译与学术英语重写交互。
- [x] **模块五：多文献管理与上下文隔离**
  - 前端侧边栏构建 DocumentList 组件，支持多文献列表渲染、高亮切换与删除。
  - 后端通过 `doc_filter` 参数配合，实现多文献问答上下文的物理级隔离，杜绝“串台”。
- [ ] **模块四：arXiv 检索与智能推荐** (开发中)
- [ ] **模块六：学术写作辅助与数据可视化** (开发中)

## 🛠️ 技术栈选型
- **前端**：Next.js (App Router), React 19, TypeScript, 现代深色学术风 UI
- **后端**：FastAPI (Python), Uvicorn, Tenacity (网络重试机制)
- **大模型与检索**：DeepSeek-V3 (OpenAI API 兼容), LangChain Text Splitters
- **向量数据库**：ChromaDB (本地持久化)
- **文档解析**：PyMuPDF (fitz)

## 🚀 快速开始

### 1. 后端启动
进入 backend 目录并启动服务：
```bash
cd backend
python -m venv venv
# Windows 激活
venv\Scripts\activate
# 安装依赖
pip install -r requirements.txt
# 启动服务
uvicorn main:app --reload --port 8000

### 2. 环境变量配置
在 backend 目录下创建 .env 文件，填入您的 API Key（请勿上传至公开仓库）：
API_KEY=sk-您的密钥
BASE_URL=https://api.deepseek.com
MODEL_NAME=deepseek-chat

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