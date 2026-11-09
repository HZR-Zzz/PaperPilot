import os
import re
import json
import base64
import io
import math
import asyncio
import difflib
import time
from datetime import datetime
from typing import List

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

from config import (
    CONFIG, recent_cutoff_date, format_page_label, format_page_marker,
    format_chunk_id, format_rag_context, is_reference_page,
    is_reference_type, wrap_citation_anchors, clean_ref_name,
)

matplotlib.use('Agg')
load_dotenv()

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=CONFIG["cors_origins"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = OpenAI(api_key=os.getenv("API_KEY"), base_url=os.getenv("BASE_URL"))
chroma_client = chromadb.PersistentClient(path=CONFIG["chroma_path"])
collection = chroma_client.get_or_create_collection(name="papers")
ocr_engine = RapidOCR()


@retry(wait=wait_fixed(2), stop=stop_after_attempt(3))
def call_llm(prompt, is_json=False):
    kwargs = {
        "model": CONFIG["llm_model"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": CONFIG["llm_temperature"],
        "top_p": 1.0,
        "timeout": CONFIG["llm_timeout"],
    }
    if is_json:
        kwargs["response_format"] = {"type": "json_object"}
    return client.chat.completions.create(**kwargs)


@retry(wait=wait_fixed(2), stop=stop_after_attempt(3))
def call_llm_stream(messages):
    return client.chat.completions.create(
        model=CONFIG["llm_model"], messages=messages, stream=True,
        temperature=CONFIG["llm_temperature"], top_p=1.0,
        timeout=CONFIG["llm_timeout"],
    )


# ==========================================
# 文档登记表
# ==========================================
def _load_registry() -> dict:
    path = CONFIG["doc_registry_path"]
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"⚠️ 读取登记表失败: {e}")
        return {}


def _save_registry(data: dict):
    try:
        with open(CONFIG["doc_registry_path"], "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ 保存登记表失败: {e}")


def _extract_pdf_toc(contents: bytes) -> list:
    try:
        doc = fitz.open(stream=contents, filetype="pdf")
        raw_toc = doc.get_toc() or []
        doc.close()
        return [
            {"level": int(lv), "title": str(t).strip(), "page": int(pg)}
            for lv, t, pg in raw_toc if t and str(t).strip()
        ]
    except Exception as e:
        print(f"⚠️ 抽取 TOC 失败: {e}")
        return []


def _preview_pdf_text(contents: bytes) -> str:
    """取 PDF 前 N 页做查重比对（不解压全文，快）"""
    try:
        pre_doc = fitz.open(stream=contents, filetype="pdf")
        n_preview = min(CONFIG["dedup_preview_pages"], len(pre_doc))
        text = ""
        for i in range(n_preview):
            text += pre_doc[i].get_text() or ""
        pre_doc.close()
        return text[:CONFIG["dedup_preview_chars"]]
    except Exception:
        return ""


# 版本号智能提示
def _build_version_hint(existing_name: str, new_name: str) -> str:
    """基于文件名中的 vN 版本号，生成智能建议（避免误匹配 conv2 等词）"""
    old_ver = re.search(r'(?<![A-Za-z])[vV](\d+)', existing_name)
    new_ver = re.search(r'(?<![A-Za-z])[vV](\d+)', new_name)
    if not (old_ver and new_ver):
        return ""
    ov, nv = int(old_ver.group(1)), int(new_ver.group(1))
    if ov > nv:
        return f"库中已有较新版本 v{ov}，当前 v{nv} 较旧，建议保留 v{ov}"
    if ov < nv:
        return f"当前 v{nv} 比库中 v{ov} 更新，建议覆盖旧版"
    return f"两版版本号相同（v{ov}），建议对比后决定"


# ==========================================
# 模块一：PDF 解析与入库
# ==========================================
def _parse_pdf_bytes(contents: bytes, filename: str):
    doc = fitz.open(stream=contents, filetype="pdf")
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CONFIG["chunk_size"],
        chunk_overlap=CONFIG["chunk_overlap"],
        length_function=len,
    )
    all_chunks, all_metadatas, all_ids, full_text = [], [], [], ""
    total_pages = len(doc)
    log_iv = CONFIG["parse_log_interval"]
    print(f"📖 解析 [{filename}] 共 {total_pages} 页...")

    for page_num, page in enumerate(doc, start=1):
        if (log_iv > 0 and page_num % log_iv == 0) or page_num == 1:
            print(f"⏳ 第 {page_num}/{total_pages} 页，{len(all_chunks)} 块")

        page_text = page.get_text()

        if not page_text.strip():
            print(f"📄 第 {page_num} 页为扫描件，启动 OCR...")
            pix = page.get_pixmap(dpi=CONFIG["ocr_dpi"])
            img_bytes = pix.tobytes("png")
            try:
                result, _ = ocr_engine(img_bytes)
                if result:
                    page_text = "\n".join([line[1] for line in result])
            except Exception as e:
                print(f"⚠️ 本地 OCR 失败: {e}")

            if not page_text.strip():
                b64 = base64.b64encode(img_bytes).decode("utf-8")
                try:
                    resp = client.chat.completions.create(
                        model=CONFIG["llm_model"],
                        messages=[{"role": "user", "content": [
                            {"type": "text", "text": CONFIG["vision_ocr_prompt"]},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                        ]}],
                        temperature=CONFIG["llm_temperature"],
                        timeout=CONFIG["llm_timeout"] + 30,
                    )
                    page_text = resp.choices[0].message.content
                except Exception as e:
                    print(f"Vision OCR 失败: {e}")
                    page_text = CONFIG["fallback_ocr_failed"].format(page=page_num)

        if not page_text.strip():
            continue

        dot_count = page_text.count(CONFIG["toc_dot_char"])
        if (dot_count > CONFIG["toc_dot_threshold"]
                and len(page_text.split("\n")) > CONFIG["toc_line_threshold"]):
            print(f"⏭️ 第 {page_num} 页疑似目录，跳过")
            continue

        # 把页标签注入 full_text（供前端 [Page X] 跳转与 TOC 定位）
        page_label = format_page_label(page_num)
        full_text += f"{page_label}：{page_text}\n"
        chunks = text_splitter.split_text(page_text)
        for i, chunk in enumerate(chunks):
            all_chunks.append(f"{page_label}：{chunk}")
            all_metadatas.append({"page": page_num, "source": filename})
            all_ids.append(format_chunk_id(filename, page_num, i))

    print(f"✅ [{filename}] 解析完成，{len(all_chunks)} 块")
    return all_chunks, all_metadatas, all_ids, full_text


