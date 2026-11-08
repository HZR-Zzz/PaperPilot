import os
import re
import json
import base64
import io
import math
import difflib  # 🚨 用于绝对确定的文本相似度计算
import fitz
import chromadb
import networkx as nx
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib
import requests
import xml.etree.ElementTree as ET
from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv
from tenacity import retry, wait_fixed, stop_after_attempt
from langchain_text_splitters import RecursiveCharacterTextSplitter
from rapidocr_onnxruntime import RapidOCR

from mpl_toolkits.mplot3d import Axes3D  # noqa: F401

matplotlib.use('Agg')
load_dotenv()
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

client = OpenAI(api_key=os.getenv("API_KEY"), base_url=os.getenv("BASE_URL"))
chroma_client = chromadb.PersistentClient(path="./chroma_db")
collection = chroma_client.get_or_create_collection(name="papers")

ocr_engine = RapidOCR()


@retry(wait=wait_fixed(2), stop=stop_after_attempt(3))
def call_llm(prompt, is_json=False):
    kwargs = {
        "model": os.getenv("MODEL_NAME"),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0, "top_p": 1.0, "timeout": 90
    }
    if is_json:
        kwargs["response_format"] = {"type": "json_object"}
    return client.chat.completions.create(**kwargs)


@retry(wait=wait_fixed(2), stop=stop_after_attempt(3))
def call_llm_stream(messages):
    return client.chat.completions.create(
        model=os.getenv("MODEL_NAME"), messages=messages, stream=True,
        temperature=0.0, top_p=1.0, timeout=90
    )


