"use client";
import React, { useState, useRef, useMemo, useCallback, useEffect } from "react";
import * as echarts from 'echarts'; 

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

export default function Home() {
  const [input, setInput] = useState("");
  const [output, setOutput] = useState("");
  const [loading, setLoading] = useState(false);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [dedupFile1, setDedupFile1] = useState<File | null>(null);
  const [dedupFile2, setDedupFile2] = useState<File | null>(null);
  const [dedupResult, setDedupResult] = useState<string>("");
  const [dbMessage, setDbMessage] = useState<string>("");
  const [docList, setDocList] = useState<{id: string, name: string}[]>([]);
  const [activeDoc, setActiveDoc] = useState<string>(""); 
  const [fullRawText, setFullRawText] = useState<string>(""); 
  const [displayedRawText, setDisplayedRawText] = useState<string>(""); 
  const [translatedText, setTranslatedText] = useState<string>(""); 
  const [hasRawText, setHasRawText] = useState(false); 
  const [isLoadingEn, setIsLoadingEn] = useState(false); 
  const [isTranslating, setIsTranslating] = useState(false); 
  const [selectedText, setSelectedText] = useState("");
  const [popupPos, setPopupPos] = useState({ x: 0, y: 0, visible: false });
  const [popupResult, setPopupResult] = useState<string>("");
  const [popupLoading, setPopupLoading] = useState(false);
  const [graphData, setGraphData] = useState<{nodes: any[], links: any[]}>({ nodes: [], links: [] });
  const [isGraphLoading, setIsGraphLoading] = useState(false);
  const [reviewText, setReviewText] = useState<string>("");

  // 模块四和模块六的 State
  const [arxivPapers, setArxivPapers] = useState<any[]>([]);
  const [csvChart, setCsvChart] = useState<{ image: string, caption: string } | null>(null);
  const [paperIdea, setPaperIdea] = useState("");
  const [paperFramework, setPaperFramework] = useState("");
  const [isGeneratingFramework, setIsGeneratingFramework] = useState(false);
  const [isGeneratingChart, setIsGeneratingChart] = useState(false);

  const leftScrollRef = useRef<HTMLDivElement>(null);
  const rightScrollRef = useRef<HTMLDivElement>(null);
  const isSyncingRef = useRef(false); 
  const chartDomRef = useRef<HTMLDivElement>(null); 

  const handleUploadToDB = async () => {
    if (!uploadFile) return alert("请先选择一篇 PDF");
    setDbMessage("正在解析并存入，请稍候...");
    setFullRawText(""); setDisplayedRawText(""); setTranslatedText(""); 
    setHasRawText(false); setIsLoadingEn(false); setIsTranslating(false);
    setGraphData({ nodes: [], links: [] }); setReviewText("");
    try {
      const formData = new FormData(); formData.append("file", uploadFile);
      const res = await fetch(`${API_BASE}/upload`, { method: "POST", body: formData });
      const data = await res.json();
      setDbMessage(data.message || "入库成功！");
      setDocList(prev => {
        if (prev.find(d => d.name === uploadFile.name)) return prev;
        return [...prev, { id: uploadFile.name, name: uploadFile.name }];
      });
      setActiveDoc(uploadFile.name);
      if (data.text) {
        const cleanText = data.text.replace(/<span[^>]*>|<\/span>/g, '');
        setFullRawText(cleanText); setHasRawText(true); 
        setDisplayedRawText("已准备就绪。点击右上角【显示原文】开始阅读。");
      }
    } catch (error: any) {
      setDbMessage("入库失败：" + error.message);
    }
  };

  const handleLoadEnglish = () => {
    if (!fullRawText || isLoadingEn) return;
    setIsLoadingEn(true); setDisplayedRawText(""); 
    const paragraphs = fullRawText.split(/\n+/).map(p => p.trim()).filter(p => p.length > 0);
    let currentIndex = 0; const batchSize = 10; 
    const loadNextBatch = () => {
      if (currentIndex >= paragraphs.length) { setIsLoadingEn(false); return; }
      const nextChunk = paragraphs.slice(currentIndex, currentIndex + batchSize).join("\n\n");
      setDisplayedRawText(prev => prev + (prev ? "\n\n" : "") + nextChunk);
      currentIndex += batchSize; setTimeout(loadNextBatch, 20);
    };
    loadNextBatch();
  };

  const handleFullTranslate = async () => {
    if (!fullRawText || isTranslating) return;
    setIsTranslating(true); setTranslatedText("正在翻译正文内容，请稍候...\n\n");
    let cleanedTextForTrans = fullRawText;
    const lines = cleanedTextForTrans.split('\n').map(l => l.trim()).filter(l => l.length > 0);
    const originalTitle = lines.length > 0 ? lines[0] : ""; 
    if (originalTitle) cleanedTextForTrans = cleanedTextForTrans.replace(originalTitle, "");
    const refIndex = cleanedTextForTrans.search(/\n\s*References/i);
    if (refIndex > -1) cleanedTextForTrans = cleanedTextForTrans.substring(0, refIndex);
    cleanedTextForTrans = cleanedTextForTrans
      .replace(/Figure \d+:.*?(\n|$)/g, '').replace(/Table \d+:.*?(\n|$)/g, '')
      .replace(/[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/g, '')
      .replace(/arXiv:\d+\.\d+v\d+\s+\[.*?\]\s+\d+\s+[A-Za-z]+\s+\d{4}/g, '')
      .replace(/<EOS>|<pad>/g, '').replace(/^\s*\*.*?等贡献.*?随机的。\s*$/gm, '') 
      .replace(/^\s*†.*?完成的工作。\s*$/gm, '').replace(/^\s*(华尔街日报|WSJ).*?F1.*?$/gm, '') 
      .replace(/of WSJ\)/g, '').replace(/^\d+(\.\d+)?\s*·\s*10\^?\d+$/gm, '').replace(/^[\d\s\.]+$/gm, '');
    const paragraphs = cleanedTextForTrans.split(/\n+/).map(p => p.trim()).filter(p => p.length > 5);
    const chunks = paragraphs.flatMap(p => p.length > 800 ? p.match(/.{1,800}/g) || [p] : [p]);
    if (chunks.length === 0) { setIsTranslating(false); setTranslatedText("未找到需要翻译的正文内容。"); return; }
    const results: string[] = new Array(chunks.length).fill("");
    let index = 0; const limit = 3;
    const worker = async () => {
      while (index < chunks.length) {
        const currentIndex = index++;
        try {
          const res = await fetch(`${API_BASE}/text_action`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text: chunks[currentIndex], action: "translate" })
          });
          const data = await res.json();
          let cleanResult = (data.result || "").replace(/<\/?text>/g, '').replace(/翻译结果如下：/g, '').trim();
          results[currentIndex] = cleanResult;
        } catch (error) { results[currentIndex] = ""; }
        const display = originalTitle + "\n\n" + results.filter(r => r !== "").join("\n\n");
        setTranslatedText(display);
        await new Promise(r => setTimeout(r, 10));
      }
    };
    await Promise.all(Array(limit).fill(null).map(() => worker()));
    setIsTranslating(false);
  };

  const handleSend = async () => {
    if (!input) return;
    setLoading(true); setOutput("");
    try {
      const response = await fetch(`${API_BASE}/chat`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: input, doc_filter: activeDoc }),
      });
      if (!response.body) throw new Error("No body");
      const reader = response.body.getReader(); const decoder = new TextDecoder("utf-8");
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
    } catch (error) { setOutput("请求失败，请检查后端服务。"); } finally { setLoading(false); }
  };

  const handleDedup = async (action: "dedup" | "diff") => {
    if (!dedupFile1 || !dedupFile2) return alert("请先选择两个 PDF 文件进行比对");
    setDedupResult("正在解析并比对，请稍候...");
    try {
      const formData1 = new FormData(); formData1.append("file", dedupFile1);
      const res1 = await fetch(`${API_BASE}/upload`, { method: "POST", body: formData1 });
      const data1 = await res1.json();
      const formData2 = new FormData(); formData2.append("file", dedupFile2);
      const res2 = await fetch(`${API_BASE}/upload`, { method: "POST", body: formData2 });
      const data2 = await res2.json();
      if (!data1.text || !data2.text) return setDedupResult(`解析失败！请检查后端。`);
      const reqData = new FormData();
      if (action === "dedup") {
        reqData.append("text1", data1.text); reqData.append("text2", data2.text);
        const res = await fetch(`${API_BASE}/dedup`, { method: "POST", body: reqData });
        const json = await res.json();
        setDedupResult(json.error ? `报错：${json.error}` : `检测完成：相似度 ${json.similarity}% 。${json.message}`);
      } else {
        reqData.append("text_old", data1.text); reqData.append("text_new", data2.text);
        const res = await fetch(`${API_BASE}/diff`, { method: "POST", body: reqData });
        const json = await res.json();
        setDedupResult(json.error ? `报错：${json.error}` : `【大模型版本差异总结】\n${json.diff_summary}`);
      }
    } catch (error: any) { setDedupResult(`请求异常：${error.message}`); }
  };

  const handleMouseUp = (e: React.MouseEvent) => {
    const selection = window.getSelection(); const text = selection?.toString().trim();
    if (text && text.length > 5) {
      const popupWidth = 320; const popupHeight = 150;
      let x = e.clientX; let y = e.clientY + 15;
      if (x + popupWidth > window.innerWidth) x = window.innerWidth - popupWidth - 20;
      if (y + popupHeight > window.innerHeight) y = e.clientY - popupHeight - 15;
      setSelectedText(text); setPopupPos({ x, y, visible: true }); setPopupResult("");
    } else { setPopupPos(prev => ({ ...prev, visible: false })); }
  };

  const handleTextAction = async (action: "translate" | "rewrite") => {
    if (!selectedText) return; setPopupLoading(true); setPopupResult("");
    try {
      const res = await fetch(`${API_BASE}/text_action`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: selectedText, action: action }),
      });
      const data = await res.json();
      let cleanResult = (data.result || data.error || "").replace(/<\/?text>/g, '').trim();
      setPopupResult(cleanResult);
    } catch (error) { setPopupResult("请求失败"); } finally { setPopupLoading(false); }
  };

  const handleScroll = useCallback((e: React.UIEvent<HTMLDivElement>, direction: 'left' | 'right') => {
    if (isSyncingRef.current) return;
    const source = e.currentTarget;
    const target = direction === 'left' ? rightScrollRef.current : leftScrollRef.current;
    if (!target) return;
    const denom = source.scrollHeight - source.clientHeight;
    if (denom <= 0) return;
    isSyncingRef.current = true;
    const scrollPercentage = source.scrollTop / denom;
    target.scrollTop = scrollPercentage * (target.scrollHeight - target.clientHeight);
    requestAnimationFrame(() => { isSyncingRef.current = false; });
  }, []);

  const handleLoadGraph = async () => {
    if (!activeDoc) return alert("请先在文献库中点击选中一篇文献！");
    setIsGraphLoading(true);
    try {
      const res = await fetch(`${API_BASE}/graph`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ doc_filter: activeDoc }),
      });
      const data = await res.json();
      if (!data.nodes || data.nodes.length === 0) {
        alert("图谱生成失败，后端未返回数据，请检查后端终端。");
      }
      setGraphData(data);
    } catch (error) { 
      console.error("获取图谱失败", error); 
      alert("请求图谱接口失败");
    } finally { setIsGraphLoading(false); }
  };

  const handleGenerateReview = async () => {
    if (!activeDoc) return alert("请先在文献库中点击选中一篇文献！");
    setReviewText("正在生成综述，请稍候...");
    try {
      const res = await fetch(`${API_BASE}/generate_review`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic: activeDoc }), 
      });
      const data = await res.json();
      setReviewText(data.review || data.error);
    } catch (error) { setReviewText("生成失败"); }
  };

  // 🚀 ECharts 渲染逻辑与图表 UI 升级（增加防重叠与自适应）
  useEffect(() => {
    if (!chartDomRef.current || graphData.nodes.length === 0) return;
    
    let myChart = echarts.getInstanceByDom(chartDomRef.current);
    if (myChart) myChart.dispose();
    myChart = echarts.init(chartDomRef.current);

    const sortedNodes = [...graphData.nodes].sort((a, b) => b.value - a.value);
    const topNodes = sortedNodes.slice(0, 6);

    const option = {
      backgroundColor: 'transparent', 
      tooltip: {
        trigger: 'axis',
        backgroundColor: '#1e293b',
        borderColor: '#3b82f6',
        textStyle: { color: '#fff' },
        axisPointer: { type: 'shadow' },
        confine: true, 
        extraCssText: 'max-width: 280px; white-space: normal; word-break: break-all; z-index: 999; box-shadow: 0 4px 12px rgba(0,0,0,0.5);' 
      },
      grid: { left: '3%', right: '12%', bottom: '3%', top: '5%', containLabel: true },
      xAxis: {
        type: 'value',
        splitNumber: 5,
        splitLine: { lineStyle: { color: '#334155' } },
        axisLabel: { 
          color: '#cbd5e1',
          hideOverlap: true // 🚨 智能隐藏重叠刻度，彻底解决数字挤在一起的问题
        }
      },
      yAxis: {
        type: 'category',
        data: topNodes.map(n => n.name.replace(/^[\(\[]\d+[\)\]]\s*/, '')).reverse(),
        axisLabel: { color: '#cbd5e1', fontSize: 10, width: 150, overflow: 'truncate' }, 
        axisLine: { lineStyle: { color: '#475569' } }
      },
      series: [
        {
          name: 'PageRank 权重',
          type: 'bar',
          data: topNodes.map(n => n.value).reverse(),
          itemStyle: { color: '#60a5fa', borderRadius: [0, 4, 4, 0] },
          label: { show: true, position: 'right', color: '#f1f5f9' }
        }
      ]
    };
    myChart.setOption(option);
    
    const handleResize = () => myChart.resize();
    window.addEventListener('resize', handleResize);
    return () => {
      window.removeEventListener('resize', handleResize);
      if (myChart) myChart.dispose();
    };
  }, [graphData]);

  const renderOutput = () => {
    if (!output) return "AI 回复将在这里显示...";
    let cleanOutput = output;
    cleanOutput = cleanOutput.replace(/(\[Page \d+\])\s*(?=\[Page \d+\])/g, '');
    const parts = cleanOutput.split(/(\[Page \d+\])/g);
    return parts.map((part, index) => {
      if (part.match(/\[Page \d+\]/)) {
        return (<span key={index} style={{ color: "#ffffff", backgroundColor: "#3b82f6", padding: "2px 8px", borderRadius: "6px", margin: "0 4px", fontWeight: "bold" }}>{part}</span>);
      }
      return <span key={index}>{part}</span>;
    });
  };

  const styles = {
    container: { minHeight: "100vh", backgroundColor: "#0f172a", color: "#f1f5f9", padding: "1rem", fontFamily: "sans-serif" },
    header: { fontSize: "1.5rem", fontWeight: "bold", textAlign: "center" as const, color: "#60a5fa", marginBottom: "1rem" },
    grid: { display: "grid", gridTemplateColumns: "360px 1fr 1fr", gap: "1rem", height: "calc(100vh - 80px)" },
    sidebar: { backgroundColor: "#1e293b", padding: "1rem", borderRadius: "0.75rem", display: "flex", flexDirection: "column" as const, gap: "1rem", overflowY: "auto" as const },
    card: { backgroundColor: "#1e293b", padding: "1rem", borderRadius: "0.75rem", border: "1px solid #334155", display: "flex", flexDirection: "column" as const, overflow: "hidden" },
    readerBox: { flex: 1, overflowY: "auto" as const, backgroundColor: "#0f172a", padding: "1rem", borderRadius: "0.5rem", whiteSpace: "pre-wrap" as const, fontSize: "0.9rem", lineHeight: "1.6", fontFamily: "Georgia, serif" },
    inputBox: { flex: 1, backgroundColor: "#334155", border: "1px solid #475569", padding: "0.5rem", borderRadius: "0.5rem", color: "white", outline: "none" },
    btnBlue: { backgroundColor: "#2563eb", color: "white", padding: "0.5rem 1rem", borderRadius: "0.5rem", fontWeight: "bold", border: "none", cursor: "pointer" },
    btnGreen: { backgroundColor: "#16a34a", color: "white", padding: "0.5rem 1rem", borderRadius: "0.5rem", fontWeight: "bold", border: "none", cursor: "pointer" },
    btnPurple: { backgroundColor: "#9333ea", color: "white", padding: "0.5rem 1rem", borderRadius: "0.5rem", fontWeight: "bold", border: "none", cursor: "pointer" },
    popup: { position: "absolute" as const, top: popupPos.y, left: popupPos.x, backgroundColor: "#1e293b", border: "1px solid #3b82f6", borderRadius: "0.5rem", padding: "0.75rem", zIndex: 1000, boxShadow: "0 8px 24px rgba(0,0,0,0.6)", display: "flex", flexDirection: "column" as const, gap: "0.5rem", width: "320px" },
    resultBox: { backgroundColor: "#0f172a", padding: "0.5rem", borderRadius: "0.5rem", color: "#4ade80", fontFamily: "monospace", border: "1px solid #166534", marginTop: "0.5rem", fontSize: "0.8rem", whiteSpace: "pre-wrap" as const }
  };

  const renderedRawText = useMemo(() => {
    const cleanText = displayedRawText.replace(/<span[^>]*>|<\/span>/g, '');
    const parts = cleanText.split(/(\[\d+\])/g);
    return parts.map((part, index) => {
      if (part.match(/^\[\d+\]$/)) {
        const refId = part.replace(/[\[\]]/g, "");
        return (
          <span key={index} style={{ color: "#60a5fa", cursor: "pointer", fontWeight: "bold", backgroundColor: "rgba(59, 130, 246, 0.1)", padding: "0 2px", borderRadius: "4px" }}
            onClick={(e) => {
              e.stopPropagation();
              let targetNode = document.getElementById(`ref-${refId}`);
              if (!targetNode && leftScrollRef.current) {
                const allSpans = leftScrollRef.current.querySelectorAll('span');
                for (let node of Array.from(allSpans)) {
                  if (node.textContent?.trim().startsWith(`[${refId}]`)) { targetNode = node as HTMLElement; break; }
                }
              }
              if (targetNode) {
                targetNode.scrollIntoView({ behavior: "smooth", block: "center" });
                const originalBg = targetNode.style.backgroundColor;
                targetNode.style.transition = "background-color 0.3s";
                targetNode.style.backgroundColor = "#2563eb"; targetNode.style.color = "white";
                setTimeout(() => { targetNode!.style.backgroundColor = originalBg; targetNode!.style.color = ""; }, 1500);
              } else { console.log(`引用 ${part} 位于尚未加载的段落，请继续点击【显示原文】。`); }
            }}
          >{part}</span>
        );
      }
      return <span key={index}>{part}</span>;
    });
  }, [displayedRawText]);

  useEffect(() => {
    const closePopup = () => setPopupPos(prev => ({ ...prev, visible: false }));
    window.addEventListener("mousedown", closePopup);
    return () => window.removeEventListener("mousedown", closePopup);
  }, []);

  return (
    <div style={styles.container}>
      <h1 style={styles.header}>PaperPilot 沉浸式科研阅读器</h1>
      <div style={styles.grid}>
        <div style={styles.sidebar}>
          <div>
            <h3 style={{marginBottom: "0.5rem", color: "#60a5fa"}}>📚 文献库</h3>
            {docList.length === 0 ? <p style={{fontSize: "0.8rem", color: "#64748b"}}>暂无文献，请上传</p> : docList.map((doc, i) => (
              <div key={i} onClick={() => setActiveDoc(doc.name)} style={{ padding: "0.5rem", backgroundColor: activeDoc === doc.name ? "#1e3a8a" : "#334155", borderRadius: "0.25rem", marginBottom: "0.5rem", cursor: "pointer", fontSize: "0.8rem" }}>
                {doc.name}
              </div>
            ))}
            <input type="file" accept=".pdf" onChange={(e) => setUploadFile(e.target.files?.[0] || null)} style={{ width: "100%", fontSize: "0.8rem", marginTop: "0.5rem" }} />
            <button onClick={handleUploadToDB} style={{...styles.btnGreen, width: "100%", marginTop: "0.5rem"}}>存入知识库</button>
            {dbMessage && <div style={{fontSize: "0.75rem", color: "#4ade80", marginTop: "0.5rem"}}>{dbMessage}</div>}
          </div>

          <div style={{ borderTop: "1px solid #334155", paddingTop: "1rem" }}>
            <h3 style={{marginBottom: "0.5rem", color: "#60a5fa"}}>⚖️ 去重与差异比对</h3>
            <input type="file" accept=".pdf" onChange={(e) => setDedupFile1(e.target.files?.[0] || null)} style={{ width: "100%", fontSize: "0.8rem", marginBottom: "0.5rem" }} />
            <input type="file" accept=".pdf" onChange={(e) => setDedupFile2(e.target.files?.[0] || null)} style={{ width: "100%", fontSize: "0.8rem", marginBottom: "0.5rem" }} />
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <button onClick={() => handleDedup("dedup")} style={{...styles.btnBlue, flex: 1, fontSize: "0.8rem"}}>开始检测</button>
              <button onClick={() => handleDedup("diff")} style={{...styles.btnPurple, flex: 1, fontSize: "0.8rem"}}>查看差异</button>
            </div>
            {dedupResult && <div style={styles.resultBox}>{dedupResult}</div>}
          </div>

          <div style={{ borderTop: "1px solid #334155", paddingTop: "1rem", flex: 1, display: "flex", flexDirection: "column" }}>
            <h3 style={{marginBottom: "0.5rem", color: "#60a5fa"}}>🕸️ 引用图谱与综述</h3>
            <div style={{ display: "flex", gap: "0.5rem", marginBottom: "0.5rem" }}>
              <button onClick={handleLoadGraph} style={{...styles.btnBlue, flex: 1, fontSize: "0.8rem"}}>{isGraphLoading ? "渲染中..." : "生成图谱"}</button>
              <button onClick={handleGenerateReview} style={{...styles.btnPurple, flex: 1, fontSize: "0.8rem"}}>生成领域综述</button>
            </div>
            
            <div style={{ height: "300px", borderRadius: "0.5rem", marginBottom: "0.5rem", border: "1px solid #334155", position: "relative", backgroundColor: "#0f172a", overflow: "hidden" }}>
              <div ref={chartDomRef} style={{ width: '100%', height: '100%', display: graphData.nodes.length > 0 ? 'block' : 'none' }} />
              {graphData.nodes.length === 0 && (
                <div style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0, display: "flex", alignItems: "center", justifyContent: "center", fontSize: "0.8rem", color: "#64748b" }}>
                  请先选中文献并点击生成图谱
                </div>
              )}
            </div>
            {reviewText && (<div style={{ maxHeight: "100px", overflowY: "auto", backgroundColor: "#0f172a", padding: "0.5rem", fontSize: "0.8rem", color: "#d1d5db", borderRadius: "0.5rem", whiteSpace: "pre-wrap" }}>{reviewText}</div>)}
          </div>
          
          <div style={{ flex: 1, display: "flex", flexDirection: "column", borderTop: "1px solid #334155", paddingTop: "1rem" }}>
            <h3 style={{marginBottom: "0.5rem", color: "#60a5fa"}}>🤖 RAG 问答</h3>
            <div style={{ flex: 1, backgroundColor: "#0f172a", borderRadius: "0.5rem", padding: "0.5rem", fontSize: "0.8rem", overflowY: "auto", marginBottom: "0.5rem" }}>
              {renderOutput()}
            </div>
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <input style={styles.inputBox} value={input} onChange={(e) => setInput(e.target.value)} placeholder="提问..." onKeyDown={(e) => e.key === 'Enter' && handleSend()} />
              <button onClick={handleSend} style={styles.btnBlue}>发</button>
            </div>
          </div>

          <div style={{ borderTop: "1px solid #334155", paddingTop: "1rem" }}>
            <h3 style={{marginBottom: "0.5rem", color: "#60a5fa"}}>🔍 arXiv 追踪</h3>
            <button onClick={async () => {
              const res = await fetch(`${API_BASE}/arxiv_search`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({query: "cs.CL"}) });
              const data = await res.json();
              setArxivPapers(data.data || []);
            }} style={{...styles.btnBlue, width: "100%", fontSize: "0.8rem"}}>获取最新论文</button>
            
            {arxivPapers.length > 0 && (
              <div style={{ marginTop: "0.5rem", maxHeight: "150px", overflowY: "auto", backgroundColor: "#0f172a", padding: "0.5rem", borderRadius: "0.5rem", fontSize: "0.75rem" }}>
                {arxivPapers.map((p, i) => (
                  <div key={i} style={{ marginBottom: "0.5rem", borderBottom: "1px dashed #334155", paddingBottom: "0.25rem" }}>
                    <div style={{ color: "#60a5fa", fontWeight: "bold" }}>{p.title}</div>
                    <div style={{ color: "#94a3b8", fontSize: "0.7rem" }}>{p.authors} | {p.published}</div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div style={{ borderTop: "1px solid #334155", paddingTop: "1rem" }}>
            <h3 style={{marginBottom: "0.5rem", color: "#60a5fa"}}>📊 数据与写作辅助</h3>
            
            <div style={{ marginBottom: "0.5rem" }}>
              <label style={{ fontSize: "0.8rem", color: "#cbd5e1", display: "block", marginBottom: "0.25rem" }}>上传 CSV 生成图表:</label>
              <input type="file" accept=".csv" onChange={async (e) => {
                const file = e.target.files?.[0];
                if(!file) return;
                setIsGeneratingChart(true); setCsvChart(null);
                const text = await file.text();
                try {
                  const res = await fetch(`${API_BASE}/csv_to_chart`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({csv_text: text}) });
                  const data = await res.json();
                  if(data.image_base64) setCsvChart({ image: data.image_base64, caption: data.caption });
                  else alert("失败: " + data.error);
                } catch (err) { alert("请求异常"); } finally { setIsGeneratingChart(false); }
              }} style={{ width: "100%", fontSize: "0.75rem", color: "#cbd5e1" }} />
            </div>

            {isGeneratingChart && <div style={{ fontSize: "0.75rem", color: "#4ade80" }}>正在生成图表与图注...</div>}
            {csvChart && (
              <div style={{ backgroundColor: "#0f172a", padding: "0.5rem", borderRadius: "0.5rem", marginBottom: "0.5rem" }}>
                <img src={`data:image/png;base64,${csvChart.image}`} alt="Chart" style={{ width: "100%", borderRadius: "0.25rem", marginBottom: "0.25rem" }} />
                <div style={{ fontSize: "0.7rem", color: "#cbd5e1", fontStyle: "italic" }}>Caption: {csvChart.caption}</div>
              </div>
            )}

            <div style={{ marginTop: "0.5rem" }}>
               <label style={{ fontSize: "0.8rem", color: "#cbd5e1", display: "block", marginBottom: "0.25rem" }}>输入 Idea 生成论文框架:</label>
               <textarea value={paperIdea} onChange={(e) => setPaperIdea(e.target.value)} placeholder="例如: 用多模态大模型结合 RAG 预测蛋白质结构..." style={{ ...styles.inputBox, width: "100%", height: "50px", marginBottom: "0.25rem", fontSize: "0.75rem", resize: "none" }} />
               <button onClick={async () => {
                 if(!paperIdea) return;
                 setIsGeneratingFramework(true); setPaperFramework("");
                 try {
                   const res = await fetch(`${API_BASE}/generate_framework`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({idea: paperIdea}) });
                   const data = await res.json();
                   setPaperFramework(data.framework || data.error);
                 } catch (err) { setPaperFramework("生成失败"); } finally { setIsGeneratingFramework(false); }
               }} disabled={isGeneratingFramework || !paperIdea} style={{ ...styles.btnPurple, width: "100%", fontSize: "0.8rem", opacity: (isGeneratingFramework || !paperIdea) ? 0.5 : 1 }}>
                 {isGeneratingFramework ? "生成中..." : "生成框架"}
               </button>
               
               {paperFramework && (
                 <div style={{ marginTop: "0.5rem", maxHeight: "150px", overflowY: "auto", backgroundColor: "#0f172a", padding: "0.5rem", borderRadius: "0.5rem", fontSize: "0.75rem", color: "#d1d5db", whiteSpace: "pre-wrap" }}>
                   {paperFramework}
                 </div>
               )}
            </div>
          </div>
        </div>

        <div style={styles.card}>
          <div style={{display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid #334155", paddingBottom: "0.5rem", marginBottom: "0.5rem"}}>
            <h3 style={{margin: 0, color: "#60a5fa"}}>📄 英文原文</h3>
            <button onClick={handleLoadEnglish} disabled={isLoadingEn || !hasRawText} style={{...styles.btnBlue, fontSize: "0.75rem", padding: "0.25rem 0.5rem", opacity: (isLoadingEn || !hasRawText) ? 0.5 : 1}}>
              {isLoadingEn ? "加载中..." : "显示原文"}
            </button>
          </div>
          <div ref={leftScrollRef} onScroll={(e) => handleScroll(e, 'left')} onMouseUp={handleMouseUp} style={styles.readerBox}>{renderedRawText}</div>
        </div>

        <div style={styles.card}>
          <div style={{display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid #334155", paddingBottom: "0.5rem", marginBottom: "0.5rem"}}>
            <h3 style={{margin: 0, color: "#60a5fa"}}>🇨🇳 中文对照</h3>
            <button onClick={handleFullTranslate} disabled={isTranslating || !hasRawText} style={{...styles.btnBlue, fontSize: "0.75rem", padding: "0.25rem 0.5rem", opacity: (isTranslating || !hasRawText) ? 0.5 : 1}}>
              {isTranslating ? "翻译中..." : "一键翻译"}
            </button>
          </div>
          <div ref={rightScrollRef} onScroll={(e) => handleScroll(e, 'right')} style={styles.readerBox}>{translatedText}</div>
        </div>
      </div>

      {popupPos.visible && (
        <div style={styles.popup} onMouseDown={(e) => e.stopPropagation()}>
          <div style={{display: "flex", gap: "0.5rem", borderBottom: "1px solid #475569", paddingBottom: "0.5rem"}}>
            <button onClick={() => handleTextAction("translate")} style={{...styles.btnBlue, flex: 1, fontSize: "0.8rem"}}>划词翻译</button>
            <button onClick={() => handleTextAction("rewrite")} style={{...styles.btnBlue, flex: 1, fontSize: "0.8rem", backgroundColor: "#9333ea"}}>学术重写</button>
            <button onClick={() => setPopupPos(prev => ({...prev, visible: false}))} style={{...styles.btnBlue, backgroundColor: "#dc2626", padding: "0.2rem 0.5rem"}}>X</button>
          </div>
          <div style={{ fontSize: "0.8rem", color: "#94a3b8", fontStyle: "italic", maxHeight: "50px", overflow: "hidden", textOverflow: "ellipsis" }}>"{selectedText.slice(0, 50)}{selectedText.length > 50 ? "..." : ""}"</div>
          {(popupResult || popupLoading) && (<div style={{ marginTop: "0.2rem", fontSize: "0.85rem", color: "#d1d5db", maxHeight: "150px", overflowY: "auto", borderTop: "1px solid #475569", paddingTop: "0.5rem" }}>{popupLoading ? "正在处理..." : popupResult}</div>)}
        </div>
      )}
    </div>
  );
}