def extract_title_and_refs(text: str) -> dict:
    text = re.sub(r'《第 \d+ 页》：', '', text)
    head = text[:CONFIG["meta_head_chars"]]
    ref_start = re.search(CONFIG["references_section_pattern"], text)
    if ref_start:
        ref_text = text[ref_start.start():ref_start.start() + CONFIG["meta_ref_chars"]]
    else:
        ref_text = text[-CONFIG["meta_ref_chars"]:]

    rmin, rmax = CONFIG["meta_refs_min"], CONFIG["meta_refs_max"]
    prompt = f"""你是学术文献解析器。返回严格 JSON：
{{"paper_title": "完整标题", "refs": ["作者 (年份) 标题核心词", "..."]}}
refs 提取 {rmin}-{rmax} 篇核心参考文献，格式如 "Vaswani (2017) Attention"。无法提取返回空数组。
只输出 JSON，无任何解释。

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
    print(f"⏳ 后台提取 [{filename}] 元数据...")
    meta = extract_title_and_refs(full_text)
    real_refs = meta["refs"]
    ref_id = f"{filename}{CONFIG['references_block_id_suffix']}"
    empty_doc = CONFIG["fallback_no_refs_found"]
    try:
        collection.add(
            documents=["-".join(real_refs) if real_refs else empty_doc],
            metadatas=[{
                "page": CONFIG["reference_page_sentinel"],
                "source": filename,
                "type": CONFIG["references_meta_type"],
                CONFIG["references_meta_refs_key"]: json.dumps(real_refs),
                CONFIG["references_meta_title_key"]: meta["paper_title"],
            }],
            ids=[ref_id],
        )
        print(f"✅ [{filename}] 参考文献 {len(real_refs)} 条")
    except Exception as e:
        print(f"❌ 后台写入失败: {e}")


def _ingest_pdf(contents: bytes, filename: str, background_tasks: BackgroundTasks):
    all_chunks, all_metadatas, all_ids, full_text = _parse_pdf_bytes(contents, filename)
    toc = _extract_pdf_toc(contents)

    if all_chunks:
        print("🧹 清理旧数据...")
        try:
            collection.delete(where={"source": filename})
        except Exception:
            pass
        batch_size = CONFIG["ingest_batch_size"]
        for i in range(0, len(all_chunks), batch_size):
            collection.add(
                documents=all_chunks[i:i + batch_size],
                metadatas=all_metadatas[i:i + batch_size],
                ids=all_ids[i:i + batch_size],
            )

    background_tasks.add_task(process_meta_task, filename, full_text)

    registry = _load_registry()
    registry[filename] = {
        "preview": full_text[:CONFIG["dedup_preview_chars"]],
        "chunks": len(all_chunks),
        "upload_time": datetime.now().isoformat(),
        "toc": toc,
    }
    _save_registry(registry)
    return all_chunks, full_text, toc


# ==========================================
# 文件接口
# ==========================================
@app.post("/upload")
def upload_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    force: bool = Form(False),
):
    """单文件上传（保留原有行为，前端循环调用可处理批量）"""
    try:
        contents = file.file.read()

        if not force:
            preview = _preview_pdf_text(contents)
            if preview.strip():
                registry = _load_registry()
                for existing_name, info in registry.items():
                    if existing_name == file.filename:
                        continue
                    old_preview = info.get("preview", "")
                    if not old_preview:
                        continue
                    sim = difflib.SequenceMatcher(None, preview, old_preview).ratio() * 100
                    if sim >= CONFIG["dedup_threshold"]:
                        return {
                            "status": "duplicate",
                            "similarity": round(sim, 1),
                            "existing": existing_name,
                            "version_hint": _build_version_hint(existing_name, file.filename),
                            "message": f"检测到与《{existing_name}》相似度 {sim:.1f}%，是否覆盖？",
                        }

        all_chunks, full_text, toc = _ingest_pdf(contents, file.filename, background_tasks)
        html_text = wrap_citation_anchors(full_text)
        return {
            "status": "success",
            "message": f"成功解析 {len(all_chunks)} 个文本块！(参考文献后台提取中)",
            "text": html_text,
            "toc": toc,
        }
    except Exception as e:
        print(f"❌ 上传失败: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/upload_batch")
def upload_pdf_batch(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    force: bool = Form(False),
):
    """
    批量上传 PDF（支持 1~N 篇）
    - 批内去重：与本批已入库文件比对
    - 库内去重：与 registry 已有文献比对
    - 返回汇总结果（success 结果里包含完整 text，供前端直接阅读）
    """
    results = []
    uploaded_in_batch: List[tuple] = []

    for file in files:
        try:
            contents = file.file.read()

            duplicate_found = False
            if not force:
                preview = _preview_pdf_text(contents)

                if preview.strip():
                    # 1) 与已有库比对
                    registry = _load_registry()
                    for existing_name, info in registry.items():
                        if existing_name == file.filename:
                            continue
                        old_preview = info.get("preview", "")
                        if not old_preview:
                            continue
                        sim = difflib.SequenceMatcher(None, preview, old_preview).ratio() * 100
                        if sim >= CONFIG["dedup_threshold"]:
                            results.append({
                                "filename": file.filename,
                                "status": "duplicate",
                                "similarity": round(sim, 1),
                                "existing": existing_name,
                                "version_hint": _build_version_hint(existing_name, file.filename),
                                "message": f"与库中《{existing_name}》相似度 {sim:.1f}%",
                            })
                            duplicate_found = True
                            break

                    # 2) 与本批已入库比对
                    if not duplicate_found:
                        for prev_name, prev_preview in uploaded_in_batch:
                            if prev_name == file.filename:
                                continue
                            sim = difflib.SequenceMatcher(None, preview, prev_preview).ratio() * 100
                            if sim >= CONFIG["dedup_threshold"]:
                                results.append({
                                    "filename": file.filename,
                                    "status": "duplicate",
                                    "similarity": round(sim, 1),
                                    "existing": prev_name,
                                    "version_hint": _build_version_hint(prev_name, file.filename),
                                    "message": f"与本批《{prev_name}》相似度 {sim:.1f}%",
                                })
                                duplicate_found = True
                                break

            if duplicate_found:
                continue

            all_chunks, full_text, toc = _ingest_pdf(contents, file.filename, background_tasks)
            uploaded_in_batch.append((file.filename, full_text[:CONFIG["dedup_preview_chars"]]))
            results.append({
                "filename": file.filename,
                "status": "success",
                "chunks": len(all_chunks),
                "toc": toc,
                "text": wrap_citation_anchors(full_text),
            })
        except Exception as e:
            results.append({
                "filename": file.filename,
                "status": "error",
                "message": str(e),
            })

    success_count = sum(1 for r in results if r["status"] == "success")
    duplicate_count = sum(1 for r in results if r["status"] == "duplicate")
    error_count = sum(1 for r in results if r["status"] == "error")

    return {
        "status": "success" if success_count > 0 else "all_failed",
        "total": len(files),
        "success_count": success_count,
        "duplicate_count": duplicate_count,
        "error_count": error_count,
        "results": results,
    }


@app.post("/list_docs")
def list_docs():
    registry = _load_registry()
    docs = [
        {"name": name, "chunks": info.get("chunks", 0),
         "upload_time": info.get("upload_time", ""), "toc": info.get("toc", [])}
        for name, info in registry.items()
    ]
    docs.sort(key=lambda x: x.get("upload_time", ""), reverse=True)
    return {"status": "success", "docs": docs}


@app.post("/delete_doc")
async def delete_doc(filename: str = Form(...)):
    try:
        collection.delete(where={"source": filename})
        registry = _load_registry()
        if filename in registry:
            registry.pop(filename)
            _save_registry(registry)
        return {"status": "success", "message": f"已删除 {filename}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/parse_only")
def parse_only(file: UploadFile = File(...)):
    try:
        contents = file.file.read()
        _, _, _, full_text = _parse_pdf_bytes(contents, file.filename)
        return {"status": "success", "text": wrap_citation_anchors(full_text)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ==========================================
# 模块二：RAG 问答
# ==========================================
class ChatRequest(BaseModel):
    message: str
    doc_filter: str = ""
    doc_filters: List[str] = []


@app.post("/chat")
async def chat_endpoint(req: ChatRequest):
    try:
        target_docs: List[str] = req.doc_filters or (
            [req.doc_filter] if req.doc_filter else []
        )

        search_queries = [req.message]
        if re.search('[\u4e00-\u9fa5]', req.message):
            try:
                trans_prompt = CONFIG["trans_expand_prompt_template"].format(
                    n=CONFIG["trans_keywords_count"], message=req.message
                )
                ans_text = call_llm(trans_prompt).choices[0].message.content
                for line in ans_text.split('\n'):
                    if "翻译：" in line:
                        search_queries.append(line.replace("翻译：", "").strip())
                    elif "关键词：" in line:
                        search_queries.append(line.replace("关键词：", "").strip())
            except Exception as e:
                print("翻译扩展失败:", e)

        query_kwargs = {"query_texts": search_queries, "n_results": CONFIG["rag_top_k"]}
        if len(target_docs) == 1:
            query_kwargs["where"] = {"source": target_docs[0]}
        elif len(target_docs) > 1:
            query_kwargs["where"] = {"source": {"$in": target_docs}}
        results = collection.query(**query_kwargs)

        context = ""
        top_page = None
        if results and results['documents'] and results['documents'][0]:
            seen_docs = set()
            for i, doc in enumerate(results['documents'][0]):
                meta = results['metadatas'][0][i]
                page = meta.get('page')
                if is_reference_page(page) or is_reference_type(meta):
                    continue
                if doc in seen_docs:
                    continue
                seen_docs.add(doc)
                source = meta.get('source', CONFIG["fallback_unknown_source"])
                context += format_rag_context(source, page, doc) + "\n\n"
                if top_page is None:
                    top_page = page

        if target_docs:
            try:
                min_len = CONFIG["rag_min_token_len"]
                token_pattern = rf'[a-zA-Z]{{{min_len},}}|\d+\.\d+|β\d?|α\d?|γ\d?'
                dynamic_tokens = re.findall(token_pattern, req.message)
                if dynamic_tokens:
                    token_max = CONFIG["rag_tokens_max"]
                    dynamic_tokens = list(set([t.lower() for t in dynamic_tokens]))[:token_max]
                    hard_match_docs = []
                    where_clause = (
                        {"source": target_docs[0]} if len(target_docs) == 1
                        else {"source": {"$in": target_docs}}
                    )
                    for token in dynamic_tokens:
                        if len(token) < min_len and token.isalpha():
                            continue
                        match_res = collection.get(
                            where=where_clause,
                            where_document={"$contains": token},
                            limit=CONFIG["rag_sparse_top_k"],
                        )
                        if match_res and match_res['documents']:
                            for d, m in zip(match_res['documents'], match_res['metadatas']):
                                if not is_reference_type(m) and d not in context and d not in hard_match_docs:
                                    hard_match_docs.append(
                                        format_rag_context(
                                            m.get('source', CONFIG["fallback_unknown_source"]),
                                            m.get('page'), d, sparse=True,
                                        )
                                    )
                                    if top_page is None:
                                        top_page = m.get('page')
                    if hard_match_docs:
                        print(f"✅ 稀疏检索命中 {len(hard_match_docs)} 块")
                        context = "\n\n".join(hard_match_docs[:CONFIG["rag_sparse_top_k"]]) + "\n\n" + context
            except Exception as e:
                print("稀疏检索失败:", e)

        multi_hint = ""
        if len(target_docs) > 1:
            multi_hint = (
                f"\n【多文献对比模式】用户同时选中了 {len(target_docs)} 篇文献：{', '.join(target_docs)}。\n"
                "🚨【强制格式要求】：在回答对比类问题时，必须分条作答，并明确指出该信息属于哪一篇文献。\n"
                "格式示例：\n"
                "1. 在《文献A》中，使用了... [Page 3]\n"
                "2. 在《文献B》中，使用了... [Page 5]\n"
                "你必须尽可能同时给出两篇文献各自的页码锚点。"
            )

        ctx_example = format_rag_context("xxx.pdf", "12", "正文内容...")
        page_example = format_page_marker("X")
        system_prompt = f"""你是 PaperPilot 科研助手。你的任务是阅读学术文献并回答用户问题。
{multi_hint}
【格式硬性要求（最高优先级）】：
1. 所有回答必须在句末附带来源物理页码，格式严格为：`{page_example}`（X 为纯数字）。
2. 🚨【多文献页码规则】：如果是多文献对比模式，请使用类似 "《文献名A》指出... [Page X]，《文献名B》指出... [Page Y]" 的格式，分别给出各篇文献的页码。
3. 🚨【页码来源铁律】：系统的真实页码已以如下格式标注在参考内容开头：`{ctx_example}`。正文中出现的所有其它纯数字（页眉、页脚、印刷数字）统统是干扰项！
4. 🚨【禁止跨页合并】：你必须严格核对「提取出的答案」是否真的出现在该「[Page X]」对应的文本块中。如果答案由多个块拼凑而成，请选择最核心答案所在的块并标注对应的页码。若实在无法确定确切页码，请直接回答"未在文献中找到相关数据"，严禁推测页码。
5. 🚨【页码输出限制】：无论参考内容中有多少个页码，你**最多只能输出 2 个最核心的 `[Page X]`**。绝对禁止像报菜名一样罗列多个页码！如果回答中实在找不到答案，直接说"未在文献中找到"，不要附带任何页码。