# ==========================================
# 模块一：PDF 解析与入库（双引擎 OCR）
# ==========================================
def _parse_pdf_bytes(contents: bytes, filename: str):
    doc = fitz.open(stream=contents, filetype="pdf")
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000, chunk_overlap=200, length_function=len
    )
    all_chunks, all_metadatas, all_ids, full_text = [], [], [], ""
    
    total_pages = len(doc)
    print(f"📖 开始解析文档 [{filename}]，共 {total_pages} 页...")

    for page_num, page in enumerate(doc, start=1):
        if page_num % 50 == 0 or page_num == 1:
            print(f"⏳ 正在解析第 {page_num} / {total_pages} 页... 已提取 {len(all_chunks)} 个文本块")
            
        page_text = page.get_text()

        if not page_text.strip():
            print(f"📄 检测到第 {page_num} 页为扫描件，启动本地 OCR...")
            pix = page.get_pixmap(dpi=200)
            img_bytes = pix.tobytes("png")

            try:
                result, _ = ocr_engine(img_bytes)
                if result:
                    page_text = "\n".join([line[1] for line in result])
                    print(f"✅ 第 {page_num} 页本地 OCR 提取成功，共 {len(page_text)} 个字符。")
            except Exception as e:
                print(f"⚠️ 本地 OCR 失败: {e}")

            if not page_text.strip():
                base64_image = base64.b64encode(img_bytes).decode('utf-8')
                try:
                    vision_prompt = "请提取这张学术论文图片中的所有文本内容，保持原有的排版格式。绝对不要输出任何废话，只输出纯文本。"
                    response = client.chat.completions.create(
                        model=os.getenv("MODEL_NAME"),
                        messages=[{"role": "user", "content": [
                            {"type": "text", "text": vision_prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
                        ]}],
                        temperature=0.0, timeout=120
                    )
                    page_text = response.choices[0].message.content
                except Exception as e:
                    print(f"Vision OCR 失败: {e}")
                    page_text = f"[扫描页 {page_num}，OCR提取失败]"

        if not page_text.strip():
            continue
            
        # 🚨 基于排版特征动态过滤目录页/大纲页（防止语义检索干扰）
        dot_count = page_text.count("...")
        if dot_count > 10 and len(page_text.split("\n")) > 20:
            print(f"⏭️ 检测到第 {page_num} 页疑似目录（包含大量索引点号），已自动跳过。")
            continue

        full_text += page_text + "\n"
        chunks = text_splitter.split_text(page_text)
        for i, chunk in enumerate(chunks):
            all_chunks.append(f"《第 {page_num} 页》：{chunk}")
            all_metadatas.append({"page": page_num, "source": filename})
            all_ids.append(f"{filename}_p{page_num:03d}_c{i:03d}")

    print(f"✅ 文档 [{filename}] 解析完成，共提取 {len(all_chunks)} 个文本块。")
    return all_chunks, all_metadatas, all_ids, full_text


def extract_title_and_refs(text: str) -> dict:
    head = text[:3000]
    ref_start = re.search(r'(?i)\n\s*(References|Bibliography)\s*\n', text)
    ref_text = text[ref_start.start():ref_start.start() + 3000] if ref_start else text[-3000:]
    prompt = f"""你是学术文献解析器。请返回严格 JSON：
{{"paper_title": "本论文完整标题", "refs": ["作者 (年份) 标题核心词", "..."]}}
refs 提取 5-8 篇核心参考文献，每项格式如 "Vaswani (2017) Attention"。无法提取返回空数组。
只输出 JSON，不要任何解释。

论文开头：
{head}

参考文献片段：
{ref_text}"""
    try:
        res = call_llm(prompt, is_json=True)
        data = json.loads(res.choices[0].message.content)
        title = data.get("paper_title") or ""
        refs = data.get("refs") or []
        if not isinstance(title, str):
            title = ""
        if not isinstance(refs, list):
            refs = []
        refs = [r for r in refs if isinstance(r, str)]
        return {"paper_title": title.strip(), "refs": refs}
    except Exception:
        return {"paper_title": "", "refs": []}


def process_meta_task(filename: str, full_text: str):
    print(f"⏳ 后台开始提取 [{filename}] 的标题和参考文献...")
    meta = extract_title_and_refs(full_text)
    real_refs = meta["refs"]
    try:
        collection.add(
            documents=["-".join(real_refs) if real_refs else f"《{filename}》参考文献未解析"],
            metadatas=[{
                "page": 999,
                "source": filename,
                "type": "references",
                "refs": json.dumps(real_refs),
                "paper_title": meta["paper_title"],
            }],
            ids=[f"{filename}_references"]
        )
        print(f"✅ [{filename}] 后台参考文献提取完毕，共 {len(real_refs)} 条！")
    except Exception as e:
        print(f"❌ [{filename}] 后台提取写入失败: {e}")


@app.post("/upload")
def upload_pdf(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    try:
        contents = file.file.read()
        all_chunks, all_metadatas, all_ids, full_text = _parse_pdf_bytes(
            contents, file.filename
        )
        
        if all_chunks:
            print("🧹 清理旧的文献数据...")
            try:
                collection.delete(where={"source": file.filename})
            except Exception:
                pass
            
            print(f"📦 开始分批写入 {len(all_chunks)} 个文本块（这步比较耗时，请耐心等待）...")
            batch_size = 500
            for i in range(0, len(all_chunks), batch_size):
                collection.add(
                    documents=all_chunks[i:i+batch_size],
                    metadatas=all_metadatas[i:i+batch_size],
                    ids=all_ids[i:i+batch_size]
                )
                print(f"  已写入 {min(i+batch_size, len(all_chunks))} / {len(all_chunks)} 块")
            print("✅ 所有文本块入库完毕！")

        background_tasks.add_task(process_meta_task, file.filename, full_text)

        html_text = re.sub(r'\n\[(\d+)\]', r'\n<span id="ref-\1">[\1]</span>', full_text)
        return {
            "status": "success",
            "message": f"成功解析 {len(all_chunks)} 个文本块！(参考文献正在后台提取)",
            "text": html_text,
        }
    except Exception as e:
        print(f"❌ 上传解析严重报错: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/delete_doc")
async def delete_doc(filename: str = Form(...)):
    try:
        print(f"🗑️ 正在删除文献：{filename}")
        collection.delete(where={"source": filename})
        return {"status": "success", "message": f"成功删除文献 {filename}"}
    except Exception as e:
        print(f"❌ 删除文献严重报错: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/parse_only")
def parse_only(file: UploadFile = File(...)):
    try:
        contents = file.file.read()
        _, _, _, full_text = _parse_pdf_bytes(contents, file.filename)
        html_text = re.sub(r'\n\[(\d+)\]', r'\n<span id="ref-\1">[\1]</span>', full_text)
        return {"status": "success", "text": html_text}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ==========================================
# 模块二：RAG 问答与溯源 (混合检索版)
# ==========================================
class ChatRequest(BaseModel):
    message: str
    doc_filter: str = ""


@app.post("/chat")
async def chat_endpoint(req: ChatRequest):
    try:
        search_queries = [req.message]
        if re.search('[\u4e00-\u9fa5]', req.message):
            try:
                trans_prompt = f"""将以下问题翻译成英文，并提取出最核心的 3 个英文检索词。
格式严格如下（不要输出任何其他解释）：
翻译：<完整英文翻译>
关键词：<关键词1> <关键词2> <关键词3>
问题：{req.message}"""
                trans_res = call_llm(trans_prompt)
                ans_text = trans_res.choices[0].message.content
                for line in ans_text.split('\n'):
                    if "翻译：" in line:
                        search_queries.append(line.replace("翻译：", "").strip())
                    elif "关键词：" in line:
                        search_queries.append(line.replace("关键词：", "").strip())
            except Exception as e:
                print("翻译扩展失败:", e)

        # 1. Dense 向量检索 (语义级别)
        query_kwargs = {"query_texts": search_queries, "n_results": 20}
        if req.doc_filter:
            query_kwargs["where"] = {"source": req.doc_filter}
        results = collection.query(**query_kwargs)

        context = ""
        top_page = None  # 动态记录本次检索最相关的真实页码，用于兜底

        if results and results['documents'] and results['documents'][0]:
            seen_docs = set()
            for i, doc in enumerate(results['documents'][0]):
                meta = results['metadatas'][0][i]
                page = meta.get('page')
                
                # 🚨 核心防御：绝对不要把参考文献块（Page 999）发给大模型
                if page == 999 or meta.get('type') == 'references':
                    continue
                    
                if doc in seen_docs:
                    continue
                seen_docs.add(doc)
                
                source = meta.get('source', '未知文献')
                context += f"[文献: {source} | Page {page}]: {doc}\n\n"
                
                # 获取第一个真实正文页码作为兜底
                if top_page is None:
                    top_page = page

        # 2. Sparse 稀疏检索 (字符硬匹配级别)
        if req.doc_filter:
            try:
                dynamic_tokens = re.findall(r'[a-zA-Z]{3,}|\d+\.\d+|β\d?|α\d?|γ\d?', req.message)
                if dynamic_tokens:
                    dynamic_tokens = list(set([t.lower() for t in dynamic_tokens]))[:3]
                    hard_match_docs = []
                    
                    for token in dynamic_tokens:
                        if len(token) < 3 and token.isalpha():
                            continue
                            
                        match_res = collection.get(
                            where={"source": req.doc_filter},
                            where_document={"$contains": token},
                            limit=3
                        )
                        if match_res and match_res['documents']:
                            for doc, meta in zip(match_res['documents'], match_res['metadatas']):
                                if meta.get('type') != 'references' and doc not in context and doc not in hard_match_docs:
                                    hard_match_docs.append(f"[文献: {meta.get('source')} | Page {meta.get('page')} | 稀疏检索命中]: {doc}")
                                    if top_page is None:
                                        top_page = meta.get('page')

                    if hard_match_docs:
                        print(f"✅ 动态稀疏检索命中 {len(hard_match_docs)} 个真实字符块，注入上下文最前方！")
                        context = "\n\n".join(hard_match_docs[:3]) + "\n\n" + context
            except Exception as e:
                print("动态稀疏检索兜底失败:", e)

        system_prompt = f"""你是 PaperPilot 科研助手。你的任务是阅读学术文献并回答用户问题。
【格式硬性要求（最高优先级）】：
1. 你的所有回答，必须在句末附带来源的物理页码。格式绝对严格为：`[Page X]`（X 必须为纯数字）。
2. 🚨 **【页码来源铁律】**：
   - 系统的真实物理页码已经以 `[文献: xxx | Page X]` 的格式标注在参考内容开头。
   - 正文中出现的所有其它纯数字（如页眉、页脚、正文边缘的印刷数字）统统是干扰项，绝对禁止作为来源页码！
   - 你必须只提取头部 `[文献: xxx | Page X]` 后面的数字作为输出。

【内容最高指令】：
1. 你必须**只**基于参考内容回答，严禁使用你自带的通用世界知识。
2. 如果用户的问题与科研完全无关，直接回答：“抱歉，我是科研助手，只能回答与学术文献相关的问题。”（🚨绝对不要在此回答后附带 [Page X]）
3. 如果参考内容确实没有提及用户问的数据，直接回答“未在文献中找到相关数据。”（🚨绝对不要在此回答后附带 [Page X]）
4. 如果用户询问“这篇文献讲了什么”，请根据参考内容提炼核心贡献，并附带页码。
5. 🚨 **无论用户使用什么语言提问，请统一使用中文（简体）输出。学术专有名词（如 Transformer）可保留英文。**

【参考内容】：
{context if context else "暂无文献数据"}
"""
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": req.message}]

        def generate():
            full_text = ""
            try:
                response = call_llm_stream(messages)
                for chunk in response:
                    if chunk.choices[0].delta.content:
                        text = chunk.choices[0].delta.content
                        full_text += text
                        yield f"data: {text}\n\n"
                
                # 代码级终极兜底：只在正常回答时，若大模型通篇未输出页码才补全
                if top_page is not None and "[Page" not in full_text:
                    # 🚨 核心防御：如果大模型触发了拒答机制，不要画蛇添足去补页码
                    refusal_keywords = ["抱歉", "未在文献中", "未找到", "无法回答", "无法提供"]
                    if not any(kw in full_text for kw in refusal_keywords):
                        yield f"data: [Page {top_page}]\n\n"
                    
            except Exception as e:
                yield f"data: [Error] 网络失败: {str(e)}\n\n"
        return StreamingResponse(generate(), media_type="text/event-stream")
    except Exception as e:
        return {"error": str(e)}


# ==========================================
# 模块一：语义去重与差异比对
# ==========================================
@app.post("/dedup")
async def check_dedup(text1: str = Form(...), text2: str = Form(...)):
    try:
        # 🚨 算法确定层：使用 difflib 计算绝对确定的文本相似度，杜绝大模型估算带来的随机波动
        matcher = difflib.SequenceMatcher(None, text1[:15000], text2[:15000])
        similarity_score = round(matcher.ratio() * 100, 1)
        
        # 阈值判定（>= 85% 认为是高度相似版本）
        is_duplicate = similarity_score >= 85.0
        
        # 🚨 大模型归因层：不负责算分，只负责根据确定的分数分析具体差异，强制中文输出
        prompt = f"""你是一个学术查重引擎。系统底层算法已经确定这两段文本的相似度为 {similarity_score}%。
请对比这两段文本，指出它们存在的具体细微差异（如作者列表、BLEU分数、参考编号、图表更新等），并给用户提出处理建议。
🚨 **无论原文是什么语言，你必须严格使用中文（简体）输出这段描述，学术专有名词（如 BLEU、NIPS）可保留英文。**

返回严格 JSON 格式：
{{"message": "一段话描述差异和建议"}}

文本1片段：
{text1[:4000]}

文本2片段：
{text2[:4000]}"""
        
        try:
            res = call_llm(prompt, is_json=True)
            data = json.loads(res.choices[0].message.content)
            message = data.get("message", "文本高度相似，建议保留最新版本。")
        except Exception as e:
            print("大模型分析差异失败，使用默认建议:", e)
            message = "文本高度相似，建议检查引用的准确性和完整性。"
        
        return {
            "similarity": similarity_score,
            "is_duplicate": is_duplicate,
            "message": message
        }
    except Exception as e:
        return {"similarity": 0, "is_duplicate": False, "message": f"语义比对失败: {str(e)}"}


@app.post("/diff")
async def compare_diff(text_old: str = Form(...), text_new: str = Form(...)):
    try:
        prompt = f"你是一个学术审稿人。请用 3 句话总结【新版】相较于【旧版】的主要修订差异。\n旧版片段：\n{text_old[:3000]}\n\n新版片段：\n{text_new[:3000]}"
        response = call_llm(prompt)
        return {"diff_summary": response.choices[0].message.content}
    except Exception as e:
        return {"error": f"大模型接口报错: {str(e)}"}


# ==========================================
# 模块三：翻译与重写
# ==========================================
class TextActionRequest(BaseModel):
    text: str
    action: str


@app.post("/text_action")
async def text_action(req: TextActionRequest):
    try:
        if req.action == "translate":
            user_prompt = f"【翻译规则】1.保持术语英文原文。2.公式、引用编号保留。3.保留换行。4.只输出纯中文译文，不要废话。\n待翻译内容：\n{req.text}"
        elif req.action == "rewrite":
            user_prompt = f"【重写规则】1.用严谨的地道学术英语重写。2.保持原意不捏造。3.去冗余。4.只输出纯英文段落，不要废话。\n待重写内容：\n{req.text}"
        else:
            return {"error": "未知操作"}
        response = call_llm(user_prompt)
        return {"result": response.choices[0].message.content.replace("<text>", "").replace("</text>", "").strip()}
    except Exception as e:
        return {"error": str(e)}


# ==========================================
# 模块四：arXiv 检索
# ==========================================
class ArxivReq(BaseModel):
    query: str = "cs.CL"


@app.post("/arxiv_search")
async def arxiv_search(req: ArxivReq):
    try:
        url = f"http://export.arxiv.org/api/query?search_query=all:{req.query}&max_results=3"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            namespace = {'atom': 'http://www.w3.org/2005/Atom'}
            entries = root.findall('atom:entry', namespace)

            real_results = []
            for entry in entries:
                title = entry.find('atom:title', namespace).text.strip().replace('\n', ' ')
                published = entry.find('atom:published', namespace).text[:10]
                summary = entry.find('atom:summary', namespace).text.strip().replace('\n', ' ')
                authors = ", ".join([author.find('atom:name', namespace).text for author in entry.findall('atom:author', namespace)])

                real_results.append({
                    "title": title,
                    "authors": authors,
                    "published": published,
                    "summary": summary,
                    "source": "arxiv_live",
                })

            if real_results:
                return {"status": "success", "data": real_results}
    except Exception as e:
        print(f"🌐 真实 arXiv 接口请求失败/超时，启用离线兜底: {e}")

    mock_db = [
        {"title": "Attention Is All You Need", "authors": "Vaswani et al.", "published": "2017-06-12", "summary": "The dominant sequence transduction models...", "source": "mock_fallback"},
        {"title": "BERT: Pre-training of Deep Bidirectional Transformers", "authors": "Devlin et al.", "published": "2018-10-11", "summary": "We introduce a new language representation model...", "source": "mock_fallback"},
    ]
    return {"status": "success", "data": mock_db}


# ==========================================
# 模块五：图谱挖掘与综述生成
# ==========================================
class GraphRequest(BaseModel):
    doc_filter: str = ""


@app.post("/graph")
async def get_citation_graph(req: GraphRequest):
    try:
        if not req.doc_filter:
            return {"nodes": [], "links": [], "message": "请先选择一篇文献"}

        current_paper = req.doc_filter
        print(f"📊 正在为 [{current_paper}] 生成图谱...")

        G = nx.DiGraph()
        G.add_node(current_paper)

        references = []
        try:
            ref_res = collection.get(where={"source": current_paper})
            if ref_res and ref_res['metadatas']:
                for meta in ref_res['metadatas']:
                    if meta.get("type") == "references" and "refs" in meta:
                        loaded = json.loads(meta.get("refs") or "[]")
                        if isinstance(loaded, list):
                            references = [r for r in loaded if isinstance(r, str)]
                        break
        except Exception as e:
            print(f"⚠️ 读取元数据失败: {e}")

        if not references:
            return {
                "nodes": [{"name": current_paper, "value": 1.0, "symbolSize": 30}],
                "links": [],
                "message": "未从该文献解析到参考文献，仅显示当前论文节点（不伪造引用）",
            }

        print(f"✅ 提取到 {len(references)} 篇引用文献")
        for ref in references:
            G.add_edge(current_paper, ref)

        pagerank_scores = nx.pagerank(G)
        nodes = [
            {
                "name": re.sub(r'^([\(\[]\d+[\)\]]|\d+[\.\)])\s*', '', n).strip(),
                "value": round(pagerank_scores[n] * 1000, 2),
                "symbolSize": 30 + pagerank_scores[n] * 15000,
            }
            for n in G.nodes()
        ]
        links = [{"source": s, "target": t} for s, t in G.edges()]

        print(f"🎉 图谱生成成功，共 {len(nodes)} 个节点。")
        return {"nodes": nodes, "links": links, "message": "ok"}
    except Exception as e:
        print(f"❌ 图谱生成严重报错: {e}")
        return {"nodes": [], "links": [], "message": f"图谱生成失败: {e}"}


class ReviewRequest(BaseModel):
    topic: str


@app.post("/generate_review")
async def generate_review(req: ReviewRequest):
    try:
        all_chunks = collection.get(where={"source": req.topic})
        macro_context_parts = []
        if all_chunks and all_chunks['documents']:
            sorted_chunks = sorted(zip(all_chunks['ids'], all_chunks['documents']), key=lambda x: x[0])
            macro_context_parts = [doc for _, doc in sorted_chunks[:3] if "《第" in doc]

        search_results = collection.query(
            query_texts=["core architecture and contribution", "future work and limitations"],
            n_results=3,
            where={"source": req.topic}
        )

        local_context_parts = []
        if search_results and search_results['documents'] and search_results['documents'][0]:
            for doc, meta in zip(search_results['documents'][0], search_results['metadatas'][0]):
                if meta.get('page') != 999 and doc not in local_context_parts:
                    local_context_parts.append(doc)

        context = "\n\n".join(macro_context_parts + local_context_parts)

        prompt = f"""你是一个顶尖的学术综述专家。请针对「{req.topic}」这一方向，严格根据以下【论文真实内容】生成一段精炼的学术综述。

要求：
1. 第一段：总结这篇论文提出的核心架构及其演进意义。
2. 第二段：指出这篇论文中的“基石算法”或机制的真实贡献。
3. 第三段：基于论文内容展望未来的研究方向（Future Work）。
4. 🚨 **必须使用中文（简体）输出！绝对不能使用英文！学术专有名词（如 Transformer, Attention）可以保留英文，但句子必须是中文。**

【论文真实内容（摘要与核心检索块）】：
{context if context else "暂无详细内容"}"""

        response = call_llm(prompt)
        return {"review": response.choices[0].message.content}
    except Exception as e:
        return {"error": str(e)}


# ==========================================
# 模块六：CSV 转图表与论文框架
# ==========================================
class CSVRequest(BaseModel):
    csv_text: str
    chart_type: str = "auto"


def dataframe_to_markdown(df: pd.DataFrame, max_rows: int = 20) -> str:
    d = df.head(max_rows).copy()
    cols = [str(c) for c in d.columns]
    lines = [
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join(["---"] * len(cols)) + " |",
    ]
    for _, row in d.iterrows():
        vals = []
        for v in row:
            s = "" if pd.isna(v) else str(v)
            s = s.replace("|", "\\|").replace("\n", " ")
            vals.append(s)
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


@app.post("/csv_to_chart")
async def csv_to_chart(req: CSVRequest):
    fig = None
    try:
        if not req.csv_text.strip():
            return {"error": "CSV 内容为空"}
        if len(req.csv_text.encode("utf-8")) > 2_000_000:
            return {"error": "CSV 文件过大，请控制在 2MB 以内"}

        df = pd.read_csv(io.StringIO(req.csv_text))
        df = df.dropna(how="all").dropna(axis=1, how="all")
        if df.empty:
            return {"error": "CSV 解析后为空"}
        if len(df.columns) > 30:
            return {"error": "CSV 列数过多，请控制在 30 列以内"}
        if len(df) > 5000:
            df = df.head(5000)

        df.columns = [str(c).strip() for c in df.columns]
        numeric_cols = df.select_dtypes(include="number").columns.tolist()
        if not numeric_cols:
            return {"error": "未检测到数值列，无法生成图表"}

        # 智能过滤：如果第一列是连续递增的序号（如 epoch, id），且还有其他数值列，则将其视为 X 轴，不作为数据绘制
        first_col_name = df.columns[0]
        if first_col_name in numeric_cols and len(numeric_cols) > 1:
            diffs = df[first_col_name].diff().dropna()
            if not diffs.empty and (diffs > 0).all():
                numeric_cols.remove(first_col_name)

        table_markdown = dataframe_to_markdown(df, max_rows=20)

        chart_type = (req.chart_type or "auto").lower()
        allowed = {"auto", "table", "line", "bar", "radar", "radar3d"}
        if chart_type not in allowed:
            chart_type = "auto"

        if chart_type == "auto":
            if len(numeric_cols) >= 3 and 1 < len(df) <= 8:
                chart_type = "radar3d"
            elif len(df) >= 6:
                chart_type = "line"
            else:
                chart_type = "bar"

        image_base64 = ""
        if chart_type != "table":
            fig = plt.figure(figsize=(8, 5))
            first_col = df.columns[0]

            if chart_type == "line":
                ax = fig.add_subplot(111)
                for y in numeric_cols:
                    ax.plot(df[first_col].astype(str), df[y], marker="o", label=str(y))
                ax.set_xlabel(str(first_col))
                ax.set_ylabel("Value")
                ax.set_title("Line Chart")
                ax.legend()
                ax.tick_params(axis="x", rotation=30)

            elif chart_type == "bar":
                ax = fig.add_subplot(111)
                plot_df = df.head(12).copy()
                
                x = range(len(plot_df))
                width = 0.8 / len(numeric_cols)
                
                for i, col in enumerate(numeric_cols):
                    ax.bar([p + width * i for p in x], plot_df[col], width=width, label=str(col))
                
                ax.set_xticks([p + width * (len(numeric_cols)-1) / 2 for p in x])
                ax.set_xticklabels(plot_df[first_col].astype(str), rotation=0)
                
                ax.set_xlabel(str(first_col))
                ax.set_title("Bar Chart")
                ax.legend()
                ax.grid(axis='y', linestyle='--', alpha=0.7)

            elif chart_type in {"radar", "radar3d"}:
                use_cols = numeric_cols[:5]
                if len(use_cols) < 3:
                    ax = fig.add_subplot(111)
                    plot_df = df.head(12).copy()
                    plot_df.set_index(first_col)[numeric_cols].plot(kind="bar", ax=ax)
                    ax.set_title("Bar Chart")
                    ax.tick_params(axis="x", rotation=30)
                    chart_type = "bar"
                else:
                    norm = df[use_cols].apply(pd.to_numeric, errors="coerce").fillna(0).astype(float)
                    if len(norm) > 8:
                        norm = norm.head(8)
                    labels = (
                        df[first_col].astype(str).head(len(norm)).tolist()
                        if first_col not in numeric_cols
                        else [str(i + 1) for i in range(len(norm))]
                    )
                    for c in use_cols:
                        mn, mx = norm[c].min(), norm[c].max()
                        norm[c] = (norm[c] - mn) / (mx - mn) if mx > mn else 0.5

                    angles = [i * 2 * math.pi / len(use_cols) for i in range(len(use_cols))]
                    angles += angles[:1]

                    if chart_type == "radar":
                        ax = fig.add_subplot(111, polar=True)
                        for zi, (_, row) in enumerate(norm.iterrows()):
                            vals = row.tolist()
                            vals += vals[:1]
                            ax.plot(angles, vals, label=labels[zi])
                            ax.fill(angles, vals, alpha=0.05)
                        ax.set_xticks(angles[:-1])
                        ax.set_xticklabels(use_cols)
                        ax.set_yticklabels([])
                        ax.set_title("Radar Chart")
                        ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1), fontsize=8)
                    else:
                        ax = fig.add_subplot(111, projection="3d")
                        for zi, (_, row) in enumerate(norm.iterrows()):
                            vals = row.tolist()
                            vals += vals[:1]
                            xs = [v * math.cos(a) for v, a in zip(vals, angles)]
                            ys = [v * math.sin(a) for v, a in zip(vals, angles)]
                            zs = [zi] * len(vals)
                            ax.plot(xs, ys, zs, label=labels[zi])
                            ax.scatter(xs, ys, zs, s=8)
                        ax.set_zticks(list(range(len(norm))))
                        ax.set_zticklabels(labels, fontsize=7)
                        ax.set_xticks([])
                        ax.set_yticks([])
                        ax.set_title("3D Radar Chart (normalized)")
                        ax.legend(loc="upper right", bbox_to_anchor=(1.2, 1.0), fontsize=7)

            fig.tight_layout()
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
            buf.seek(0)
            image_base64 = base64.b64encode(buf.read()).decode("utf-8")

        stats_text = df.describe(include="all").to_string()[:3000]
        prompt = f"""你是一个学术写作专家。请严格根据以下 CSV 的真实列名、前几行和统计量，为图表生成学术规范 Figure Caption。
禁止编造数据中不存在的数值、趋势或结论。
图表类型：{chart_type}
列名：{list(df.columns)}
前5行：
{df.head(5).to_string()}
统计量：
{stats_text}

输出格式（只输出这两行，不要其他解释）：
第一行：英文 Figure Caption，以 "Figure 1." 开头。
第二行：中文核心结论，以 "中文结论：" 开头。"""
        try:
            caption = call_llm(prompt).choices[0].message.content.strip()
        except Exception:
            caption = (
                f"Figure 1. {chart_type} chart generated from uploaded CSV data. "
                f"中文结论：数据共 {len(df)} 行，数值列包括 {', '.join(numeric_cols)}，请结合表格与图形查看具体趋势。"
            )

        return {
            "image_base64": image_base64,
            "table_markdown": table_markdown,
            "caption": caption,
            "chart_type": chart_type,
            "columns": [str(c) for c in df.columns],
            "rows": int(len(df)),
        }
    except Exception as e:
        return {"error": f"CSV 图表生成失败: {str(e)}"}
    finally:
        if fig is not None:
            plt.close(fig)


