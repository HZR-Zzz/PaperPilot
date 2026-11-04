"use client";
import { useState } from "react";

export default function Home() {
  const [input, setInput] = useState("");
  const [output, setOutput] = useState("");
  const [loading, setLoading] = useState(false);
  
  const [file1, setFile1] = useState<File | null>(null);
  const [file2, setFile2] = useState<File | null>(null);
  const [dedupResult, setDedupResult] = useState<string>("");
  const [dbMessage, setDbMessage] = useState<string>("");
  
  // 文献列表管理
  const [docList, setDocList] = useState<{id: string, name: string}[]>([
    { id: "1706.03762v1.pdf", name: "1706.03762v1.pdf" }
  ]);
  const [activeDoc, setActiveDoc] = useState<string>("1706.03762v1.pdf"); 

  // ===== 模块：入库与删除 =====
  const handleUploadToDB = async () => {
    if (!file1) return alert("请先选择一篇 PDF");
    setDbMessage("正在解析并存入...");
    try {
      const formData = new FormData();
      formData.append("file", file1);
      const res = await fetch("http://127.0.0.1:8000/upload", { method: "POST", body: formData });
      const data = await res.json();
      setDbMessage(data.message || "入库成功！");
      
      if (!docList.find(d => d.name === file1.name)) {
        const newDoc = { id: file1.name, name: file1.name };
        setDocList([...docList, newDoc]);
        setActiveDoc(newDoc.name);
      }
    } catch (error: any) {
      setDbMessage("入库失败：" + error.message);
    }
  };

  const handleDeleteDoc = (docName: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (confirm(`确定要移除 ${docName} 吗？`)) {
      setDocList(docList.filter(d => d.name !== docName));
      if (activeDoc === docName) setActiveDoc("");
      setDbMessage(`已移除 ${docName}`);
    }
  };

  // ===== 模块：去重与差异 =====
  const handleDedup = async () => {
    if (!file1 || !file2) return alert("请先选择两个 PDF 文件");
    setDedupResult("正在解析并计算相似度...");
    try {
      const formData1 = new FormData(); formData1.append("file", file1);
      const res1 = await fetch("http://127.0.0.1:8000/upload", { method: "POST", body: formData1 });
      const data1 = await res1.json();

      const formData2 = new FormData(); formData2.append("file", file2);
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
        setDedupResult(`去重失败：${JSON.stringify(dedupJson)}`);
      }
    } catch (error: any) {
      setDedupResult(`异常：${error.message}`);
    }
  };

  const handleDiff = async () => {
    if (!file1 || !file2) return alert("请先选择两个 PDF 文件");
    setDedupResult("正在调用大模型分析版本差异，请稍候...");
    try {
      const formData1 = new FormData(); formData1.append("file", file1);
      const res1 = await fetch("http://127.0.0.1:8000/upload", { method: "POST", body: formData1 });
      const data1 = await res1.json();

      const formData2 = new FormData(); formData2.append("file", file2);
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
      setDedupResult(`异常：${error.message}`);
    }
  };

  // ===== 模块：RAG 问答 =====
  const handleSend = async () => {
    if (!input) return;
    setLoading(true);
    setOutput("");
    try {
      const response = await fetch("http://127.0.0.1:8000/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: input, doc_filter: activeDoc }),
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

  const renderOutput = () => {
    if (!output) return "AI 回复将在这里显示...";
    const parts = output.split(/(\[Page \d+\])/g);
    return parts.map((part, index) => {
      if (part.match(/\[Page \d+\]/)) {
        return (
          <span key={index} style={{ color: "#ffffff", backgroundColor: "#3b82f6", padding: "2px 8px", borderRadius: "6px", margin: "0 4px", fontWeight: "bold" }}>
            {part}
          </span>
        );
      }
      return <span key={index}>{part}</span>;
    });
  };

  const styles = {
    container: { minHeight: "100vh", backgroundColor: "#0f172a", color: "#f1f5f9", padding: "2rem", fontFamily: "sans-serif" },
    header: { fontSize: "2rem", fontWeight: "bold", textAlign: "center" as const, color: "#60a5fa", marginBottom: "2rem" },
    grid: { display: "grid", gridTemplateColumns: "1fr 2fr", gap: "1.5rem", maxWidth: "80rem", margin: "0 auto" },
    card: { backgroundColor: "#1e293b", padding: "1.5rem", borderRadius: "0.75rem", border: "1px solid #334155", marginBottom: "1.5rem" },
    cardTitle: { fontSize: "1.25rem", fontWeight: "600", marginBottom: "1rem", color: "#ffffff" },
    fileInput: { backgroundColor: "#334155", padding: "0.5rem", borderRadius: "0.25rem", color: "#fff", cursor: "pointer", width: "100%", marginBottom: "0.5rem" },
    btnGreen: { backgroundColor: "#16a34a", color: "white", padding: "0.5rem 1rem", borderRadius: "0.5rem", fontWeight: "bold", border: "none", cursor: "pointer", width: "100%" },
    btnBlue: { backgroundColor: "#2563eb", color: "white", padding: "0.5rem 1rem", borderRadius: "0.5rem", fontWeight: "bold", border: "none", cursor: "pointer" },
    btnPurple: { backgroundColor: "#9333ea", color: "white", padding: "0.5rem 1rem", borderRadius: "0.5rem", fontWeight: "bold", border: "none", cursor: "pointer" },
    btnRed: { backgroundColor: "#dc2626", color: "white", padding: "0.2rem 0.5rem", borderRadius: "0.25rem", fontSize: "0.75rem", cursor: "pointer", border: "none" },
    resultBox: { backgroundColor: "#0f172a", padding: "1rem", borderRadius: "0.5rem", color: "#4ade80", fontFamily: "monospace", border: "1px solid #166534", marginTop: "1rem", whiteSpace: "pre-wrap" as const },
    inputBox: { flex: 1, backgroundColor: "#334155", border: "1px solid #475569", padding: "0.75rem", borderRadius: "0.5rem", color: "white", outline: "none" },
    outputBox: { flex: 1, minHeight: "400px", backgroundColor: "#0f172a", padding: "1rem", borderRadius: "0.5rem", color: "#d1d5db", fontFamily: "monospace", border: "1px solid #334155", whiteSpace: "pre-wrap" as const, overflowY: "auto" as const },
    docItem: (isActive: boolean) => ({ 
      display: "flex", justifyContent: "space-between", alignItems: "center", 
      padding: "0.5rem", backgroundColor: isActive ? "#1e3a8a" : "#334155", 
      border: isActive ? "1px solid #60a5fa" : "1px solid transparent",
      borderRadius: "0.25rem", marginBottom: "0.5rem", cursor: "pointer"
    })
  };

  return (
    <div style={styles.container}>
      <h1 style={styles.header}>PaperPilot 科研助手</h1>

      <div style={styles.grid}>
        {/* 左栏：管理区 */}
        <div>
          <div style={styles.card}>
            <h2 style={styles.cardTitle}>📚 文献管理库</h2>
            <div style={{ marginBottom: "1rem" }}>
              {docList.map((doc, i) => (
                <div key={i} style={styles.docItem(activeDoc === doc.name)} onClick={() => setActiveDoc(doc.name)}>
                  <span style={{ fontSize: "0.875rem", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "75%", color: activeDoc === doc.name ? "#93c5fd" : "#fff" }}>
                    {doc.name}
                  </span>
                  <button onClick={(e) => handleDeleteDoc(doc.name, e)} style={styles.btnRed}>删除</button>
                </div>
              ))}
            </div>
            <input type="file" accept=".pdf" onChange={(e) => setFile1(e.target.files?.[0] || null)} style={styles.fileInput} />
            <button onClick={handleUploadToDB} style={styles.btnGreen}>上传并存入知识库</button>
            {dbMessage && <div style={{...styles.resultBox, color: "#4ade80"}}>{dbMessage}</div>}
          </div>

          <div style={styles.card}>
            <h2 style={styles.cardTitle}>🔍 文献去重比对</h2>
            <input type="file" accept=".pdf" onChange={(e) => setFile1(e.target.files?.[0] || null)} style={styles.fileInput} />
            <input type="file" accept=".pdf" onChange={(e) => setFile2(e.target.files?.[0] || null)} style={styles.fileInput} />
            <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.5rem" }}>
              <button onClick={handleDedup} style={styles.btnBlue}>开始检测</button>
              <button onClick={handleDiff} style={styles.btnPurple}>查看差异</button>
            </div>
            {dedupResult && <div style={styles.resultBox}>{dedupResult}</div>}
          </div>
        </div>

        {/* 右栏：问答区 */}
        <div style={styles.card}>
          <h2 style={styles.cardTitle}>🤖 抗幻觉问答 (RAG 溯源)</h2>
          {activeDoc && <p style={{fontSize: "0.85rem", color: "#4ade80", marginBottom: "0.5rem"}}>当前提问范围：{activeDoc}</p>}
          <div style={{ display: "flex", flexDirection: "column", gap: "1rem", height: "100%" }}>
            <div style={styles.outputBox}>{renderOutput()}</div>
            <div style={{ display: "flex", gap: "1rem" }}>
              <input
                style={styles.inputBox}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="例如：Transformer 的训练用了多少块 GPU？"
                onKeyDown={(e) => e.key === 'Enter' && handleSend()}
              />
              <button onClick={handleSend} disabled={loading} style={{...styles.btnBlue, opacity: loading ? 0.5 : 1}}>
                {loading ? "思考中..." : "发送"}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}