【内容最高指令】：
1. 只基于参考内容回答，严禁使用通用世界知识。
2. 若问题与科研完全无关，回答："抱歉，我是科研助手，只能回答与学术文献相关的问题。"（🚨不要附页码）
3. 若参考内容确实未提及，回答"未在文献中找到相关数据。"（🚨不要附页码）
4. 若用户问"这篇文献讲了什么"，提炼核心贡献并附页码。
5. 🚨 无论用户使用何种语言，统一用中文（简体）输出，学术专有名词可保留英文。

【参考内容】：
{context if context else CONFIG["fallback_no_context"]}
"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": req.message},
        ]

        def generate():
            full_text = ""
            try:
                response = call_llm_stream(messages)
                for chunk in response:
                    if chunk.choices[0].delta.content:
                        text = chunk.choices[0].delta.content
                        full_text += text
                        yield f"data: {text}\n\n"

                if top_page is not None and CONFIG["page_marker_probe"] not in full_text:
                    refusal_keywords = CONFIG["rag_refusal_keywords"]
                    if not any(kw in full_text for kw in refusal_keywords):
                        yield f"data: {format_page_marker(top_page)}\n\n"
            except Exception as e:
                yield f"data: [Error] 网络失败: {str(e)}\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")
    except Exception as e:
        return {"error": str(e)}


class CompareReq(BaseModel):
    doc_names: List[str]
    aspect: str = ""


@app.post("/compare")
async def compare_docs(req: CompareReq):
    aspect = req.aspect.strip() or CONFIG["compare_default_aspect"]
    if len(req.doc_names) < CONFIG["compare_min_docs"]:
        return {"error": f"至少选择 {CONFIG['compare_min_docs']} 篇文献"}
    if len(req.doc_names) > CONFIG["compare_max_docs"]:
        return {"error": f"单次最多对比 {CONFIG['compare_max_docs']} 篇"}

    contexts = []
    per_doc = CONFIG["compare_per_doc_chunks"]
    for doc in req.doc_names:
        try:
            res = collection.query(query_texts=[aspect], n_results=per_doc, where={"source": doc})
            chunks = []
            if res and res.get("documents") and res["documents"][0]:
                for d, m in zip(res["documents"][0], res["metadatas"][0]):
                    if is_reference_type(m):
                        continue
                    chunks.append(f"[{doc} | Page {m.get('page')}] {d}")
            if chunks:
                contexts.append(f"=== 文献《{doc}》===\n" + "\n\n".join(chunks))
        except Exception as e:
            print(f"对比检索 {doc} 失败: {e}")

    if not contexts:
        return {"error": "未从所选文献中检索到相关内容"}

    prompt = f"""你是学术对比专家。请基于以下真实文献片段，对 {', '.join(req.doc_names)} 进行结构化对比。

要求：
1. 使用 Markdown 表格对比核心维度（架构 / 贡献 / 参数 / 数据集 / 指标）。
2. 指出论文之间的承袭与差异关系。
3. 每处结论必须标注页码或来源文件名。
4. 中文输出，专有名词保留英文。

【文献片段】：
{chr(10).join(contexts)}"""

    try:
        res = call_llm(prompt)
        return {"compare": res.choices[0].message.content, "docs": req.doc_names}
    except Exception as e:
        return {"error": str(e)}


# ==========================================
# 模块一：去重与差异
# ==========================================
@app.post("/dedup")
async def check_dedup(text1: str = Form(...), text2: str = Form(...)):
    try:
        cap = CONFIG["dedup_compare_chars"]
        matcher = difflib.SequenceMatcher(None, text1[:cap], text2[:cap])
        similarity_score = round(matcher.ratio() * 100, 1)
        is_duplicate = similarity_score >= CONFIG["dedup_threshold"]
        prompt_cap = CONFIG["dedup_prompt_chars"]

        prompt = f"""你是学术查重引擎。系统底层算法已确定两段文本相似度为 {similarity_score}%。
请对比这两段文本，指出具体细微差异，并给用户提出处理建议。
🚨 无论原文语言，必须严格使用中文（简体）输出，学术专有名词可保留英文。

返回严格 JSON：
{{"message": "一段话描述差异和建议"}}

文本1片段：
{text1[:prompt_cap]}

文本2片段：
{text2[:prompt_cap]}"""

        try:
            res = call_llm(prompt, is_json=True)
            data = json.loads(res.choices[0].message.content)
            message = data.get("message", "文本高度相似，建议保留最新版本。")
        except Exception as e:
            print("大模型分析差异失败:", e)
            message = "文本高度相似，建议检查引用的准确性和完整性。"

        return {"similarity": similarity_score, "is_duplicate": is_duplicate, "message": message}
    except Exception as e:
        return {"similarity": 0, "is_duplicate": False, "message": f"比对失败: {str(e)}"}