class FrameworkReq(BaseModel):
    idea: str
    doc_filter: str = ""


def parse_json_loose(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```json\s*", "", text, flags=re.S)
    text = re.sub(r"^```\s*", "", text, flags=re.S)
    text = re.sub(r"\s*```$", "", text, flags=re.S)
    return json.loads(text)


@app.post("/generate_framework")
async def generate_framework(req: FrameworkReq):
    try:
        if not req.idea.strip():
            return {"error": "Idea 不能为空"}

        context_parts, candidates = [], []
        try:
            query_kwargs = {"query_texts": [req.idea], "n_results": 5}
            if req.doc_filter:
                query_kwargs["where"] = {"source": req.doc_filter}
            results = collection.query(**query_kwargs)
            if results and results["documents"] and results["documents"][0]:
                for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
                    if meta.get("type") == "references":
                        continue
                    src = meta.get("source", "未知文献")
                    page = meta.get("page", "?")
                    context_parts.append(f"[{src} | Page {page}] {doc}")
                    if src not in candidates:
                        candidates.append(src)
        except Exception as e:
            print(f"框架生成检索失败，将按无本地文献处理: {e}")

        candidate_text = "\n".join(f"- {c}" for c in candidates) if candidates else "（本地知识库暂无相关文献候选）"
        context_text = "\n\n".join(context_parts) if context_parts else "（本地知识库暂无相关文献片段）"

        prompt = f"""你是一个顶会审稿人。请根据用户 Idea 和本地真实文献片段，生成论文框架。
严格要求：
1. 必须包含 Abstract、Introduction、Related Work、Method、Conclusion。
2. References 只能从【候选参考文献】中选择，严禁编造候选列表之外的文献。
3. 如果候选为空，References 必须为空数组，并在框架中写明“本地知识库暂无相关文献，未生成引用”。
4. 同时生成一个 Mermaid 架构图脚本，必须以 "flowchart TD" 或 "graph TD" 开头。
5. 严格返回 JSON，不要输出 Markdown 代码围栏。JSON 格式：
{{"framework_markdown": "完整 Markdown 框架", "references": ["候选文献文件名"], "mermaid": "flowchart TD\\n    A[Idea] --> B[Method]"}}

用户 Idea：
{req.idea}

【候选参考文献】：
{candidate_text}

【本地真实文献片段】：
{context_text}"""

        try:
            res = call_llm(prompt, is_json=True)
            data = parse_json_loose(res.choices[0].message.content)
        except Exception:
            res = call_llm(prompt)
            data = parse_json_loose(res.choices[0].message.content)

        framework_md = data.get("framework_markdown") or ""
        if not isinstance(framework_md, str):
            framework_md = ""
        framework_md = framework_md.strip()

        raw_refs = data.get("references") or []
        if not isinstance(raw_refs, list):
            raw_refs = []
        references = [r for r in raw_refs if isinstance(r, str) and r in candidates]

        mermaid = data.get("mermaid") or ""
        if not isinstance(mermaid, str):
            mermaid = ""
        mermaid = mermaid.strip()

        if not framework_md:
            framework_md = (
                f"# 论文框架\n\n## Abstract\n围绕以下 Idea 展开：{req.idea}\n\n"
                "## Introduction\n待补充。\n\n## Related Work\n待补充。\n\n"
                "## Method\n待补充。\n\n## Conclusion\n待补充。\n\n"
                "本地知识库暂无相关文献，未生成引用。"
            )
        if not re.match(r"^\s*(flowchart|graph)\s+", mermaid):
            mermaid = (
                "flowchart TD\n"
                "    A[Research Idea] --> B[Abstract]\n"
                "    B --> C[Introduction]\n"
                "    C --> D[Related Work]\n"
                "    D --> E[Method]\n"
                "    E --> F[Conclusion]"
            )

        return {
            "framework": framework_md,
            "references": references,
            "mermaid": mermaid,
            "sources": candidates,
        }
    except Exception as e:
        return {"error": f"论文框架生成失败: {str(e)}"}