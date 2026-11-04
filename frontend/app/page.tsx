"use client";
import { useState } from "react";

export default function Home() {
  const [input, setInput] = useState("");
  const [output, setOutput] = useState("");
  const [loading, setLoading] = useState(false);
  
  const [file1, setFile1] = useState<File | null>(null);
  const [file2, setFile2] = useState<File | null>(null);
  const [dedupResult, setDedupResult] = useState<string>("");

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
        for (const line of chunk.split("\n")) {
          if (line.startsWith("data: ")) {
            const text = line.replace("data: ", "");
            if (text) setOutput((prev) => prev + text);
          }
        }
      }
    } catch (error) {
      setOutput("请求失败，请检查后端服务。");
    } finally {
      setLoading(false);
    }
  };

  const handleDedup = async () => {
    if (!file1 || !file2) {
      alert("请先选择两个 PDF 文件");
      return;
    }
    setDedupResult("正在解析并计算相似度...");
    
    try {
      const formData1 = new FormData();
      formData1.append("file", file1);
      const res1 = await fetch("http://127.0.0.1:8000/upload", { method: "POST", body: formData1 });
      const data1 = await res1.json();

      const formData2 = new FormData();
      formData2.append("file", file2);
      const res2 = await fetch("http://127.0.0.1:8000/upload", { method: "POST", body: formData2 });
      const data2 = await res2.json();

      const dedupData = new FormData();
      dedupData.append("text1", data1.text || "");
      dedupData.append("text2", data2.text || "");
      
      const res3 = await fetch("http://127.0.0.1:8000/dedup", { method: "POST", body: dedupData });
      const dedupJson = await res3.json();

      if (dedupJson.similarity !== undefined) {
        setDedupResult(`检测完成：相似度 ${dedupJson.similarity}% 。${dedupJson.message}`);
      } else {
        setDedupResult(`去重失败，错误信息：${JSON.stringify(dedupJson)}`);
      }
    } catch (error: any) {
      setDedupResult(`网络请求异常：${error.message}`);
    }
  };

  const handleDiff = async () => {
    if (!file1 || !file2) {
      alert("请先选择两个 PDF 文件");
      return;
    }
    setDedupResult("正在调用大模型分析版本差异，请稍候...");

    try {
      const formData1 = new FormData(); 
      formData1.append("file", file1);
      const res1 = await fetch("http://127.0.0.1:8000/upload", { method: "POST", body: formData1 });
      const data1 = await res1.json();

      const formData2 = new FormData(); 
      formData2.append("file", file2);
      const res2 = await fetch("http://127.0.0.1:8000/upload", { method: "POST", body: formData2 });
      const data2 = await res2.json();

      const diffData = new FormData();
      diffData.append("text_old", data1.text || "");
      diffData.append("text_new", data2.text || "");
      
      const res3 = await fetch("http://127.0.0.1:8000/diff", { method: "POST", body: diffData });
      const diffJson = await res3.json();

      if (diffJson.diff_summary) {
        setDedupResult(`【大模型版本差异总结】\n${diffJson.diff_summary}`);
      } else {
        setDedupResult(`分析失败：${JSON.stringify(diffJson)}`);
      }
    } catch (error: any) {
      setDedupResult(`请求异常：${error.message}`);
    }
  };

  // 使用内联样式确保在任何环境下都能显示深色主题
  const styles = {
    container: { minHeight: "100vh", backgroundColor: "#0f172a", color: "#f1f5f9", padding: "2rem", fontFamily: "sans-serif" },
    header: { fontSize: "2.25rem", fontWeight: "bold", textAlign: "center" as const, color: "#60a5fa", marginBottom: "2rem" },
    card: { backgroundColor: "#1e293b", padding: "1.5rem", borderRadius: "0.75rem", border: "1px solid #334155", marginBottom: "2rem" },
    cardTitle: { fontSize: "1.5rem", fontWeight: "600", marginBottom: "1rem", color: "#ffffff" },
    row: { display: "flex", gap: "1rem", alignItems: "center", flexWrap: "wrap" as const, marginBottom: "1rem" },
    fileInput: { backgroundColor: "#334155", padding: "0.5rem", borderRadius: "0.25rem", color: "#fff", cursor: "pointer" },
    btnBlue: { backgroundColor: "#2563eb", color: "white", padding: "0.5rem 1.5rem", borderRadius: "0.5rem", fontWeight: "bold", border: "none", cursor: "pointer" },
    btnPurple: { backgroundColor: "#9333ea", color: "white", padding: "0.5rem 1.5rem", borderRadius: "0.5rem", fontWeight: "bold", border: "none", cursor: "pointer" },
    resultBox: { backgroundColor: "#0f172a", padding: "1rem", borderRadius: "0.5rem", color: "#4ade80", fontFamily: "monospace", border: "1px solid #166534", whiteSpace: "pre-wrap" as const },
    inputBox: { flex: 1, backgroundColor: "#334155", border: "1px solid #475569", padding: "0.75rem", borderRadius: "0.5rem", color: "white", outline: "none" },
    outputBox: { minHeight: "150px", backgroundColor: "#0f172a", padding: "1rem", borderRadius: "0.5rem", color: "#d1d5db", fontFamily: "monospace", border: "1px solid #334155", whiteSpace: "pre-wrap" as const }
  };

  return (
    <div style={styles.container}>
      <div style={{ maxWidth: "64rem", margin: "0 auto" }}>
        <h1 style={styles.header}>PaperPilot 科研助手</h1>

        {/* 去重模块 */}
        <div style={styles.card}>
          <h2 style={styles.cardTitle}>文献智能去重与版本比对</h2>
          <div style={styles.row}>
            <input type="file" accept=".pdf" onChange={(e) => setFile1(e.target.files?.[0] || null)} style={styles.fileInput} />
            <span style={{ color: "#94a3b8" }}>对比</span>
            <input type="file" accept=".pdf" onChange={(e) => setFile2(e.target.files?.[0] || null)} style={styles.fileInput} />
            
            <button onClick={handleDedup} style={styles.btnBlue}>开始检测</button>
            <button onClick={handleDiff} style={styles.btnPurple}>查看差异</button>
          </div>
          {dedupResult && <div style={styles.resultBox}>{dedupResult}</div>}
        </div>

        {/* 对话模块 */}
        <div style={styles.card}>
          <h2 style={styles.cardTitle}>抗幻觉问答 Agent</h2>
          <div style={styles.row}>
            <input
              style={styles.inputBox}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="输入您的问题..."
              onKeyDown={(e) => e.key === 'Enter' && handleSend()}
            />
            <button onClick={handleSend} disabled={loading} style={{...styles.btnBlue, opacity: loading ? 0.5 : 1}}>
              {loading ? "思考中..." : "发送"}
            </button>
          </div>
          <div style={styles.outputBox}>
            {output || "AI 回复将在这里显示..."}
          </div>
        </div>
      </div>
    </div>
  );
}