@app.post("/diff")
async def compare_diff(text_old: str = Form(...), text_new: str = Form(...)):
    try:
        cap = CONFIG["diff_prompt_chars"]
        n = CONFIG["diff_summary_sentences"]
        prompt = (
            f"你是一个学术审稿人。请用 {n} 句话总结【新版】相较于【旧版】的主要修订差异。\n"
            f"旧版片段：\n{text_old[:cap]}\n\n新版片段：\n{text_new[:cap]}"
        )
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
            prompt = f"【翻译规则】1.保持术语英文原文。2.公式、引用编号保留。3.保留换行。4.只输出纯中文译文。\n待翻译：\n{req.text}"
        elif req.action == "rewrite":
            prompt = f"【重写规则】1.用严谨学术英语重写。2.保持原意不捏造。3.去冗余。4.只输出纯英文。\n待重写：\n{req.text}"
        elif req.action == "academic_en":
            prompt = f"【学术中译英规则】1.使用地道严谨学术英语。2.术语采用国际通用表达。3.公式、引用编号保留。4.保持原意不增删。5.只输出纯英文译文。\n待翻译：\n{req.text}"
        else:
            return {"error": "未知操作"}

        response = call_llm(prompt)
        result = response.choices[0].message.content.replace("<text>", "").replace("</text>", "").strip()
        return {"result": result}
    except Exception as e:
        return {"error": str(e)}


# ==========================================
# 模块四：arXiv
# ==========================================
class ArxivReq(BaseModel):
    query: str = ""
    category: str = ""
    max_results: int = 10


def _looks_like_arxiv_category(s: str) -> bool:
    if not s or not isinstance(s, str):
        return False
    return bool(re.match(r'^[a-z\-]+(\.[A-Za-z]{2,})*$', s.strip()))


def _extract_github_url(text: str) -> str:
    if not text:
        return ""
    m = re.findall(r'https?://github\.com/[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+', text)
    return m[0].rstrip('.,;') if m else ""


def _load_mock_arxiv() -> list:
    path = CONFIG["mock_arxiv_path"]
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"⚠️ 读取 mock 失败: {e}")
        return []


