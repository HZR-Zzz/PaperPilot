"use client";
import { useState } from "react";

export default function Home() {
  const [input, setInput] = useState("");
  const [output, setOutput] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSend = async () => {
    if (!input) return;
    setLoading(true);
    setOutput("");

    try {
      const response = await fetch("http://127.0.0.1:8000/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: input }),
      });

      if (!response.body) throw new Error("No body");
      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        
        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split("\n");
        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const text = line.replace("data: ", "");
            if (text) setOutput((prev) => prev + text);
          }
        }
      }
    } catch (error) {
      setOutput("请求失败，请检查后端是否启动。");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-8 max-w-2xl mx-auto mt-20 font-sans">
      <h1 className="text-3xl font-bold mb-8 text-blue-600">PaperPilot 联调测试</h1>
      <div className="flex gap-4 mb-6">
        <input
          className="border-2 border-gray-300 p-3 flex-1 rounded-lg outline-none focus:border-blue-500"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="输入测试内容..."
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
        />
        <button
          onClick={handleSend}
          disabled={loading}
          className="bg-blue-600 hover:bg-blue-700 text-white font-bold px-6 py-3 rounded-lg transition-colors"
        >
          {loading ? "思考中..." : "发送"}
        </button>
      </div>
      
      <div className="border-2 border-gray-200 p-6 rounded-lg min-h-[300px] bg-gray-50 whitespace-pre-wrap text-gray-800 text-lg">
        {output || "AI 的回复将在这里以打字机效果出现..."}
      </div>
    </div>
  );
}

