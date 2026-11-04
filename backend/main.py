import os
from fastapi import FastAPI
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

class ChatRequest(BaseModel):
    message: str

@retry(wait=wait_fixed(2), stop=stop_after_attempt(3))
def call_llm(messages):
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
            response = call_llm(messages)
            for chunk in response:
                if chunk.choices[0].delta.content:
                    yield f"data: {chunk.choices[0].delta.content}\n\n"
        except Exception as e:
            yield f"data: [Error] 网络失败: {str(e)}\n\n"
            
    return StreamingResponse(generate(), media_type="text/event-stream")