@retry(wait=wait_fixed(2), stop=stop_after_attempt(2))
def _fetch_arxiv_live(query: str, category: str, max_results: int) -> list:
    if _looks_like_arxiv_category(query) and not category:
        category = query
        query = ""
    parts = []
    if query:
        parts.append(f"all:{query}")
    if category:
        parts.append(f"cat:{category}")
    search_q = "+AND+".join(parts) if parts else f"cat:{CONFIG['arxiv_default_category']}"

    url = (
        "http://export.arxiv.org/api/query"
        f"?search_query={search_q}&start=0&max_results={max_results}"
        f"&sortBy={CONFIG['arxiv_sort_by']}&sortOrder={CONFIG['arxiv_sort_order']}"
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    resp = requests.get(url, headers=headers, timeout=CONFIG["arxiv_timeout"])
    if resp.status_code != 200:
        raise Exception(f"arXiv HTTP {resp.status_code}")

    root = ET.fromstring(resp.content)
    ns = {"atom": "http://www.w3.org/2005/Atom",
          "arxiv": "http://arxiv.org/schemas/atom"}
    entries = root.findall("atom:entry", ns)

    results = []
    amax = CONFIG["arxiv_authors_max"]
    for entry in entries:
        title_el = entry.find("atom:title", ns)
        summary_el = entry.find("atom:summary", ns)
        published_el = entry.find("atom:published", ns)
        id_el = entry.find("atom:id", ns)
        comment_el = entry.find("arxiv:comment", ns)
        authors = [a.find("atom:name", ns).text for a in entry.findall("atom:author", ns)
                   if a.find("atom:name", ns) is not None]

        title = (title_el.text or "").strip().replace("\n", " ") if title_el is not None else ""
        summary = (summary_el.text or "").strip().replace("\n", " ") if summary_el is not None else ""
        published = (published_el.text or "")[:10] if published_el is not None else ""
        arxiv_url = (id_el.text or "").strip() if id_el is not None else ""
        comment = (comment_el.text or "").strip() if comment_el is not None else ""
        github_url = _extract_github_url(comment) or _extract_github_url(summary)

        authors_short = ", ".join(authors[:amax]) + (
            CONFIG["arxiv_authors_etc_suffix"] if len(authors) > amax else ""
        )
        results.append({
            "title": title, "authors": authors_short, "published": published,
            "summary": summary, "arxiv_url": arxiv_url,
            "github_url": github_url, "source": "arxiv_live",
        })
    return results


def _compute_local_relevance(paper_title: str, paper_summary: str) -> tuple:
    try:
        cap = CONFIG["relevance_summary_chars"]
        query_text = f"{paper_title} {paper_summary[:cap]}".strip()
        if not query_text or collection.count() == 0:
            return 0.0, ""
        results = collection.query(query_texts=[query_text], n_results=1)
        if (results and results.get("distances") and results["distances"][0]
                and results["distances"][0][0] is not None):
            dist = float(results["distances"][0][0])
            score = round(100.0 / (CONFIG["relevance_smoothing"] + max(dist, 0.0)), 1)
            top_source = ""
            if results.get("metadatas") and results["metadatas"][0]:
                top_source = results["metadatas"][0][0].get("source", "")
            return score, top_source
    except Exception as e:
        print(f"⚠️ 相关性计算失败: {e}")
    return 0.0, ""


def _generate_recommend_reason(paper: dict, local_score: float, top_source: str) -> str:
    reasons = []
    gh = paper.get("github_url", "")
    if gh:
        repo = gh.split("github.com/")[-1].strip("/")
        reasons.append(f"✅ 附带开源代码 {repo}，复现性强")
    if local_score >= CONFIG["relevance_high"]:
        reasons.append(f"🔥 与本地《{top_source}》高度相关（{local_score}分）")
    elif local_score >= CONFIG["relevance_medium"]:
        reasons.append(f"📎 与本地文献有一定关联（{local_score}分）")
    pub = paper.get("published", "")
    if pub and pub >= recent_cutoff_date():
        reasons.append("🆕 近期新作")
    if not reasons:
        reasons.append("📄 匹配检索关键词")
    return " · ".join(reasons)


@app.post("/arxiv_search")
async def arxiv_search(req: ArxivReq):
    query = (req.query or "").strip()
    category = (req.category or "").strip()
    if category and not _looks_like_arxiv_category(category):
        category = CONFIG["arxiv_default_category"]
    if not category:
        category = CONFIG["arxiv_default_category"]

    cap = CONFIG["arxiv_max_results_cap"]
    max_results = max(1, min(int(req.max_results or CONFIG["arxiv_max_results"]), cap))

    raw_results, offline = [], False
    try:
        raw_results = _fetch_arxiv_live(query, category, max_results)
        if not raw_results:
            raise Exception("空结果")
        print(f"✅ arXiv 实时 {len(raw_results)} 篇")
    except Exception as e:
        print(f"🌐 arXiv 失败，离线兜底: {e}")
        offline = True
        raw_results = _load_mock_arxiv()

    if not raw_results:
        return {"status": "error", "message": "arXiv 与本地 mock 均无数据", "data": []}

    enriched = []
    for p in raw_results:
        score, top_src = _compute_local_relevance(p.get("title", ""), p.get("summary", ""))
        p["local_relevance"] = score
        p["top_local_source"] = top_src
        p["recommend_reason"] = _generate_recommend_reason(p, score, top_src)
        enriched.append(p)

    enriched.sort(key=lambda x: (1 if x.get("github_url") else 0, x.get("local_relevance", 0)), reverse=True)
    return {"status": "success", "offline": offline, "count": len(enriched), "data": enriched}


class FeedbackReq(BaseModel):
    arxiv_url: str = ""
    title: str = ""
    action: str


def _load_feedback() -> dict:
    path = CONFIG["user_feedback_path"]
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_feedback(data: dict):
    try:
        with open(CONFIG["user_feedback_path"], "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ 保存反馈失败: {e}")


@app.post("/arxiv_feedback")
async def arxiv_feedback(req: FeedbackReq):
    if req.action not in ("like", "dislike"):
        return {"error": "action 必须为 like 或 dislike"}
    key = (req.arxiv_url or req.title or "").strip()
    if not key:
        return {"error": "arxiv_url 与 title 不能同时为空"}
    data = _load_feedback()
    record = data.get(key, {"like": 0, "dislike": 0, "title": req.title})
    record[req.action] = int(record.get(req.action, 0)) + 1
    record["title"] = req.title or record.get("title", "")
    data[key] = record
    _save_feedback(data)
    return {"status": "success", "record": record}


@app.post("/arxiv_download")
def arxiv_download(background_tasks: BackgroundTasks, arxiv_url: str = Form(...)):
    try:
        arxiv_url = (arxiv_url or "").strip()
        if not arxiv_url or "arxiv.org" not in arxiv_url:
            return {"error": "无效的 arXiv 链接"}

        pdf_url = arxiv_url.replace("/abs/", "/pdf/").replace("http://", "https://")
        if not pdf_url.endswith(".pdf"):
            pdf_url += ".pdf"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/pdf,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        resp = None
        for attempt in range(3):
            try:
                resp = requests.get(pdf_url, headers=headers, timeout=90, stream=True, verify=False)
                if resp.status_code == 200:
                    break
            except requests.exceptions.RequestException as e:
                print(f"下载尝试 {attempt+1} 失败: {e}")
                if attempt == 2:
                    return {"error": f"网络异常，下载失败: {str(e)}"}
                time.sleep(2)

        if not resp or resp.status_code != 200:
            return {"error": f"PDF 下载失败，HTTP {resp.status_code if resp else 'Timeout'}"}

        MAX_BYTES = CONFIG["pdf_max_bytes"]
        buf = bytearray()
        for chunk in resp.iter_content(chunk_size=8192):
            if not chunk:
                continue
            buf.extend(chunk)
            if len(buf) > MAX_BYTES:
                return {"error": f"PDF 超过 {MAX_BYTES // (1024*1024)}MB，已拒绝下载"}

        contents = bytes(buf)
        arxiv_id = arxiv_url.rstrip("/").split("/")[-1] or CONFIG["fallback_arxiv_id"]
        safe_id = re.sub(r'[^A-Za-z0-9._\-]', '_', arxiv_id)
        filename = f"{safe_id}.pdf"

        all_chunks, full_text, toc = _ingest_pdf(contents, filename, background_tasks)
        if not all_chunks:
            return {"error": "PDF 解析后无有效文本"}

        return {"status": "success", "filename": filename,
                "message": f"已下载并入库 {len(all_chunks)} 个文本块", "toc": toc}
    except Exception as e:
        print(f"❌ arXiv 下载失败: {e}")
        return {"error": f"下载入库失败: {str(e)}"}


# ==========================================
# 模块五：图谱 / 综述 / 未来方向
# ==========================================
class GraphRequest(BaseModel):
    doc_filter: str = ""
    doc_filters: List[str] = []


def _get_doc_refs(doc_name: str) -> List[str]:
    try:
        ref_res = collection.get(where={"source": doc_name})
        if ref_res and ref_res.get("metadatas"):
            refs_key = CONFIG["references_meta_refs_key"]
            for meta in ref_res["metadatas"]:
                if is_reference_type(meta) and refs_key in meta:
                    loaded = json.loads(meta.get(refs_key) or "[]")
                    if isinstance(loaded, list):
                        return [r for r in loaded if isinstance(r, str)]
    except Exception as e:
        print(f"读取 {doc_name} refs 失败: {e}")
    return []


@app.post("/graph")
async def get_citation_graph(req: GraphRequest):
    try:
        target_docs: List[str] = req.doc_filters or (
            [req.doc_filter] if req.doc_filter else []
        )
        if not target_docs:
            return {"nodes": [], "links": [], "message": "请先选择文献"}

        G = nx.DiGraph()
        for d in target_docs:
            G.add_node(d)

        total_refs = 0
        for d in target_docs:
            refs = _get_doc_refs(d)
            total_refs += len(refs)
            for ref in refs:
                clean = clean_ref_name(ref)
                if clean:
                    G.add_edge(d, clean)

        if total_refs == 0:
            local_sz = CONFIG["graph_node_local_size"]
            nodes = [
                {"name": d, "value": 1.0, "symbolSize": local_sz, "role": "user_paper", "is_local": True}
                for d in target_docs
            ]
            return {"nodes": nodes, "links": [],
                    "message": "未从所选文献解析到参考文献（不伪造引用）",
                    "summary": {"total_papers": len(target_docs), "total_refs": 0, "pillar_count": 0}}

        try:
            pagerank = nx.pagerank(G)
        except Exception:
            fb = CONFIG["graph_fallback_pr"]
            pagerank = {n: fb / max(len(G.nodes()), 1) for n in G.nodes()}

        scores = list(pagerank.values())
        avg = sum(scores) / len(scores) if scores else 0
        max_score = max(scores) if scores else 1
        pillar_threshold = avg * CONFIG["pillar_ratio"]
        base_sz = CONFIG["graph_node_base_size"]
        range_sz = CONFIG["graph_node_size_range"]
        fb_sz = CONFIG["graph_node_fallback_size"]
        scale = CONFIG["pagerank_scale"]

        nodes = []
        for n in G.nodes():
            score = pagerank[n]
            if n in target_docs:
                role = "user_paper"
            elif score > pillar_threshold:
                role = "pillar"
            else:
                role = "edge"
            nodes.append({
                "name": n,
                "value": round(score * scale, 2),
                "symbolSize": base_sz + (score / max_score) * range_sz if max_score > 0 else fb_sz,
                "role": role,
                "is_local": n in target_docs,
            })

        links = [{"source": s, "target": t} for s, t in G.edges()]
        pillar_count = sum(1 for n in nodes if n["role"] == "pillar")
        return {"nodes": nodes, "links": links, "message": "ok",
                "summary": {"total_papers": len(target_docs), "total_refs": total_refs, "pillar_count": pillar_count}}
    except Exception as e:
        print(f"❌ 图谱失败: {e}")
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
            prefix = CONFIG["review_macro_label_prefix"]
            macro_limit = CONFIG["review_macro_chunks"]
            macro_context_parts = [doc for _, doc in sorted_chunks[:macro_limit] if prefix in doc]

        search_results = collection.query(
            query_texts=CONFIG["review_queries"],
            n_results=CONFIG["review_local_chunks"], where={"source": req.topic},
        )
        local_context_parts = []
        if search_results and search_results['documents'] and search_results['documents'][0]:
            for doc, meta in zip(search_results['documents'][0], search_results['metadatas'][0]):
                if not is_reference_page(meta.get('page')) and not is_reference_type(meta) and doc not in local_context_parts:
                    local_context_parts.append(doc)

        context = "\n\n".join(macro_context_parts + local_context_parts)
        prompt = f"""你是顶尖学术综述专家。请针对「{req.topic}」这一方向，严格根据以下【论文真实内容】生成一段精炼的学术综述。

要求：
1. 第一段：总结核心架构及其演进意义。
2. 第二段：指出论文中的"基石算法"或机制的真实贡献。
3. 第三段：基于论文内容展望未来方向（Future Work）。
4. 🚨 必须使用中文（简体）输出！

【论文真实内容】：
{context if context else CONFIG["fallback_no_detail"]}"""

        response = call_llm(prompt)
        return {"review": response.choices[0].message.content}
    except Exception as e:
        return {"error": str(e)}


class FutureWorkReq(BaseModel):
    doc_filter: str = ""
    doc_filters: List[str] = []


@app.post("/future_work")
async def extract_future_work(req: FutureWorkReq):
    target_docs: List[str] = req.doc_filters or (
        [req.doc_filter] if req.doc_filter else []
    )
    if not target_docs:
        return {"error": "请先选择文献"}

    all_fw = []
    max_docs = CONFIG["future_work_max_docs"]
    per_doc = CONFIG["future_work_chunks_per_doc"]
    for doc in target_docs[:max_docs]:
        try:
            res = collection.query(
                query_texts=[CONFIG["future_work_query"]],
                n_results=per_doc, where={"source": doc},
            )
            chunks = []
            if res and res.get("documents") and res["documents"][0]:
                for d, m in zip(res["documents"][0], res["metadatas"][0]):
                    if is_reference_type(m):
                        continue
                    chunks.append(f"[{doc} | Page {m.get('page')}] {d}")
            if chunks:
                all_fw.append(f"=== 文献《{doc}》===\n" + "\n\n".join(chunks))
        except Exception as e:
            print(f"提取 {doc} 失败: {e}")

    if not all_fw:
        return {"error": "未能提取到 Future Work 相关内容"}

    prompt = f"""你是学术洞察专家。请完成：

1. 从以下文献中提取所有明确提出的「Future Work / Future Direction / Limitations」条目。
2. 基于你自身的知识，判断每条 idea 是否已被近年后续研究解决。
3. 只输出「尚未被解决」且有真正探索价值的未来方向；已被解决的旧 idea 直接舍弃。

输出格式：
- **[来源文献] 方向标题** — 说明（若无法判断就标"待考证"）
- 中文输出，术语保留英文。

【文献片段】：
{chr(10).join(all_fw)}"""

    try:
        res = call_llm(prompt)
        return {"future_work": res.choices[0].message.content, "docs": target_docs}
    except Exception as e:
        return {"error": str(e)}


# ==========================================
# 模块六：CSV / 框架
# ==========================================
class CSVRequest(BaseModel):
    csv_text: str
    chart_type: str = "auto"


def dataframe_to_markdown(df: pd.DataFrame, max_rows: int) -> str:
    d = df.head(max_rows).copy()
    cols = [str(c) for c in d.columns]
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
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
        if len(req.csv_text.encode("utf-8")) > CONFIG["csv_max_bytes"]:
            return {"error": f"CSV 文件过大，请控制在 {CONFIG['csv_max_bytes'] // 1024 // 1024}MB 以内"}

        df = pd.read_csv(io.StringIO(req.csv_text))
        df = df.dropna(how="all").dropna(axis=1, how="all")
        if df.empty:
            return {"error": "CSV 解析后为空"}
        if len(df.columns) > CONFIG["csv_max_columns"]:
            return {"error": f"列数过多，请控制在 {CONFIG['csv_max_columns']} 列以内"}
        if len(df) > CONFIG["csv_max_rows"]:
            df = df.head(CONFIG["csv_max_rows"])

        df.columns = [str(c).strip() for c in df.columns]
        numeric_cols = df.select_dtypes(include="number").columns.tolist()
        if not numeric_cols:
            return {"error": "未检测到数值列"}

        first_col_name = df.columns[0]
        if first_col_name in numeric_cols and len(numeric_cols) > 1:
            diffs = df[first_col_name].diff().dropna()
            if not diffs.empty and (diffs > 0).all():
                numeric_cols.remove(first_col_name)

        table_markdown = dataframe_to_markdown(df, max_rows=CONFIG["csv_preview_rows"])

        chart_type = (req.chart_type or "auto").lower()
        allowed = set(CONFIG["csv_chart_types"])
        if chart_type not in allowed:
            chart_type = "auto"

        if chart_type == "auto":
            if (len(numeric_cols) >= CONFIG["csv_radar_min_cols"]
                    and 1 < len(df) <= CONFIG["csv_radar_max_rows"]):
                chart_type = "radar3d"
            elif len(df) >= CONFIG["csv_line_min_rows"]:
                chart_type = "line"
            else:
                chart_type = "bar"

        image_base64 = ""
        if chart_type != "table":
            fig = plt.figure(figsize=(CONFIG["csv_figsize_w"], CONFIG["csv_figsize_h"]))
            first_col = df.columns[0]

            if chart_type == "line":
                ax = fig.add_subplot(111)
                for y in numeric_cols:
                    ax.plot(df[first_col].astype(str), df[y], marker="o", label=str(y))
                ax.set_xlabel(str(first_col))
                ax.set_ylabel("Value")
                ax.set_title("Line Chart")
                ax.legend()
                ax.tick_params(axis="x", rotation=CONFIG["csv_xlabel_rotation"])

            elif chart_type == "bar":
                ax = fig.add_subplot(111)
                plot_df = df.head(CONFIG["csv_bar_max_rows"]).copy()
                x = range(len(plot_df))
                width = CONFIG["csv_bar_width_ratio"] / len(numeric_cols)
                for i, col in enumerate(numeric_cols):
                    ax.bar([p + width * i for p in x], plot_df[col], width=width, label=str(col))
                ax.set_xticks([p + width * (len(numeric_cols) - 1) / 2 for p in x])
                ax.set_xticklabels(plot_df[first_col].astype(str), rotation=0)
                ax.set_xlabel(str(first_col))
                ax.set_title("Bar Chart")
                ax.legend()
                ax.grid(axis='y', linestyle='--', alpha=0.7)

            elif chart_type in {"radar", "radar3d"}:
                use_cols = numeric_cols[:CONFIG["csv_radar_max_dims"]]
                if len(use_cols) < CONFIG["csv_radar_min_cols"]:
                    ax = fig.add_subplot(111)
                    plot_df = df.head(CONFIG["csv_bar_max_rows"]).copy()
                    plot_df.set_index(first_col)[numeric_cols].plot(kind="bar", ax=ax)
                    ax.set_title("Bar Chart")
                    ax.tick_params(axis="x", rotation=CONFIG["csv_xlabel_rotation"])
                    chart_type = "bar"
                else:
                    norm = df[use_cols].apply(pd.to_numeric, errors="coerce").fillna(0).astype(float)
                    max_rows = CONFIG["csv_radar_max_rows"]
                    if len(norm) > max_rows:
                        norm = norm.head(max_rows)
                    labels = (df[first_col].astype(str).head(len(norm)).tolist()
                              if first_col not in numeric_cols
                              else [str(i + 1) for i in range(len(norm))])
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
            fig.savefig(buf, format="png", dpi=CONFIG["csv_dpi"], bbox_inches="tight")
            buf.seek(0)
            image_base64 = base64.b64encode(buf.read()).decode("utf-8")

        stats_text = df.describe(include="all").to_string()[:CONFIG["csv_stats_chars"]]
        fig_no = CONFIG["csv_caption_figure_no"]
        prompt = f"""你是学术写作专家。请严格根据以下 CSV 的真实列名、前几行和统计量，为图表生成学术规范 Figure Caption。
禁止编造数据中不存在的数值、趋势或结论。
图表类型：{chart_type}
列名：{list(df.columns)}
前5行：
{df.head(5).to_string()}
统计量：
{stats_text}

输出格式（只输出两行）：
第一行：英文 Figure Caption，以 "Figure {fig_no}." 开头。
第二行：中文核心结论，以 "中文结论：" 开头。"""
        try:
            caption = call_llm(prompt).choices[0].message.content.strip()
        except Exception:
            caption = (
                f"Figure {fig_no}. {chart_type} chart generated from uploaded CSV data. "
                f"中文结论：数据共 {len(df)} 行，数值列包括 {', '.join(numeric_cols)}。"
            )

        return {"image_base64": image_base64, "table_markdown": table_markdown,
                "caption": caption, "chart_type": chart_type,
                "columns": [str(c) for c in df.columns], "rows": int(len(df))}
    except Exception as e:
        return {"error": f"CSV 图表失败: {str(e)}"}
    finally:
        if fig is not None:
            plt.close(fig)


# ==========================================
# 模块六：论文框架生成 (重点修改区)
# ==========================================
class FrameworkReq(BaseModel):
    idea: str
    doc_filter: str = ""


def parse_json_loose(text: str) -> dict:
    """增强版 JSON 解析器，容错 LaTeX 单反斜杠问题"""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.S)
    text = re.sub(r"\s*```$", "", text, flags=re.S)
    
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        text = text[start:end + 1]
        
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 容错处理：大模型输出的 TikZ 经常出现单反斜杠，导致非法转义
        fixed = re.sub(
            r'(?<!\\)\\(begin|end|draw|node|path|fill|tikz|documentclass|usepackage)',
            r'\\\\\1', text
        )
        return json.loads(fixed)


