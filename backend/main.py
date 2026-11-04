import os
import re
import hashlib
import fitz  # PyMuPDF
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv
from tenacity import retry, wait_fixed, stop_after_attempt

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

# ================= 模块二：流式对话 =================
class ChatRequest(BaseModel):
    message: str

@retry(wait=wait_fixed(2), stop=stop_after_attempt(3))
def call_llm_stream(messages):
    return client.chat.completions.create(
        model=os.getenv("MODEL_NAME"),
        messages=messages,
        stream=True
    )

@app.post("/chat")
async def chat_endpoint(req: ChatRequest):
    messages = [
        {"role": "system", "content": "你是 PaperPilot 科研助手。你的任务是为大学生和科研人员提供文献解析、精准问答、图谱分析与写作辅助。请保持客观严谨的学术口吻，回答时尽量使用 Markdown 格式排版，严禁编造未提供的数据。"},
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


# ================= 模块一：PDF解析 =================
@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        doc = fitz.open(stream=contents, filetype="pdf")
        text = ""
        for page in doc:
            text += page.get_text()
            
        if len(text.strip()) < 50:
            return {"status": "warning", "message": "疑似扫描件", "text": "OCR占位"}
        return {"status": "success", "text": text, "page_count": len(doc)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ================= 🌟 手写超稳定版 SimHash 去重算法 =================
def get_simhash(text):
    # 去除空白字符
    clean_text = re.sub(r'\s+', '', text)
    if not clean_text:
        return 0, 0
    
    # 将文本分块提取特征（比如每 4 个字符算一个特征）
    v = [0] * 64
    features = [clean_text[i:i+4] for i in range(0, len(clean_text), 4)]
    
    for feature in features:
        # 计算 MD5 哈希
        feature_hash = int(hashlib.md5(feature.encode('utf-8')).hexdigest(), 16)
        for i in range(64):
            bitmask = 1 << i
            if feature_hash & bitmask:
                v[i] += 1
            else:
                v[i] -= 1
                
    fingerprint = 0
    for i in range(64):
        if v[i] > 0:
            fingerprint |= (1 << i)
    return fingerprint, len(features)

@app.post("/dedup")
async def check_dedup(text1: str = Form(...), text2: str = Form(...)):
    try:
        # 计算指纹
        hash1, len1 = get_simhash(text1)
        hash2, len2 = get_simhash(text2)
        
        if len1 == 0 or len2 == 0:
            return {"similarity": 0, "is_duplicate": False, "message": "文本内容为空"}

        # 计算汉明距离
        distance = bin(hash1 ^ hash2).count('1')
        similarity = (1 - distance / 64) * 100
        
        # 🌟 学术级动态阈值判断逻辑
        if similarity > 85.0:
            is_duplicate = True
            message = "检测到高度相似版本，建议直接覆盖！"
        elif similarity > 70.0:
            is_duplicate = True
            message = f"检测到同一论文的不同修订版本（相似度 {round(similarity, 2)}%）。建议对比修订差异，并保留最新版本！"
        else:
            is_duplicate = False
            message = "正常论文，无重复。"
        
        return {
            "similarity": round(similarity, 2),
            "is_duplicate": is_duplicate,
            "message": message
        }
    except Exception as e:
        return {"error": str(e)}

# ================= 大模型对比版本差异接口 =================
@retry(wait=wait_fixed(2), stop=stop_after_attempt(3))
def call_llm(prompt):
    return client.chat.completions.create(
        model=os.getenv("MODEL_NAME"),
        messages=[{"role": "user", "content": prompt}]
    )

@app.post("/diff")
async def compare_diff(text_old: str = Form(...), text_new: str = Form(...)):
    try:
        prompt = f"你是学术审稿人。请用 3 句话总结【新版】相较于【旧版】的主要修订差异。\n旧版：{text_old[:4000]}\n新版：{text_new[:4000]}"
        response = call_llm(prompt)
        return {"diff_summary": response.choices[0].message.content}
    except Exception as e:
        return {"error": str(e)}