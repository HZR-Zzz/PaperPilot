import os
import re
import hashlib
import fitz  # PyMuPDF
import chromadb
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv
from tenacity import retry, wait_fixed, stop_after_attempt
from langchain_text_splitters import RecursiveCharacterTextSplitter

load_dotenv()
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = OpenAI(
    api_key=os.getenv("API_KEY"),
    base_url=os.getenv("BASE_URL")
)

chroma_client = chromadb.PersistentClient(path="./chroma_db")
collection = chroma_client.get_or_create_collection(name="papers")

@retry(wait=wait_fixed(2), stop=stop_after_attempt(3))
def call_llm(prompt):
    return client.chat.completions.create(
        model=os.getenv("MODEL_NAME"),
        messages=[{"role": "user", "content": prompt}]
    )

@retry(wait=wait_fixed(2), stop=stop_after_attempt(3))
def call_llm_stream(messages):
    return client.chat.completions.create(
        model=os.getenv("MODEL_NAME"),
        messages=messages,
        stream=True
    )

class ChatRequest(BaseModel):
    message: str
    doc_filter: str = ""

@app.post("/chat")
async def chat_endpoint(req: ChatRequest):
    try:
        # 1. 双语翻译检索
        search_queries = [req.message]
        if re.search('[\u4e00-\u9fa5]', req.message):
            try:
                trans_prompt = f"""你是一个学术检索专家。请将以下问题翻译成精准的英文，并提取出最核心的 3 个英文检索词。
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
        
        query_kwargs = {
            "query_texts": search_queries,
            "n_results": 5
        }
        if req.doc_filter:
            query_kwargs["where"] = {"source": req.doc_filter}
            
        results = collection.query(**query_kwargs)
        
        # 2. 学术专有名词硬匹配兜底（中英词典映射）
        extra_context = ""
        keyword_map = {
            "梯度消失": "vanishing gradient",
            "梯度爆炸": "exploding gradient",
            "优化器": "optimizer",
            "超参数": "hyperparameter",
            "正则化": "regularization",
            "损失函数": "loss function",
            "反向传播": "backpropagation",
            "注意力机制": "attention mechanism",
            "自然语言处理": "natural language processing",
            "计算机视觉": "computer vision"
        }
        
        matched_kws = []
        for zh_kw, en_kw in keyword_map.items():
            if zh_kw in req.message:
                matched_kws.append(en_kw)
                
        if matched_kws:
            keyword_kwargs = {
                "query_texts": matched_kws,
                "n_results": 3
            }
            if req.doc_filter:
                keyword_kwargs["where"] = {"source": req.doc_filter}
                
            keyword_results = collection.query(**keyword_kwargs)
            if keyword_results and keyword_results['documents']:
                for i, doc in enumerate(keyword_results['documents'][0]):
                    page = keyword_results['metadatas'][0][i]['page']
                    extra_context += f"[Page {page}]: {doc}\n\n"
        
        # 3. 拼接上下文
        context = extra_context
        if results and results['documents'] and results['documents'][0]:
            seen_docs = set()
            for i, doc in enumerate(results['documents'][0]):
                if doc in seen_docs: continue
                seen_docs.add(doc)
                page = results['metadatas'][0][i]['page']
                context += f"[Page {page}]: {doc}\n\n"
                
        # 4. 终极防幻觉 Prompt
        system_prompt = f"""你是 PaperPilot 科研助手。
请严格根据以下【参考内容】回答用户问题。
要求：
1. 必须基于参考内容，严禁凭空编造。
2. 如果参考内容没有提及，直接回答“未在文献中找到相关数据”。
3. 必须在回答的句子末尾标注来源页码，格式严格为：[Page X]。
4. 【最高指令】X 的值必须严格等于【参考内容】中你引用的那段话开头的 [Page X] 标记！

【参考内容】：
{context if context else "暂无文献数据"}
"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": req.message}
        ]
        
        def generate():
            try:
                response = call_llm_stream(messages)
                for chunk in response:
                    if chunk.choices[0].delta.content:
                        yield f"data: {chunk.choices[0].delta.content}\n\n"
            except Exception as e:
                yield f"data: [Error] 网络失败: {str(e)}\n\n"
                
        return StreamingResponse(generate(), media_type="text/event-stream")
    except Exception as e:
        return {"error": str(e)}


@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        doc = fitz.open(stream=contents, filetype="pdf")
        
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=50,
            length_function=len
        )
        
        all_chunks = []
        all_metadatas = []
        all_ids = []
        
        for page_num, page in enumerate(doc, start=1):
            page_text = page.get_text()
            if not page_text.strip(): continue
            
            chunks = text_splitter.split_text(page_text)
            for i, chunk in enumerate(chunks):
                chunk_with_page = f"[Page {page_num}] {chunk}"
                all_chunks.append(chunk_with_page)
                all_metadatas.append({"page": page_num})
                all_ids.append(f"{file.filename}_p{page_num}_c{i}")
                
        if all_chunks:
            collection.delete(where={"source": file.filename})
            for meta in all_metadatas:
                meta["source"] = file.filename
                
            collection.add(
                documents=all_chunks,
                metadatas=all_metadatas,
                ids=all_ids
            )
            
        return {"status": "success", "message": f"成功解析并入库 {len(all_chunks)} 个文本块！"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def get_simhash(text):
    clean_text = re.sub(r'\s+', '', text)
    if not clean_text: return 0, 0
    v = [0] * 64
    features = [clean_text[i:i+4] for i in range(0, len(clean_text), 4)]
    for feature in features:
        feature_hash = int(hashlib.md5(feature.encode('utf-8')).hexdigest(), 16)
        for i in range(64):
            if feature_hash & (1 << i): v[i] += 1
            else: v[i] -= 1
    fingerprint = 0
    for i in range(64):
        if v[i] > 0: fingerprint |= (1 << i)
    return fingerprint, len(features)

@app.post("/dedup")
async def check_dedup(text1: str = Form(...), text2: str = Form(...)):
    try:
        hash1, len1 = get_simhash(text1)
        hash2, len2 = get_simhash(text2)
        if len1 == 0 or len2 == 0: return {"similarity": 0, "is_duplicate": False, "message": "文本为空"}
        
        distance = bin(hash1 ^ hash2).count('1')
        similarity = (1 - distance / 64) * 100
        
        if similarity > 85.0:
            is_duplicate = True
            message = "检测到高度相似版本，建议直接覆盖！"
        elif similarity > 70.0:
            is_duplicate = True
            message = f"检测到同一论文的不同修订版本（相似度 {round(similarity, 2)}%）。建议对比修订差异，并保留最新版本！"
        else:
            is_duplicate = False
            message = "正常论文，无重复。"
            
        return {"similarity": round(similarity, 2), "is_duplicate": is_duplicate, "message": message}
    except Exception as e:
        return {"error": str(e)}

@app.post("/diff")
async def compare_diff(text_old: str = Form(...), text_new: str = Form(...)):
    try:
        prompt = f"你是学术审稿人。请用 3 句话总结【新版】相较于【旧版】的主要修订差异。\n旧版：{text_old[:4000]}\n新版：{text_new[:4000]}"
        response = call_llm(prompt)
        return {"diff_summary": response.choices[0].message.content}
    except Exception as e:
        return {"error": str(e)}