@app.post("/generate_framework")
async def generate_framework(req: FrameworkReq):
    try:
        if not req.idea.strip():
            return {"error": "Idea 不能为空"}

        context_parts, candidates = [], []
        try:
            query_kwargs = {"query_texts": [req.idea], "n_results": CONFIG["framework_rag_k"]}
            if req.doc_filter:
                query_kwargs["where"] = {"source": req.doc_filter}
            results = collection.query(**query_kwargs)
            if results and results["documents"] and results["documents"][0]:
                for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
                    if is_reference_type(meta):
                        continue
                    src = meta.get("source", CONFIG["fallback_unknown_source"])
                    page = meta.get("page", "?")
                    context_parts.append(f"[{src} | Page {page}] {doc}")
                    if src not in candidates:
                        candidates.append(src)
                    if len(candidates) >= CONFIG["framework_max_candidates"]:
                        break
        except Exception as e:
            print(f"框架检索失败: {e}")

        candidate_text = ("\n".join(f"- {c}" for c in candidates)
                          if candidates else CONFIG["fallback_no_candidates"])
        context_text = ("\n\n".join(context_parts)
                        if context_parts else CONFIG["fallback_no_context_fragment"])

        # 🚨 升级 Prompt，强制扩展内容和图表复杂度
        prompt = f"""你是顶会审稿人。请根据用户 Idea 和本地真实文献片段，生成论文框架。
严格要求：
1. 必须输出完整的 Markdown 框架，必须包含以下五个二级标题：## Abstract、## Introduction、## Related Work、## Method、## Conclusion。每个章节写 100-200 字，不能敷衍。
2. References 只能从【候选参考文献】中选择，严禁编造候选列表之外的文献。如果候选为空，References 必须为空数组。
3. 生成 Mermaid 架构图脚本，以 "flowchart TD" 开头。🚨必须包含至少 5 个核心模块节点（如 Input, Embedding, Encoder, Decoder, Output），严禁只画两个节点敷衍了事。
4. 生成 TikZ 架构图脚本（LaTeX），直接输出 \\begin{{tikzpicture}}...\\end{{tikzpicture}}，不要 Markdown 代码围栏。🚨必须包含至少 3 个模块的相对复杂结构。
5. 严格返回 JSON，不要输出 Markdown 代码围栏：
{{"framework_markdown": "完整 Markdown 框架", "references": ["候选文献文件名"], "mermaid": "flowchart TD\\n    A[Input] --> B[Embedding]", "tikz": "\\\\begin{{tikzpicture}}...\\\\end{{tikzpicture}}"}}

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

        # 🚨 增强 References 匹配（去后缀、忽略大小写）
        raw_refs = data.get("references") or []
        if not isinstance(raw_refs, list):
            raw_refs = []
        
        def _norm_ref(s: str) -> str:
            s = os.path.basename(str(s)).strip().lower()
            return re.sub(r"\.pdf$", "", s)
        
        cand_map = {_norm_ref(c): c for c in candidates}
        references = []
        for r in raw_refs:
            key = _norm_ref(r)
            if key in cand_map:
                references.append(cand_map[key])
        
        # 如果大模型瞎写导致全空，且确实有候选文献，兜底给前两个
        if not references and candidates:
            references = candidates[:2]

        # 🚨 清洗 Mermaid 和 TikZ，去掉可能出现的 Markdown 围栏
        mermaid = data.get("mermaid") or ""
        if not isinstance(mermaid, str):
            mermaid = ""
        mermaid = re.sub(r"^```(?:mermaid)?\s*|\s*```$", "", mermaid.strip(), flags=re.S).strip()

        tikz = data.get("tikz") or ""
        if not isinstance(tikz, str):
            tikz = ""
        tikz = re.sub(r"^```(?:latex|tex)?\s*|\s*```$", "", tikz.strip(), flags=re.S).strip()

        if not framework_md:
            framework_md = CONFIG["fallback_framework_template"].format(
                idea=req.idea, refs_note=CONFIG["fallback_no_refs_found"],
            )
        if not re.match(r"^\s*(flowchart|graph)\s+", mermaid):
            mermaid = CONFIG["fallback_mermaid_flowchart"]
        if not tikz.startswith("\\begin{tikzpicture}"):
            tikz = ""

        return {"framework": framework_md, "references": references,
                "mermaid": mermaid, "tikz": tikz, "sources": candidates}
    except Exception as e:
        return {"error": f"论文框架生成失败: {str(e)}"}


# ==========================================
# Agent 路由
# ==========================================
class AgentReq(BaseModel):
    message: str
    doc_filter: str = ""
    doc_filters: List[str] = []


AGENT_TOOLS = [
    {"type": "function", "function": {
        "name": "search_arxiv",
        "description": "在 arXiv 检索最新论文。当用户想找论文/查最新进展时调用。",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "英文关键词"},
            "category": {"type": "string", "description": "arXiv 分类", "enum": CONFIG["arxiv_categories"]},
        }, "required": ["query"]},
    }},
    {"type": "function", "function": {
        "name": "citation_graph",
        "description": "生成引用图谱，挖掘基石论文。",
        "parameters": {"type": "object", "properties": {
            "doc_name": {"type": "string", "description": "本地已入库文献名"},
        }, "required": ["doc_name"]},
    }},
    {"type": "function", "function": {
        "name": "generate_review",
        "description": "基于某篇文献自动生成领域综述。",
        "parameters": {"type": "object", "properties": {
            "topic": {"type": "string", "description": "综述主题（本地文献名）"},
        }, "required": ["topic"]},
    }},
    {"type": "function", "function": {
        "name": "generate_framework",
        "description": "根据用户 idea 生成论文框架与 References、Mermaid架构图、TikZ架构图。",
        "parameters": {"type": "object", "properties": {
            "idea": {"type": "string", "description": "用户核心研究 Idea"},
        }, "required": ["idea"]},
    }},
    {"type": "function", "function": {
        "name": "translate_academic",
        "description": "将中文翻译成地道学术英文。",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string", "description": "待翻译中文"},
        }, "required": ["text"]},
    }},
    {"type": "function", "function": {
        "name": "future_work",
        "description": "提取 Future Work 并过滤已解决的旧 idea。",
        "parameters": {"type": "object", "properties": {
            "doc_name": {"type": "string", "description": "文献名"},
        }, "required": ["doc_name"]},
    }},
]


def _execute_tool_sync(name: str, args: dict, default_doc: str = "") -> dict:
    try:
        if name == "search_arxiv":
            query = (args.get("query") or "").strip()
            category = (args.get("category") or CONFIG["arxiv_default_category"]).strip()
            if category and not _looks_like_arxiv_category(category):
                category = CONFIG["arxiv_default_category"]
            fetch_n = CONFIG["arxiv_agent_fetch_n"]
            try:
                papers = _fetch_arxiv_live(query, category, fetch_n)
            except Exception:
                papers = _load_mock_arxiv()[:fetch_n]
            for p in papers:
                p["recommend_reason"] = _generate_recommend_reason(p, 0.0, "")
            return {"papers": papers, "count": len(papers)}

        if name == "citation_graph":
            doc = (args.get("doc_name") or default_doc).strip()
            if not doc:
                return {"error": "缺少 doc_name"}
            G = nx.DiGraph()
            G.add_node(doc)
            refs = _get_doc_refs(doc)
            for r in refs:
                clean = clean_ref_name(r)
                if clean:
                    G.add_edge(doc, clean)
            try:
                pr = nx.pagerank(G)
            except Exception:
                fb = CONFIG["graph_fallback_pr"]
                pr = {n: fb / max(len(G.nodes()), 1) for n in G.nodes()}
            top_n = CONFIG["graph_agent_top_nodes"]
            top = sorted(pr.items(), key=lambda x: x[1], reverse=True)[:top_n]
            scale = CONFIG["pagerank_scale"]
            return {"pillars": [{"name": k, "score": round(v * scale, 2)} for k, v in top], "total_refs": len(refs)}

        if name == "generate_review":
            topic = (args.get("topic") or default_doc).strip()
            if not topic:
                return {"error": "缺少 topic"}
            all_chunks = collection.get(where={"source": topic})
            parts = []
            if all_chunks and all_chunks.get("documents"):
                sorted_chunks = sorted(zip(all_chunks["ids"], all_chunks["documents"]), key=lambda x: x[0])
                prefix = CONFIG["review_macro_label_prefix"]
                parts = [d for _, d in sorted_chunks[:CONFIG["review_macro_chunks"]] if prefix in d]
            prompt = f"针对「{topic}」，用中文写一段简洁学术综述（核心架构/基石贡献/Future Work），禁止英文段落。\n参考：{chr(10).join(parts) if parts else '暂无'}"
            res = call_llm(prompt)
            return {"review": res.choices[0].message.content}

        # 🚨 Agent 中的 generate_framework 也同步升级
        if name == "generate_framework":
            idea = (args.get("idea") or "").strip()
            if not idea:
                return {"error": "缺少 idea"}
            try:
                qk = {"query_texts": [idea], "n_results": CONFIG["framework_rag_k"]}
                if default_doc:
                    qk["where"] = {"source": default_doc}
                r = collection.query(**qk)
                candidates = []
                if r and r.get("metadatas") and r["metadatas"][0]:
                    for m in r["metadatas"][0]:
                        src = m.get("source")
                        if src and src not in candidates:
                            candidates.append(src)
                        if len(candidates) >= CONFIG["framework_max_candidates"]:
                            break
            except Exception:
                candidates = []
            cand_text = ("\n".join(f"- {c}" for c in candidates)
                         if candidates else CONFIG["fallback_no_candidates_short"])
            
            prompt = f"""写论文框架。必须包含完整 Markdown（## Abstract, ## Introduction, ## Related Work, ## Method, ## Conclusion），每个章节 100-200 字。
References 必须从候选列表选择。
同时生成 Mermaid 架构图（至少 5 个节点）和 TikZ 架构图。
严格返回 JSON：{{"framework_markdown": "...", "references": [], "mermaid": "flowchart TD...", "tikz": "..."}}
Idea：{idea}
候选：{cand_text}"""
            
            try:
                res = call_llm(prompt, is_json=True)
                data = parse_json_loose(res.choices[0].message.content)
            except Exception:
                res = call_llm(prompt)
                data = parse_json_loose(res.choices[0].message.content)
                
            return {
                "framework": data.get("framework_markdown", ""),
                "references": data.get("references", candidates),
                "mermaid": data.get("mermaid", ""),
                "tikz": data.get("tikz", "")
            }

        if name == "translate_academic":
            text = (args.get("text") or "").strip()
            if not text:
                return {"error": "缺少 text"}
            prompt = f"请将以下中文翻译为地道学术英文，只输出译文：\n{text}"
            res = call_llm(prompt)
            return {"result": res.choices[0].message.content}

        if name == "future_work":
            doc = (args.get("doc_name") or default_doc).strip()
            if not doc:
                return {"error": "缺少 doc_name"}
            res = collection.query(
                query_texts=[CONFIG["future_work_query"]],
                n_results=CONFIG["future_work_chunks_per_doc"], where={"source": doc},
            )
            chunks = []
            if res and res.get("documents") and res["documents"][0]:
                for d, m in zip(res["documents"][0], res["metadatas"][0]):
                    if is_reference_type(m):
                        continue
                    chunks.append(d)
            if not chunks:
                return {"error": "未找到 Future Work 片段"}
            prompt = f"从以下片段提取 Future Work，剔除已被后续研究解决的旧 idea，只输出有探索价值的新方向，中文输出：\n{chr(10).join(chunks)}"
            res2 = call_llm(prompt)
            return {"future_work": res2.choices[0].message.content}

        return {"error": f"未知工具 {name}"}
    except Exception as e:
        return {"error": str(e)}


@app.post("/agent")
async def agent_endpoint(req: AgentReq):
    user_msg = (req.message or "").strip()
    if not user_msg:
        return {"error": "message 不能为空"}

    default_doc = req.doc_filters[0] if req.doc_filters else (req.doc_filter or "")
    steps = []
    framework_payload = None # 🆕 新增：用于捕获生成的框架数据传给前端
    
    # 🚨 核心修改：极度强硬的 System Prompt，逼迫大模型必须调工具
    system_prompt = (
        "你是 PaperPilot 智能科研 Agent。当用户意图匹配以下能力时，必须调用对应工具：\n"
        "- 找论文/查最新 → search_arxiv\n"
        "- 分析引用/找基石 → citation_graph\n"
        "- 写综述 → generate_review\n"
        "- 🚨🚨🚨【最高指令】：写论文框架、生成大纲、写Abstract/Introduction等，严禁自己直接生成纯文本，必须调用 generate_framework 工具！\n"
        "- 中译英学术 → translate_academic\n"
        "- 找未来方向 → future_work\n"
        "若无工具匹配，直接回答；若能调用工具，必须优先调用。"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]

    try:
        first = client.chat.completions.create(
            model=CONFIG["llm_model"], messages=messages,
            tools=AGENT_TOOLS, tool_choice="auto",
            temperature=CONFIG["llm_temperature"],
            timeout=CONFIG["agent_route_timeout"],
        )
    except Exception as e:
        return {"mode": "fallback", "answer": f"Agent 路由失败: {e}", "steps": steps}

    msg = first.choices[0].message
    if not msg.tool_calls:
        steps.append({"type": "thought", "content": "无需工具，直接回答"})
        return {"mode": "direct", "answer": msg.content or "", "steps": steps}

    messages.append({
        "role": "assistant", "content": msg.content or "",
        "tool_calls": [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in msg.tool_calls
        ],
    })

    for tc in msg.tool_calls:
        name = tc.function.name
        try:
            args = json.loads(tc.function.arguments or "{}")
        except Exception:
            args = {}
        steps.append({"type": "tool_call", "tool": name, "args": args})
        try:
            result = await asyncio.to_thread(_execute_tool_sync, name, args, default_doc)
        except Exception as e:
            result = {"error": str(e)}
        steps.append({"type": "tool_result", "tool": name,
                      "result_preview": str(result)[:CONFIG["agent_result_preview_chars"]]})
        messages.append({"role": "tool", "tool_call_id": tc.id,
                         "content": json.dumps(result, ensure_ascii=False)})
        
        # 🆕 捕获 generate_framework 的结果，赋值给 framework_payload
        if name == "generate_framework" and "error" not in result:
            framework_payload = result

    try:
        final = client.chat.completions.create(
            model=CONFIG["llm_model"], messages=messages,
            temperature=CONFIG["llm_temperature"],
            timeout=CONFIG["agent_final_timeout"],
        )
        answer = final.choices[0].message.content or ""
    except Exception as e:
        answer = f"工具执行后汇总失败: {e}"

    steps.append({"type": "thought", "content": "已汇总工具结果"})
    
    # 🆕 将 framework_payload 包含在返回体中
    return {
        "mode": "agent", 
        "answer": answer, 
        "steps": steps,
        "framework_payload": framework_payload
    }


# ==========================================
# 配置外发
# ==========================================
@app.get("/config")
def get_config():
    return {
        "arxiv_categories": CONFIG["arxiv_categories"],
        "arxiv_default_category": CONFIG["arxiv_default_category"],
        "arxiv_max_results": CONFIG["arxiv_max_results"],
        "relevance_high": CONFIG["relevance_high"],
        "relevance_medium": CONFIG["relevance_medium"],
        "page_marker_pattern": CONFIG["page_marker_pattern"],
    }