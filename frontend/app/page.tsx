"use client";
import React, { useState, useRef, useMemo, useCallback, useEffect } from "react";
import * as echarts from "echarts";
import katex from "katex";
import { UI } from "./uiConstants";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

export default function Home() {
  const [input, setInput] = useState("");
  const [output, setOutput] = useState("");
  const [loading, setLoading] = useState(false);
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [dedupFile1, setDedupFile1] = useState<File | null>(null);
  const [dedupFile2, setDedupFile2] = useState<File | null>(null);
  const [dedupResult, setDedupResult] = useState<string>("");
  const [dbMessage, setDbMessage] = useState<string>("");
  const [docList, setDocList] = useState<{ id: string; name: string }[]>([]);
  const [activeDoc, setActiveDoc] = useState<string>("");
  const [selectedDocs, setSelectedDocs] = useState<string[]>([]);
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
  const [graphData, setGraphData] = useState<{ nodes: any[]; links: any[] }>({ nodes: [], links: [] });
  const [graphMessage, setGraphMessage] = useState<string>("");
  const [graphSummary, setGraphSummary] = useState<any>(null);
  const [isGraphLoading, setIsGraphLoading] = useState(false);
  const [reviewText, setReviewText] = useState<string>("");
  const [compareResult, setCompareResult] = useState<string>("");
  const [futureWork, setFutureWork] = useState<string>("");
  const [tocList, setTocList] = useState<{ level: number; title: string; page: number }[]>([]);

  const [agentMode, setAgentMode] = useState(false);
  const [agentSteps, setAgentSteps] = useState<any[]>([]);

  const [arxivPapers, setArxivPapers] = useState<any[]>([]);
  const [arxivQuery, setArxivQuery] = useState("transformer");
  const [arxivCategory, setArxivCategory] = useState("");
  const [arxivMax, setArxivMax] = useState(10);
  const [arxivStatus, setArxivStatus] = useState("");
  const [arxivOffline, setArxivOffline] = useState(false);
  const [arxivFeedback, setArxivFeedback] = useState<Record<string, { like: number; dislike: number }>>({});
  const [arxivDownloading, setArxivDownloading] = useState("");
  const [arxivCategories, setArxivCategories] = useState<string[]>([]);
  const [configLoaded, setConfigLoaded] = useState(false);
  const [pageMarkerPattern, setPageMarkerPattern] = useState<string>("\\[Page \\d+\\]");

  const [csvChart, setCsvChart] = useState<{
    image: string; caption: string; table: string; chartType: string;
  } | null>(null);
  const [chartType, setChartType] = useState("auto");
  const [paperIdea, setPaperIdea] = useState("");
  const [paperFramework, setPaperFramework] = useState("");
  const [frameworkRefs, setFrameworkRefs] = useState<string[]>([]);
  const [frameworkMermaid, setFrameworkMermaid] = useState("");
  const [frameworkTikz, setFrameworkTikz] = useState("");
  const [mermaidSvg, setMermaidSvg] = useState("");
  const [isGeneratingFramework, setIsGeneratingFramework] = useState(false);
  const [isGeneratingChart, setIsGeneratingChart] = useState(false);
  const [frameworkError, setFrameworkError] = useState("");

  const leftScrollRef = useRef<HTMLDivElement>(null);
  const rightScrollRef = useRef<HTMLDivElement>(null);
  const isSyncingRef = useRef(false);
  const chartDomRef = useRef<HTMLDivElement>(null);
  const highlightTimerRef = useRef<number | null>(null);
  const pageJumpTimerRef = useRef<number | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/list_docs`, { method: "POST" });
        const data = await res.json();
        if (data.status === "success" && Array.isArray(data.docs)) {
          setDocList(data.docs.map((d: any) => ({ id: d.name, name: d.name })));
        }
      } catch (e) { console.warn("恢复文献列表失败", e); }

      try {
        const cfgRes = await fetch(`${API_BASE}/config`);
        const cfg = await cfgRes.json();
        if (Array.isArray(cfg.arxiv_categories) && cfg.arxiv_categories.length > 0) {
          setArxivCategories(cfg.arxiv_categories);
          setArxivCategory(cfg.arxiv_default_category || cfg.arxiv_categories[0]);
        } else {
          setArxivCategories(["cs.CL"]);
          setArxivCategory("cs.CL");
        }
        if (typeof cfg.page_marker_pattern === "string" && cfg.page_marker_pattern.trim()) {
          setPageMarkerPattern(cfg.page_marker_pattern);
        }
        setConfigLoaded(true);
      } catch (e) {
        console.warn("加载配置失败", e);
        setArxivCategories(["cs.CL"]);
        setArxivCategory("cs.CL");
        setConfigLoaded(true);
      }
    })();
  }, []);

  const handleUploadToDB = async (files: File[] = [], force: boolean = false) => {
    const toUpload = files.length > 0 ? files : uploadFiles;
    if (toUpload.length === 0) return alert("请先选择至少一篇 PDF");

    const isBatch = toUpload.length > 1;
    setDbMessage(isBatch ? `批量解析 ${toUpload.length} 篇...` : (force ? "强制覆盖入库..." : "解析并检查重复..."));

    if (!isBatch) {
      setFullRawText(""); setDisplayedRawText(""); setTranslatedText("");
      setHasRawText(false); setIsLoadingEn(false); setIsTranslating(false);
      setGraphData({ nodes: [], links: [] }); setGraphMessage(""); setReviewText(""); setTocList([]);
    }

    try {
      const formData = new FormData();
      toUpload.forEach(file => formData.append("files", file));
      if (force) formData.append("force", "true");

      const res = await fetch(`${API_BASE}/upload_batch`, { method: "POST", body: formData });
      const data = await res.json();

      if (data.status === "all_failed") {
        const errorMsgs = data.results?.map((r: any) => r.message).join("；");
        setDbMessage(errorMsgs || "全部上传失败，请检查日志。");
        return;
      }

      const successResults = data.results.filter((r: any) => r.status === "success");
      const dupResults = data.results.filter((r: any) => r.status === "duplicate");

      setDocList(prev => {
        const newList = [...prev];
        successResults.forEach((r: any) => {
          if (!newList.find(d => d.name === r.filename)) newList.push({ id: r.filename, name: r.filename });
        });
        return newList;
      });

      const parts: string[] = [];
      const totalChunks = successResults.reduce((acc: number, r: any) => acc + (r.chunks || 0), 0);
      if (data.success_count > 0) parts.push(`✅ 成功 ${data.success_count} 篇（共 ${totalChunks} 个文本块）`);
      if (data.duplicate_count > 0) parts.push(`⚠️ 跳过重复 ${data.duplicate_count} 篇`);
      if (data.error_count > 0) parts.push(`❌ 失败 ${data.error_count} 篇`);
      setDbMessage(parts.join("；") || "无文件被处理");

      if (successResults.length > 0) {
        const last = successResults[successResults.length - 1];
        setActiveDoc(last.filename);
        setSelectedDocs([last.filename]);
        if (Array.isArray(last.toc)) setTocList(last.toc);
        if (last.text) {
          const cleanText = last.text.replace(/<span[^>]*>|<\/span>/g, "");
          setFullRawText(cleanText);
          setHasRawText(true);
          setDisplayedRawText("已就绪，点击【显示原文】开始阅读。");
        }
      }

      if (dupResults.length > 0) {
        const dupMsg = `以下 ${dupResults.length} 篇与已有文献相似：\n${dupResults.map((d: any) => {
          const hint = d.version_hint ? `\n     ↳ ${d.version_hint}` : "";
          return `· ${d.filename}（与《${d.existing}》相似 ${d.similarity}%）${hint}`;
        }).join("\n")}\n\n点"确定"覆盖，点"取消"保留现有版本。`;
        if (confirm(dupMsg)) {
          const dupFileNames = dupResults.map((d: any) => d.filename);
          const dupFiles = toUpload.filter(f => dupFileNames.includes(f.name));
          if (dupFiles.length > 0) {
            await handleUploadToDB(dupFiles, true);
            return;
          }
        }
      }

      setUploadFiles([]);
    } catch (error: any) {
      setDbMessage("请求异常：" + error.message);
    }
  };

  const handleDeleteDoc = async (e: React.MouseEvent, docName: string) => {
    e.stopPropagation();
    if (!confirm(`确定删除 ${docName}？`)) return;
    try {
      const formData = new FormData();
      formData.append("filename", docName);
      const res = await fetch(`${API_BASE}/delete_doc`, { method: "POST", body: formData });
      const data = await res.json();
      if (data.status === "success") {
        setDocList(prev => prev.filter(d => d.name !== docName));
        setSelectedDocs(prev => prev.filter(n => n !== docName));
        if (activeDoc === docName) {
          setActiveDoc(""); setHasRawText(false);
          setFullRawText(""); setDisplayedRawText(""); setTranslatedText("");
          setGraphData({ nodes: [], links: [] }); setReviewText("");
        }
      } else alert("删除失败：" + data.message);
    } catch (err: any) { alert("请求异常：" + err.message); }
  };

  const handleLoadEnglish = () => {
    if (!fullRawText || isLoadingEn) return;
    setIsLoadingEn(true); setDisplayedRawText("");
    const paragraphs = fullRawText.split(/\n+/).map(p => p.trim()).filter(p => p.length > 0);
    let idx = 0; const batch = 10;
    const next = () => {
      if (idx >= paragraphs.length) { setIsLoadingEn(false); return; }
      const chunk = paragraphs.slice(idx, idx + batch).join("\n\n");
      setDisplayedRawText(prev => prev + (prev ? "\n\n" : "") + chunk);
      idx += batch;
      setTimeout(next, 20);
    };
    next();
  };

  const handleFullTranslate = async () => {
    if (!fullRawText || isTranslating) return;
    setIsTranslating(true); setTranslatedText("正在翻译...\n\n");
    let cleaned = fullRawText;
    const lines = cleaned.split("\n").map(l => l.trim()).filter(l => l.length > 0);
    const originalTitle = lines.length > 0 ? lines[0] : "";
    if (originalTitle) cleaned = cleaned.replace(originalTitle, "");
    const refIdx = cleaned.search(/\n\s*References/i);
    if (refIdx > -1) cleaned = cleaned.substring(0, refIdx);
    cleaned = cleaned
      .replace(/《第 \d+ 页》：/g, "")   
      .replace(/Figure \d+:.*?(\n|$)/g, "")
      .replace(/Table \d+:.*?(\n|$)/g, "")
      .replace(/[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/g, "")
      .replace(/^[\d\s\.]+$/gm, "");

    const paragraphs = cleaned.split(/\n+/).map(p => p.trim()).filter(p => p.length > UI.MIN_TRANSLATE_PARAGRAPH_LEN);
    const chunkSize = UI.TRANSLATE_CHUNK_SIZE;
    const chunks = paragraphs.flatMap(p => p.length > chunkSize ? p.match(new RegExp(`.{1,${chunkSize}}`, "g")) || [p] : [p]);
    if (chunks.length === 0) { setIsTranslating(false); setTranslatedText("无可翻译内容"); return; }

    const results: string[] = new Array(chunks.length).fill("");
    let index = 0; const limit = UI.TRANSLATE_CONCURRENCY;
    const worker = async () => {
      while (index < chunks.length) {
        const cur = index++;
        try {
          const res = await fetch(`${API_BASE}/text_action`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text: chunks[cur], action: "translate" }),
          });
          const data = await res.json();
          results[cur] = (data.result || "").replace(/<\/?text>/g, "").trim();
        } catch { results[cur] = ""; }
        setTranslatedText(originalTitle + "\n\n" + results.filter(r => r !== "").join("\n\n"));
        await new Promise(r => setTimeout(r, 10));
      }
    };
    await Promise.all(Array(limit).fill(null).map(() => worker()));
    setIsTranslating(false);
  };

  const handleSend = async () => {
    if (!input) return;
    setLoading(true); setOutput(""); setAgentSteps([]);

    const isFrameworkIntent = /(框架|大纲|生成论文|写一篇论文|Abstract|生成架构)/i.test(input);

    if (isFrameworkIntent) {
      setAgentSteps([{ type: "thought", content: "🔍 智能路由：识别到生成框架意图，自动调用专属引擎..." }]);
      try {
        const ideaText = input.replace(/帮我|生成|一个|论文|框架|基于|本地|文献/g, "").trim() || input;
        
        const res = await fetch(`${API_BASE}/generate_framework`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ idea: ideaText, doc_filter: activeDoc }),
        });
        const data = await res.json();
        
        if (data.error) {
          setOutput("生成失败：" + data.error);
        } else {
          setPaperFramework(data.framework || "");
          setFrameworkRefs(data.references || []);
          setFrameworkMermaid(data.mermaid || "");
          setFrameworkTikz(data.tikz || "");
          setOutput("✅ 已成功生成论文框架！\n请查看左侧边栏下方的【数据与写作】面板获取完整内容及 Mermaid / TikZ 图表。");
          setAgentSteps(prev => [...prev, { type: "tool_result", tool: "generate_framework", result_preview: "生成成功" }]);
        }
      } catch (e: any) {
        setOutput("请求失败：" + e.message);
      } finally {
        setLoading(false);
      }
      return;
    }

    if (agentMode) {
      try {
        const res = await fetch(`${API_BASE}/agent`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message: input,
            doc_filter: activeDoc,
            doc_filters: selectedDocs.length > 0 ? selectedDocs : (activeDoc ? [activeDoc] : []),
          }),
        });
        const data = await res.json();
        setAgentSteps(data.steps || []);
        
        if (data.framework_payload) {
          setPaperFramework(data.framework_payload.framework || "");
          setFrameworkRefs(data.framework_payload.references || []);
          setFrameworkMermaid(data.framework_payload.mermaid || "");
          setFrameworkTikz(data.framework_payload.tikz || "");
          setOutput("✅ Agent 已成功生成论文框架！\n请查看左侧边栏下方的【数据与写作】面板获取完整内容及 Mermaid / TikZ 图表。");
        } else {
          setOutput(data.answer || data.error || "（Agent 无返回）");
        }
      } catch (e: any) {
        setOutput("Agent 请求失败：" + e.message);
      } finally {
        setLoading(false);
      }
      return;
    }

    try {
      const response = await fetch(`${API_BASE}/chat`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: input,
          doc_filter: activeDoc,
          doc_filters: selectedDocs.length > 0 ? selectedDocs : [],
        }),
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
            if (text) setOutput(prev => prev + text);
          }
        }
      }
    } catch {
      setOutput("请求失败，请检查后端服务。");
    } finally {
      setLoading(false);
    }
  };

  const handleDedup = async (action: "dedup" | "diff") => {
    if (!dedupFile1 || !dedupFile2) return alert("请选择两个 PDF");
    setDedupResult("解析比对中...");
    try {
      const f1 = new FormData(); f1.append("file", dedupFile1);
      const r1 = await fetch(`${API_BASE}/parse_only`, { method: "POST", body: f1 });
      const d1 = await r1.json();
      const f2 = new FormData(); f2.append("file", dedupFile2);
      const r2 = await fetch(`${API_BASE}/parse_only`, { method: "POST", body: f2 });
      const d2 = await r2.json();
      if (d1.status !== "success" || !d1.text) return setDedupResult("文件1解析失败");
      if (d2.status !== "success" || !d2.text) return setDedupResult("文件2解析失败");
      const req = new FormData();
      if (action === "dedup") {
        req.append("text1", d1.text); req.append("text2", d2.text);
        const r = await fetch(`${API_BASE}/dedup`, { method: "POST", body: req });
        const j = await r.json();
        setDedupResult(j.error ? `报错：${j.error}` : `相似度 ${j.similarity}% 。${j.message}`);
      } else {
        req.append("text_old", d1.text); req.append("text_new", d2.text);
        const r = await fetch(`${API_BASE}/diff`, { method: "POST", body: req });
        const j = await r.json();
        setDedupResult(j.error ? `报错：${j.error}` : `【差异总结】\n${j.diff_summary}`);
      }
    } catch (error: any) {
      setDedupResult("请求异常：" + error.message);
    }
  };

  const handleMouseUp = (e: React.MouseEvent) => {
    const selection = window.getSelection();
    const text = selection?.toString().trim();
    if (text && text.length > UI.MIN_SELECTION_LEN) {
      const pw = UI.POPUP_WIDTH, ph = UI.POPUP_HEIGHT;
      let x = e.clientX;
      let y = e.clientY + 15;
      if (x + pw > window.innerWidth) x = window.innerWidth - pw - UI.POPUP_EDGE_MARGIN;
      if (y + ph > window.innerHeight) y = e.clientY - ph - 15;
      setSelectedText(text);
      setPopupPos({ x, y, visible: true });
      setPopupResult("");
    } else {
      setPopupPos(prev => ({ ...prev, visible: false }));
    }
  };

  const handleTextAction = async (action: "translate" | "rewrite" | "academic_en") => {
    if (!selectedText) return;
    setPopupLoading(true); setPopupResult("");
    try {
      const res = await fetch(`${API_BASE}/text_action`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: selectedText, action }),
      });
      const data = await res.json();
      setPopupResult((data.result || data.error || "").replace(/<\/?text>/g, "").trim());
    } catch {
      setPopupResult("请求失败");
    } finally {
      setPopupLoading(false);
    }
  };

  const handleScroll = useCallback((e: React.UIEvent<HTMLDivElement>, direction: "left" | "right") => {
    if (isSyncingRef.current) return;
    const source = e.currentTarget;
    const target = direction === "left" ? rightScrollRef.current : leftScrollRef.current;
    if (!target) return;
    const denom = source.scrollHeight - source.clientHeight;
    if (denom <= 0) return;
    isSyncingRef.current = true;
    const pct = source.scrollTop / denom;
    target.scrollTop = pct * (target.scrollHeight - target.clientHeight);
    requestAnimationFrame(() => { isSyncingRef.current = false; });
  }, []);

  const handleLoadGraph = async () => {
    const target = selectedDocs.length > 0 ? selectedDocs : (activeDoc ? [activeDoc] : []);
    if (target.length === 0) return alert("请选择文献");
    setIsGraphLoading(true); setGraphMessage(""); setGraphSummary(null);
    try {
      const res = await fetch(`${API_BASE}/graph`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ doc_filter: activeDoc, doc_filters: target }),
      });
      const data = await res.json();
      setGraphData({ nodes: data.nodes || [], links: data.links || [] });
      setGraphSummary(data.summary || null);
      if (data.message && data.message !== "ok") setGraphMessage(data.message);
      else if (!data.nodes || data.nodes.length === 0) setGraphMessage("未返回图谱节点");
    } catch {
      setGraphMessage("请求图谱接口失败");
    } finally {
      setIsGraphLoading(false);
    }
  };

  const handleGenerateReview = async () => {
    if (!activeDoc) return alert("请选中文献");
    setReviewText("正在生成综述...");
    try {
      const res = await fetch(`${API_BASE}/generate_review`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic: activeDoc }),
      });
      const data = await res.json();
      setReviewText(data.review || data.error);
    } catch {
      setReviewText("生成失败");
    }
  };

  const handleCompare = async () => {
    const target = selectedDocs.length > 0 ? selectedDocs : (activeDoc ? [activeDoc] : []);
    if (target.length < 2) return alert("请按住 Ctrl 多选至少 2 篇");
    setCompareResult("对比中...");
    try {
      const res = await fetch(`${API_BASE}/compare`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ doc_names: target }),
      });
      const data = await res.json();
      setCompareResult(data.compare || data.error || "无结果");
    } catch (e: any) {
      setCompareResult("对比失败：" + e.message);
    }
  };

  const handleFutureWork = async () => {
    const target = selectedDocs.length > 0 ? selectedDocs : (activeDoc ? [activeDoc] : []);
    if (target.length === 0) return alert("请选中文献");
    setFutureWork("正在提取未来方向...");
    try {
      const res = await fetch(`${API_BASE}/future_work`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ doc_filter: activeDoc, doc_filters: target }),
      });
      const data = await res.json();
      setFutureWork(data.future_work || data.error || "无结果");
    } catch (e: any) {
      setFutureWork("提取失败：" + e.message);
    }
  };

  const handleArxivSearch = async () => {
    setArxivStatus("正在获取...");
    setArxivOffline(false);
    try {
      const res = await fetch(`${API_BASE}/arxiv_search`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: arxivQuery, category: arxivCategory, max_results: arxivMax }),
      });
      const data = await res.json();
      if (data.status === "success") {
        setArxivPapers(data.data || []);
        setArxivOffline(!!data.offline);
        setArxivStatus(`已获取 ${data.count} 篇${data.offline ? "（离线兜底）" : ""}`);
      } else {
        setArxivStatus("获取失败：" + (data.message || "未知错误"));
      }
    } catch (err: any) {
      setArxivStatus("请求异常：" + err.message);
    }
  };

  const handleArxivFeedback = async (paper: any, action: "like" | "dislike") => {
    const key = paper.arxiv_url || paper.title;
    try {
      const res = await fetch(`${API_BASE}/arxiv_feedback`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ arxiv_url: paper.arxiv_url, title: paper.title, action }),
      });
      const data = await res.json();
      if (data.status === "success") {
        setArxivFeedback(prev => ({ ...prev, [key]: { like: data.record.like, dislike: data.record.dislike } }));
      }
    } catch { /* ignore */ }
  };

  const handleArxivDownload = async (paper: any) => {
    if (!paper.arxiv_url) return alert("该论文无 arXiv 链接");
    const key = paper.arxiv_url || paper.title;
    setArxivDownloading(key);
    try {
      const fd = new FormData();
      fd.append("arxiv_url", paper.arxiv_url);
      const res = await fetch(`${API_BASE}/arxiv_download`, { method: "POST", body: fd });
      const data = await res.json();
      if (data.status === "success") {
        setDocList(prev => prev.find(d => d.name === data.filename)
          ? prev : [...prev, { id: data.filename, name: data.filename }]);
        setActiveDoc(data.filename);
        setSelectedDocs([data.filename]);
        alert(`✅ 已入库：${data.filename}\n${data.message}`);
      } else {
        alert("下载失败：" + (data.error || "未知错误"));
      }
    } catch (e: any) {
      alert("请求异常：" + e.message);
    } finally {
      setArxivDownloading("");
    }
  };

  const handleCsvUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const inputEl = e.target;
    const file = inputEl.files?.[0];
    if (!file) return;
    inputEl.value = "";
    setIsGeneratingChart(true); setCsvChart(null);
    const text = await file.text();
    try {
      const res = await fetch(`${API_BASE}/csv_to_chart`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ csv_text: text, chart_type: chartType }),
      });
      const data = await res.json();
      if (data.error) alert("失败: " + data.error);
      else setCsvChart({
        image: data.image_base64 || "",
        caption: data.caption || "",
        table: data.table_markdown || "",
        chartType: data.chart_type || "",
      });
    } catch {
      alert("请求异常");
    } finally {
      setIsGeneratingChart(false);
    }
  };

  const handleGenerateFramework = async () => {
    if (!paperIdea) return;
    setIsGeneratingFramework(true);
    setPaperFramework(""); setFrameworkRefs([]); setFrameworkMermaid(""); setFrameworkTikz(""); setFrameworkError("");
    try {
      const res = await fetch(`${API_BASE}/generate_framework`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ idea: paperIdea, doc_filter: activeDoc }),
      });
      const data = await res.json();
      if (data.error) {
        setFrameworkError(data.error);
      } else {
        setPaperFramework(data.framework || "");
        setFrameworkRefs(data.references || []);
        setFrameworkMermaid(data.mermaid || "");
        setFrameworkTikz(data.tikz || "");
      }
    } catch (err: any) {
      setFrameworkError("请求异常：" + err.message);
    } finally {
      setIsGeneratingFramework(false);
    }
  };

  useEffect(() => {
    if (!chartDomRef.current || graphData.nodes.length === 0) return;
    let myChart = echarts.getInstanceByDom(chartDomRef.current);
    if (myChart) myChart.dispose();
    myChart = echarts.init(chartDomRef.current);

    const safeNum = (v: any, fallback: number) => {
      const n = Number(v);
      return Number.isFinite(n) ? n : fallback;
    };

    const roleColor = (role: string) =>
      role === "pillar" ? "#fbbf24"
      : role === "user_paper" ? "#60a5fa"
      : "#64748b";

    const nodes = graphData.nodes.map((n: any) => ({
      id: n.name,
      name: n.name,
      symbolSize: Math.max(14, Math.min(50, safeNum(n.symbolSize, 20))),
      itemStyle: { color: roleColor(n.role) },
      label: {
        show: true,
        fontSize: 9,
        color: "#cbd5e1",
        formatter: (p: any) =>
          p.name.length > 12 ? p.name.slice(0, 12) + "…" : p.name,
      },
      category: n.role === "pillar" ? 0 : n.role === "user_paper" ? 1 : 2,
    }));

    const links = graphData.links.map((l: any) => ({
      source: l.source,
      target: l.target,
      lineStyle: { color: "#334155", width: 1, curveness: 0.15, opacity: 0.7 },
    }));

    const option = {
      backgroundColor: "transparent",
      tooltip: {
        trigger: "item",
        backgroundColor: "#1e293b",
        borderColor: "#3b82f6",
        textStyle: { color: "#fff", fontSize: 11 },
        confine: true,
        extraCssText: "max-width: 280px; white-space: normal; word-break: break-all; z-index: 999;",
        formatter: (p: any) => {
          if (p.dataType === "edge") return `${p.data.source} → ${p.data.target}`;
          const roleText = p.data.category === 0 ? "基石论文"
            : p.data.category === 1 ? "本地论文" : "边缘论文";
          return `<b>${p.name}</b><br/>角色：${roleText}`;
        },
      },
      legend: [{
        data: ["基石论文", "本地论文", "边缘论文"],
        textStyle: { color: "#cbd5e1", fontSize: 10 },
        bottom: 0,
        itemWidth: 10,
        itemHeight: 10,
      }],
      series: [{
        type: "graph",
        layout: "force",
        roam: true,
        draggable: true,
        categories: [
          { name: "基石论文", itemStyle: { color: "#fbbf24" } },
          { name: "本地论文", itemStyle: { color: "#60a5fa" } },
          { name: "边缘论文", itemStyle: { color: "#64748b" } },
        ],
        force: {
          repulsion: 180,
          edgeLength: [60, 120],
          gravity: 0.08,
          layoutAnimation: true,
        },
        data: nodes,
        links: links,
        lineStyle: { color: "#334155", width: 1, curveness: 0.15, opacity: 0.7 },
        label: { show: true, position: "right", fontSize: 9, color: "#cbd5e1" },
        emphasis: {
          focus: "adjacency",
          lineStyle: { width: 2, color: "#60a5fa" },
          label: { fontSize: 11, color: "#fff" },
        },
      }],
    };
    myChart.setOption(option);

    const onResize = () => myChart.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      myChart.dispose();
    };
  }, [graphData]);

  useEffect(() => {
    let cancelled = false;
    if (!frameworkMermaid) { setMermaidSvg(""); return; }
    (async () => {
      try {
        const mermaid = (await import("mermaid")).default;
        mermaid.initialize({ startOnLoad: false, theme: "dark", securityLevel: "strict" });
        const id = `m-${Date.now()}-${Math.random().toString(36).slice(2)}`;
        const result: any = await mermaid.render(id, frameworkMermaid);
        const svg = typeof result === "string" ? result : result.svg;
        if (!cancelled) setMermaidSvg(svg);
      } catch {
        if (!cancelled) setMermaidSvg("");
      }
    })();
    return () => { cancelled = true; };
  }, [frameworkMermaid]);

  const exportFramework = () => {
    const refsText = frameworkRefs.length
      ? frameworkRefs.map((r, i) => `[${i + 1}] ${r}`).join("\n")
      : "本地知识库暂无相关文献，未生成引用。";
    const md = `${paperFramework}\n\n## References\n${refsText}\n\n\`\`\`mermaid\n${frameworkMermaid}\n\`\`\`\n${frameworkTikz ? `\n\`\`\`latex\n${frameworkTikz}\n\`\`\`\n` : ""}`;
    const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "paper_framework.md"; a.click();
    URL.revokeObjectURL(url);
  };

  const renderOutput = () => {
    if (!output) return "💡 请输入指令，或点击左侧功能按钮开始探索...";
    let re: RegExp;
    try { re = new RegExp(pageMarkerPattern, "g"); } catch { re = /\[Page \d+\]/g; }
    const matches = output.match(re) || [];
    let cleanOutput = output;
    if (matches.length > 1) {
      const marker = matches[0]?.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      cleanOutput = output.replace(new RegExp(`(${marker})\\s*(?=${marker})`, "g"), "");
    }
    const mathRegex = /(\$\$[\s\S]+?\$\$|\$[^\$\n]+?\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\))/g;
    const segs = cleanOutput.split(mathRegex);
    
    const renderTextWithLineBreaks = (text: string) => {
      const formattedText = text
        .replace(/([一二三四五六七八九十]+、)/g, "\n\n$1")
        .replace(/(\d+\.\s*[^\d\n]+)/g, "\n$1")
        .replace(/(\d+\.\d+\s*[^\d\n]+)/g, "\n$1");
        
      return formattedText.split("\n").map((line, li, arr) => (
        <React.Fragment key={li}>
          {line}
          {li < arr.length - 1 && <br />}
        </React.Fragment>
      ));
    };

    return segs.map((seg, i) => {
      if (seg.startsWith("$$") && seg.endsWith("$$")) {
        try {
          const html = katex.renderToString(seg.slice(2, -2), { displayMode: true, throwOnError: false });
          return <div key={`m-${i}`} style={{ textAlign: "center", margin: "0.4rem 0" }} dangerouslySetInnerHTML={{ __html: html }} />;
        } catch { /* fallthrough */ }
      }
      if (seg.startsWith("$") && seg.endsWith("$") && seg.length > 2) {
        try {
          const html = katex.renderToString(seg.slice(1, -1), { displayMode: false, throwOnError: false });
          return <span key={`m-${i}`} dangerouslySetInnerHTML={{ __html: html }} />;
        } catch { /* fallthrough */ }
      }
      if (seg.startsWith("\\[") && seg.endsWith("\\]")) {
        try {
          const html = katex.renderToString(seg.slice(2, -2), { displayMode: true, throwOnError: false });
          return <div key={`m-${i}`} style={{ textAlign: "center", margin: "0.4rem 0" }} dangerouslySetInnerHTML={{ __html: html }} />;
        } catch { /* fallthrough */ }
      }
      if (seg.startsWith("\\(") && seg.endsWith("\\)")) {
        try {
          const html = katex.renderToString(seg.slice(2, -2), { displayMode: false, throwOnError: false });
          return <span key={`m-${i}`} dangerouslySetInnerHTML={{ __html: html }} />;
        } catch { /* fallthrough */ }
      }
      const parts = seg.split(new RegExp(`(${pageMarkerPattern})`, "g"));
      return (
        <span key={`t-${i}`}>
          {parts.map((part, j) => {
            if (new RegExp(`^${pageMarkerPattern}$`).test(part)) {
              const pageNum = (part.match(/\d+/) || [""])[0];

              return (
                <span
                  key={`p-${i}-${j}`}
                  onClick={() => {
                    if (!leftScrollRef.current || !pageNum) return;
                    if (highlightTimerRef.current) {
                      clearTimeout(highlightTimerRef.current);
                      highlightTimerRef.current = null;
                    }
                    if (pageJumpTimerRef.current) {
                      clearTimeout(pageJumpTimerRef.current);
                      pageJumpTimerRef.current = null;
                    }
                    const findTarget = (): Element | undefined => {
                      if (!leftScrollRef.current) return undefined;
                      return leftScrollRef.current.querySelector(`[data-page-anchor="${pageNum}"]`) || undefined;
                    };

                    const highlightAndScroll = (el: Element) => {
                      const node = el as HTMLElement;
                      leftScrollRef.current?.querySelectorAll("span[data-page-anchor]").forEach((s: any) => {
                        s.style.backgroundColor = "rgba(96, 165, 250, 0.15)";
                        s.style.color = "#60a5fa";
                        s.style.borderColor = "rgba(96, 165, 250, 0.3)";
                      });

                      node.scrollIntoView({ behavior: "smooth", block: "center" });
                      node.style.backgroundColor = "#2563eb";
                      node.style.color = "#fff";
                      node.style.borderColor = "#2563eb";

                      highlightTimerRef.current = window.setTimeout(() => {
                        node.style.backgroundColor = "rgba(96, 165, 250, 0.15)";
                        node.style.color = "#60a5fa";
                        node.style.borderColor = "rgba(96, 165, 250, 0.3)";
                        highlightTimerRef.current = null;
                      }, 3000);
                    };

                    const tryScroll = (attempt: number) => {
                      if (!leftScrollRef.current) return;
                      const t = findTarget();
                      if (t) {
                        highlightAndScroll(t);
                        pageJumpTimerRef.current = null;
                        return;
                      }
                      if (attempt >= 30) {
                        alert(`未找到第 ${pageNum} 页，请确认该页存在于当前文献。`);
                        pageJumpTimerRef.current = null;
                        return;
                      }
                      pageJumpTimerRef.current = window.setTimeout(() => tryScroll(attempt + 1), 100);
                    };

                    const immediate = findTarget();
                    if (immediate) {
                      highlightAndScroll(immediate);
                      return;
                    }

                    if (fullRawText.includes(`《第 ${pageNum} 页》`)) {
                      setDisplayedRawText(fullRawText);
                      tryScroll(0);
                      return;
                    }

                    alert(`当前文献尚未加载全文，请先点击右上角【显示原文】。`);
                  }}
                  style={{
                    color: "#fff", backgroundColor: "#3b82f6", padding: "2px 8px",
                    borderRadius: "6px", margin: "0 4px", fontWeight: "bold",
                    cursor: "pointer", display: "inline-block", transition: "all 0.2s", boxShadow: "0 2px 4px rgba(59, 130, 246, 0.3)"
                  }}
                  title={`点击跳转到第 ${pageNum} 页`}
                >
                  {part}
                </span>
              );
            }
            return <span key={`p-${i}-${j}`}>{renderTextWithLineBreaks(part)}</span>;
          })}
        </span>
      );
    });
  };

  const renderedRawText = useMemo(() => {
    const cleanText = displayedRawText.replace(/<span[^>]*>|<\/span>/g, "");
    const refMatch = cleanText.search(UI.REFERENCES_DETECT_REGEX);
    const refStart = refMatch > -1 ? refMatch : 0;

    const splitRegex = /(\$\$[\s\S]+?\$\$|\$[^\$\n]+?\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)|《第 \d+ 页》：?|\[\d+\])/g;
    const parts = cleanText.split(splitRegex);

    let cursor = 0;
    const partsWithOffset = parts.map(part => {
      const start = cursor;
      cursor += part.length;
      return { part, start };
    });

    return partsWithOffset.map(({ part, start }, i) => {
      if (part.match(/^《第 \d+ 页》：?$/)) {
        const pageNum = (part.match(/\d+/) || [""])[0];
        return (
          <span
            key={`page-marker-${i}`}
            data-page-anchor={pageNum}
            style={{
              display: "inline-block",
              fontSize: "0.75rem",
              color: "#60a5fa",
              backgroundColor: "rgba(96, 165, 250, 0.15)",
              border: "1px solid rgba(96, 165, 250, 0.3)",
              padding: "0px 6px",
              borderRadius: "4px",
              margin: "8px 4px 8px 0",
              verticalAlign: "middle",
              userSelect: "none",
              fontWeight: "bold",
            }}
          >
            {`第 ${pageNum} 页`}
          </span>
        );
      }

      if (part.match(/^\[\d+\]$/)) {
        const refId = part.replace(/[\[\]]/g, "");
        const isInRefSection = refStart > 0 && start >= refStart;

        return (
          <span
            key={`ref-${i}`}
            data-offset={start}
            style={{
              color: "#60a5fa", cursor: "pointer", fontWeight: "bold",
              backgroundColor: "rgba(59, 130, 246, 0.1)", padding: "0 2px", borderRadius: "4px",
            }}
            onClick={(e) => {
              e.stopPropagation();
              if (!leftScrollRef.current) return;

              leftScrollRef.current.querySelectorAll("span[data-offset]").forEach((s: any) => {
                s.style.backgroundColor = "";
                s.style.color = "";
                s.style.borderLeft = "";
                s.style.paddingLeft = "";
              });

              if (highlightTimerRef.current) {
                clearTimeout(highlightTimerRef.current);
                highlightTimerRef.current = null;
              }

              let target: HTMLElement | null = null;
              const regex = new RegExp(`\\[${refId}\\]`);
              const allSpans = Array.from(leftScrollRef.current.querySelectorAll("span[data-offset]"));

              if (isInRefSection) {
                for (let k = 0; k < allSpans.length; k++) {
                  const node = allSpans[k] as HTMLElement;
                  const off = parseInt(node.getAttribute("data-offset") || "-1", 10);
                  if (off >= 0 && off < refStart && regex.test(node.textContent || "")) {
                    target = node;
                    break;
                  }
                }
              } else {
                for (let k = allSpans.length - 1; k >= 0; k--) {
                  const node = allSpans[k] as HTMLElement;
                  const off = parseInt(node.getAttribute("data-offset") || "-1", 10);
                  if (off >= refStart && off >= 0 && regex.test(node.textContent || "")) {
                    target = node;
                    break;
                  }
                }
              }

              if (target) {
                isSyncingRef.current = true;
                target.scrollIntoView({ behavior: "smooth", block: "center" });
                target.style.transition = "all 0.3s";
                target.style.backgroundColor = "#2563eb";
                target.style.color = "white";
                target.style.borderLeft = "4px solid #60a5fa";
                target.style.paddingLeft = "4px";

                highlightTimerRef.current = window.setTimeout(() => {
                  if (target) {
                    target.style.backgroundColor = "";
                    target.style.color = "";
                    target.style.borderLeft = "";
                    target.style.paddingLeft = "";
                    isSyncingRef.current = false;
                  }
                  highlightTimerRef.current = null;
                }, 3000);
              } else {
                alert(isInRefSection
                  ? `正文中未找到 [${refId}] 的引用位置。`
                  : `References 中未找到 [${refId}]，请先点击【显示原文】加载全文。`);
              }
            }}
          >{part}</span>
        );
      }

      if (part.startsWith("$$") && part.endsWith("$$") && part.length > 4) {
        try {
          const html = katex.renderToString(part.slice(2, -2), { displayMode: true, throwOnError: false });
          return (
            <div
              key={`m-${i}`}
              style={{ textAlign: "center", margin: "0.6rem 0", overflowX: "auto" }}
              dangerouslySetInnerHTML={{ __html: html }}
            />
          );
        } catch { /* 降级为原文 */ }
      }

      if (part.startsWith("$") && part.endsWith("$") && part.length > 2) {
        try {
          const html = katex.renderToString(part.slice(1, -1), { displayMode: false, throwOnError: false });
          return <span key={`m-${i}`} dangerouslySetInnerHTML={{ __html: html }} />;
        } catch { /* 降级为原文 */ }
      }

      if (part.startsWith("\\[") && part.endsWith("\\]")) {
        try {
          const html = katex.renderToString(part.slice(2, -2), { displayMode: true, throwOnError: false });
          return (
            <div
              key={`m-${i}`}
              style={{ textAlign: "center", margin: "0.6rem 0", overflowX: "auto" }}
              dangerouslySetInnerHTML={{ __html: html }}
            />
          );
        } catch { /* 降级为原文 */ }
      }

      if (part.startsWith("\\(") && part.endsWith("\\)")) {
        try {
          const html = katex.renderToString(part.slice(2, -2), { displayMode: false, throwOnError: false });
          return <span key={`m-${i}`} dangerouslySetInnerHTML={{ __html: html }} />;
        } catch { /* 降级为原文 */ }
      }

      return <span key={`t-${i}`}>{part}</span>;
    });
  }, [displayedRawText]);

  useEffect(() => {
    const close = () => setPopupPos(prev => ({ ...prev, visible: false }));
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
  }, []);

  useEffect(() => {
    return () => {
      if (highlightTimerRef.current) {
        clearTimeout(highlightTimerRef.current);
        highlightTimerRef.current = null;
      }
      if (pageJumpTimerRef.current) {
        clearTimeout(pageJumpTimerRef.current);
        pageJumpTimerRef.current = null;
      }
    };
  }, []);

  const styles: Record<string, React.CSSProperties> = {
    container: { minHeight: "100vh", background: "radial-gradient(circle at 50% 0%, #1e293b 0%, #0f172a 60%)", color: "#f1f5f9", padding: "1rem", fontFamily: "system-ui, -apple-system, sans-serif" },
    header: { fontSize: "1.6rem", fontWeight: "bold", textAlign: "center", color: "#60a5fa", marginBottom: "1rem", letterSpacing: "1px", textShadow: "0 0 20px rgba(96, 165, 250, 0.4)" },
    grid: { display: "grid", gridTemplateColumns: "380px 1fr 1fr", gap: "1rem", height: "calc(100vh - 80px)" },
    sidebar: { backgroundColor: "rgba(30, 41, 59, 0.7)", backdropFilter: "blur(12px)", padding: "1rem", borderRadius: "1rem", display: "flex", flexDirection: "column", gap: "1rem", overflowY: "auto", border: "1px solid rgba(71, 85, 105, 0.5)", boxShadow: "0 8px 32px 0 rgba(0, 0, 0, 0.37)" },
    card: { backgroundColor: "rgba(30, 41, 59, 0.7)", backdropFilter: "blur(12px)", padding: "1rem", borderRadius: "1rem", border: "1px solid rgba(71, 85, 105, 0.5)", display: "flex", flexDirection: "column", overflow: "hidden", boxShadow: "0 8px 32px 0 rgba(0, 0, 0, 0.37)" },
    readerBox: { flex: 1, overflowY: "auto", backgroundColor: "#0b1120", padding: "1.2rem", borderRadius: "0.75rem", whiteSpace: "pre-wrap", fontSize: "0.95rem", lineHeight: "1.7", fontFamily: "Georgia, serif", border: "1px solid #1e293b", boxShadow: "inset 0 2px 10px rgba(0,0,0,0.5)" },
    inputBox: { flex: 1, backgroundColor: "rgba(15, 23, 42, 0.6)", border: "1px solid #475569", padding: "0.5rem 0.8rem", borderRadius: "0.5rem", color: "white", outline: "none", transition: "all 0.2s" },
    btnBlue: { backgroundColor: "#3b82f6", color: "white", padding: "0.5rem 1rem", borderRadius: "0.5rem", fontWeight: "bold", border: "none", cursor: "pointer", boxShadow: "0 2px 8px rgba(59, 130, 246, 0.4)" },
    btnGreen: { backgroundColor: "#10b981", color: "white", padding: "0.5rem 1rem", borderRadius: "0.5rem", fontWeight: "bold", border: "none", cursor: "pointer", boxShadow: "0 2px 8px rgba(16, 185, 129, 0.4)" },
    btnPurple: { backgroundColor: "#8b5cf6", color: "white", padding: "0.5rem 1rem", borderRadius: "0.5rem", fontWeight: "bold", border: "none", cursor: "pointer", boxShadow: "0 2px 8px rgba(139, 92, 246, 0.4)" },
    popup: { position: "absolute", top: popupPos.y, left: popupPos.x, backgroundColor: "rgba(30, 41, 59, 0.95)", backdropFilter: "blur(16px)", border: "1px solid #3b82f6", borderRadius: "0.75rem", padding: "0.75rem", zIndex: 1000, boxShadow: "0 12px 40px rgba(0,0,0,0.8)", display: "flex", flexDirection: "column", gap: "0.5rem", width: `${UI.POPUP_WIDTH}px` },
    resultBox: { backgroundColor: "rgba(2, 6, 23, 0.5)", padding: "0.6rem", borderRadius: "0.5rem", color: "#34d399", fontFamily: "monospace", border: "1px solid #059669", marginTop: "0.5rem", fontSize: "0.8rem", whiteSpace: "pre-wrap" },
  };

  return (
    <div style={styles.container}>
      <style>{`
        ::-webkit-scrollbar { width: 8px; height: 8px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #334155; border-radius: 4px; border: 2px solid transparent; background-clip: padding-box; }
        ::-webkit-scrollbar-thumb:hover { background-color: #475569; }
        ::selection { background-color: rgba(59, 130, 246, 0.4); color: #ffffff; }
        
        /* 全局按钮微交互 */
        button { transition: all 0.2s ease-in-out !important; }
        button:hover:not(:disabled) { filter: brightness(1.15); transform: translateY(-1px); box-shadow: 0 4px 12px rgba(0,0,0,0.3); }
        button:active:not(:disabled) { transform: translateY(1px); filter: brightness(0.9); }
        
        /* 输入框聚焦发光 */
        input:focus, textarea:focus, select:focus { border-color: #60a5fa !important; box-shadow: 0 0 0 3px rgba(96, 165, 250, 0.2) !important; outline: none !important; }
        
        /* 链接和可点击元素微交互 */
        a { transition: all 0.2s; }
        a:hover { filter: brightness(1.2); }
      `}</style>

      <h1 style={styles.header}>PaperPilot 沉浸式科研阅读器</h1>
      <div style={styles.grid}>
        <div style={styles.sidebar}>
          {tocList.length > 0 && (
            <div style={{ borderBottom: "1px solid #334155", paddingBottom: "1rem" }}>
              <h3 style={{ marginBottom: "0.5rem", color: "#60a5fa", display: "flex", alignItems: "center", gap: "0.5rem" }}>
                📑 章节导航
                <span style={{ fontSize: "0.65rem", color: "#94a3b8", fontWeight: "normal", backgroundColor: "#1e293b", padding: "2px 6px", borderRadius: "4px" }}>
                  {tocList.length} 节
                </span>
              </h3>
              <div style={{ maxHeight: "200px", overflowY: "auto", backgroundColor: "rgba(15, 23, 42, 0.6)", borderRadius: "0.5rem", padding: "0.4rem", border: "1px solid #1e293b" }}>
                {tocList.slice(0, 60).map((t, i) => {
                  const isL1 = t.level === 1;
                  const isL2 = t.level === 2;
                  return (
                    <div
                      key={i}
                      onClick={() => {
                        if (!leftScrollRef.current) return;
                        const target = leftScrollRef.current.querySelector(`[data-page-anchor="${t.page}"]`);
                        if (target) {
                          (target as HTMLElement).scrollIntoView({ behavior: "smooth", block: "center" });
                          (target as HTMLElement).style.backgroundColor = "#2563eb";
                          (target as HTMLElement).style.color = "#fff";
                          (target as HTMLElement).style.borderColor = "#2563eb";
                          setTimeout(() => {
                            if (target) {
                              (target as HTMLElement).style.backgroundColor = "rgba(96, 165, 250, 0.15)";
                              (target as HTMLElement).style.color = "#60a5fa";
                              (target as HTMLElement).style.borderColor = "rgba(96, 165, 250, 0.3)";
                            }
                          }, 2000);
                        }
                      }}
                      style={{
                        paddingLeft: isL1 ? "0.4rem" : isL2 ? "1.2rem" : "2.2rem",
                        padding: "0.3rem 0.4rem",
                        fontSize: isL1 ? "0.8rem" : "0.75rem",
                        fontWeight: isL1 ? "bold" : "normal",
                        color: isL1 ? "#93c5fd" : isL2 ? "#cbd5e1" : "#94a3b8",
                        cursor: "pointer",
                        borderRadius: "0.3rem",
                        borderLeft: isL1 ? "3px solid #3b82f6" : "none",
                        marginBottom: "0.1rem",
                        transition: "all 0.2s"
                      }}
                      onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.backgroundColor = "rgba(51, 65, 85, 0.8)"; }}
                      onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.backgroundColor = "transparent"; }}
                    >
                      {isL1 ? "▪ " : isL2 ? "▫ " : "· "}
                      {t.title}
                      <span style={{ color: "#475569", fontSize: "0.65rem", marginLeft: "0.3rem" }}>p.{t.page}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          <div>
            <h3 style={{ marginBottom: "0.5rem", color: "#60a5fa" }}>
              📚 文献库 <span style={{ fontSize: "0.65rem", color: "#94a3b8", fontWeight: "normal" }}>(Ctrl 多选)</span>
            </h3>
            {docList.length === 0 ? (
              <p style={{ fontSize: "0.8rem", color: "#64748b" }}>暂无文献，请上传</p>
            ) : docList.map((doc, i) => (
              <div
                key={i}
                onClick={(e: React.MouseEvent) => {
                  if (e.ctrlKey || e.metaKey) {
                    setSelectedDocs(prev => prev.includes(doc.name)
                      ? prev.filter(n => n !== doc.name) : [...prev, doc.name]);
                  } else {
                    setActiveDoc(prev => prev === doc.name ? "" : doc.name);
                    setSelectedDocs([doc.name]);
                  }
                }}
                style={{
                  display: "flex", justifyContent: "space-between", alignItems: "center",
                  padding: "0.6rem 0.8rem",
                  backgroundColor: activeDoc === doc.name ? "rgba(37, 99, 235, 0.2)" : "rgba(15, 23, 42, 0.6)",
                  border: activeDoc === doc.name ? "1px solid #3b82f6" : "1px solid transparent",
                  borderRadius: "0.5rem", marginBottom: "0.4rem", cursor: "pointer",
                  fontSize: "0.8rem", transition: "all 0.2s",
                }}
                onMouseEnter={(e) => { if (activeDoc !== doc.name) (e.currentTarget as HTMLElement).style.backgroundColor = "rgba(51, 65, 85, 0.6)"; }}
                onMouseLeave={(e) => { if (activeDoc !== doc.name) (e.currentTarget as HTMLElement).style.backgroundColor = "rgba(15, 23, 42, 0.6)"; }}
              >
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>
                  {doc.name}
                  {activeDoc === doc.name && <span style={{ color: "#60a5fa", fontSize: "0.7rem", marginLeft: "0.3rem" }}> (当前)</span>}
                  {selectedDocs.includes(doc.name) && selectedDocs.length > 1 && (
                    <span style={{ color: "#4ade80", fontSize: "0.7rem", marginLeft: "0.3rem" }}> ✓对比</span>
                  )}
                </span>
                <button
                  onClick={(e) => handleDeleteDoc(e, doc.name)}
                  style={{ backgroundColor: "rgba(220, 38, 38, 0.8)", color: "white", border: "none", borderRadius: "0.25rem", padding: "0.2rem 0.4rem", fontSize: "0.7rem", marginLeft: "0.5rem", cursor: "pointer", flexShrink: 0 }}
                >删除</button>
              </div>
            ))}
            <input
              type="file" accept=".pdf" multiple
              onChange={(e) => {
                const files = Array.from(e.target.files || []);
                setUploadFiles(files);
              }}
              style={{ width: "100%", fontSize: "0.8rem", marginTop: "0.5rem", color: "#94a3b8" }}
            />
            {uploadFiles.length > 0 && (
              <div style={{ fontSize: "0.7rem", color: "#94a3b8", marginTop: "0.25rem" }}>
                已选 {uploadFiles.length} 篇{uploadFiles.length > 1 ? "（批量模式）" : ""}
              </div>
            )}
            <button
              onClick={() => handleUploadToDB()}
              disabled={uploadFiles.length === 0}
              style={{ ...styles.btnGreen, width: "100%", marginTop: "0.5rem", opacity: uploadFiles.length === 0 ? 0.5 : 1 }}
            >
              {uploadFiles.length > 1 ? `批量存入 ${uploadFiles.length} 篇` : "存入知识库"}
            </button>
            {dbMessage && <div style={{ fontSize: "0.75rem", color: "#4ade80", marginTop: "0.5rem" }}>{dbMessage}</div>}
          </div>

          <div style={{ borderTop: "1px solid #334155", paddingTop: "1rem" }}>
            <h3 style={{ marginBottom: "0.5rem", color: "#60a5fa" }}>⚖️ 去重与差异</h3>
            <input type="file" accept=".pdf" onChange={(e) => setDedupFile1(e.target.files?.[0] || null)} style={{ width: "100%", fontSize: "0.8rem", marginBottom: "0.5rem", color: "#94a3b8" }} />
            <input type="file" accept=".pdf" onChange={(e) => setDedupFile2(e.target.files?.[0] || null)} style={{ width: "100%", fontSize: "0.8rem", marginBottom: "0.5rem", color: "#94a3b8" }} />
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <button onClick={() => handleDedup("dedup")} style={{ ...styles.btnBlue, flex: 1, fontSize: "0.8rem" }}>开始检测</button>
              <button onClick={() => handleDedup("diff")} style={{ ...styles.btnPurple, flex: 1, fontSize: "0.8rem" }}>查看差异</button>
            </div>
            {dedupResult && <div style={styles.resultBox}>{dedupResult}</div>}
          </div>

          <div style={{ borderTop: "1px solid #334155", paddingTop: "1rem", flex: 1, display: "flex", flexDirection: "column" }}>
            <h3 style={{ marginBottom: "0.5rem", color: "#60a5fa" }}>🕸️ 图谱与综述</h3>
            <div style={{ display: "flex", gap: "0.4rem", marginBottom: "0.5rem", flexWrap: "wrap" }}>
              <button onClick={handleLoadGraph} style={{ ...styles.btnBlue, flex: 1, fontSize: "0.75rem", minWidth: "100px" }}>
                {isGraphLoading ? "渲染中..." : "生成图谱"}
              </button>
              <button onClick={handleGenerateReview} style={{ ...styles.btnPurple, flex: 1, fontSize: "0.75rem", minWidth: "100px" }}>
                生成综述
              </button>
              <button onClick={handleCompare} style={{ ...styles.btnGreen, flex: 1, fontSize: "0.75rem", minWidth: "100px" }}>
                多文献对比
              </button>
              <button onClick={handleFutureWork} style={{ ...styles.btnBlue, flex: 1, fontSize: "0.75rem", minWidth: "100px", backgroundColor: "#f59e0b", boxShadow: "0 2px 8px rgba(245, 158, 11, 0.4)" }}>
                未来方向
              </button>
            </div>
            {graphSummary && (
              <div style={{ fontSize: "0.65rem", color: "#cbd5e1", marginBottom: "0.5rem", backgroundColor: "rgba(2, 6, 23, 0.6)", padding: "0.5rem", borderRadius: "0.5rem", border: "1px solid #334155" }}>
                📊 {graphSummary.total_papers} 篇本地 · {graphSummary.total_refs} 条引用 · {graphSummary.pillar_count} 篇基石论文
              </div>
            )}
            {graphMessage && <div style={{ fontSize: "0.7rem", color: "#fbbf24", marginBottom: "0.25rem" }}>{graphMessage}</div>}
            <div style={{ height: "280px", borderRadius: "0.5rem", marginBottom: "0.5rem", border: "1px solid #334155", position: "relative", backgroundColor: "rgba(11, 17, 32, 0.8)", overflow: "hidden" }}>
              <div ref={chartDomRef} style={{ width: "100%", height: "100%", display: graphData.nodes.length > 0 ? "block" : "none" }} />
              {graphData.nodes.length === 0 && (
                <div style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0, display: "flex", alignItems: "center", justifyContent: "center", fontSize: "0.8rem", color: "#64748b" }}>
                  请先选中文献并点击生成图谱
                </div>
              )}
            </div>
            {reviewText && (
              <div style={{ maxHeight: "150px", overflowY: "auto", backgroundColor: "rgba(15, 23, 42, 0.8)", padding: "0.6rem", fontSize: "0.8rem", color: "#d1d5db", borderRadius: "0.5rem", whiteSpace: "pre-wrap", border: "1px solid #334155" }}>
                {reviewText}
              </div>
            )}
            {compareResult && (
              <div style={{ maxHeight: "180px", overflowY: "auto", backgroundColor: "rgba(2, 6, 23, 0.8)", padding: "0.6rem", fontSize: "0.75rem", color: "#d1d5db", borderRadius: "0.5rem", whiteSpace: "pre-wrap", marginTop: "0.5rem", border: "1px solid #16a34a" }}>
                <div style={{ color: "#4ade80", fontWeight: "bold", marginBottom: "0.2rem" }}>⚖️ 多文献对比</div>
                {compareResult}
              </div>
            )}
            {futureWork && (
              <div style={{ maxHeight: "180px", overflowY: "auto", backgroundColor: "rgba(2, 6, 23, 0.8)", padding: "0.6rem", fontSize: "0.75rem", color: "#d1d5db", borderRadius: "0.5rem", whiteSpace: "pre-wrap", marginTop: "0.5rem", border: "1px solid #f59e0b" }}>
                <div style={{ color: "#fbbf24", fontWeight: "bold", marginBottom: "0.2rem" }}>🌱 未来方向（已过滤旧 idea）</div>
                {futureWork}
              </div>
            )}
          </div>

          <div style={{ flex: 1, display: "flex", flexDirection: "column", borderTop: "1px solid #334155", paddingTop: "1rem" }}>
            <h3 style={{ marginBottom: "0.5rem", color: "#60a5fa" }}>🤖 RAG 问答</h3>
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.4rem" }}>
              <label style={{ fontSize: "0.75rem", color: "#cbd5e1", display: "flex", alignItems: "center", gap: "0.3rem", cursor: "pointer" }}>
                <input type="checkbox" checked={agentMode} onChange={(e) => setAgentMode(e.target.checked)} style={{ cursor: "pointer" }} />
                Agent 智能路由
              </label>
            </div>
            <div style={{ flex: 1, backgroundColor: "rgba(11, 17, 32, 0.8)", borderRadius: "0.5rem", padding: "0.8rem", fontSize: "0.85rem", overflowY: "auto", marginBottom: "0.5rem", whiteSpace: "pre-wrap", wordBreak: "break-all", border: "1px solid #1e293b", boxShadow: "inset 0 2px 10px rgba(0,0,0,0.5)" }}>
              {renderOutput()}
            </div>
            {agentSteps.length > 0 && (
              <div style={{ marginBottom: "0.4rem", maxHeight: "150px", overflowY: "auto", backgroundColor: "rgba(2, 6, 23, 0.8)", padding: "0.6rem", borderRadius: "0.5rem", fontSize: "0.75rem", border: "1px solid #334155" }}>
                <div style={{ color: "#fbbf24", marginBottom: "0.3rem", fontWeight: "bold" }}>🧠 Agent 思考链</div>
                {agentSteps.map((s, i) => (
                  <div key={i} style={{ color: "#94a3b8", marginBottom: "0.2rem", lineHeight: 1.5 }}>
                    {s.type === "tool_call" && `🔧 调用 ${s.tool}(${JSON.stringify(s.args).slice(0, UI.AGENT_ARGS_PREVIEW_LEN)}...)`}
                    {s.type === "tool_result" && `📦 ${s.tool} 结果：${String(s.result_preview || "").slice(0, UI.AGENT_RESULT_PREVIEW_LEN)}...`}
                    {s.type === "thought" && `💭 ${s.content}`}
                  </div>
                ))}
              </div>
            )}
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <input
                style={styles.inputBox} value={input} onChange={(e) => setInput(e.target.value)}
                placeholder="输入关于文献的提问..." onKeyDown={(e) => e.key === "Enter" && handleSend()}
              />
              <button onClick={handleSend} style={styles.btnBlue}>{loading ? "..." : "发送"}</button>
            </div>
          </div>

          <div style={{ borderTop: "1px solid #334155", paddingTop: "1rem" }}>
            <h3 style={{ marginBottom: "0.5rem", color: "#60a5fa" }}>🔍 arXiv 追踪</h3>
            <div style={{ display: "flex", gap: "0.4rem", marginBottom: "0.4rem" }}>
              <input
                value={arxivQuery} onChange={(e) => setArxivQuery(e.target.value)}
                placeholder="关键词 e.g. transformer"
                style={{ ...styles.inputBox, flex: 2, fontSize: "0.75rem" }}
              />
              <select
                value={arxivCategory} onChange={(e) => setArxivCategory(e.target.value)}
                style={{ ...styles.inputBox, flex: 1, fontSize: "0.75rem" }} disabled={!configLoaded}
              >
                {arxivCategories.length === 0 && <option value="">加载中...</option>}
                {arxivCategories.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
              <select
                value={arxivMax} onChange={(e) => setArxivMax(Number(e.target.value))}
                style={{ ...styles.inputBox, width: "70px", fontSize: "0.75rem" }} disabled={!configLoaded}
              >
                {UI.ARXIV_MAX_OPTIONS.map(n => <option key={n} value={n}>{n}</option>)}
              </select>
            </div>
            <button onClick={handleArxivSearch} style={{ ...styles.btnBlue, width: "100%", fontSize: "0.8rem" }}>
              获取最新论文
            </button>
            {arxivStatus && (
              <div style={{ fontSize: "0.7rem", color: arxivOffline ? "#fbbf24" : "#4ade80", marginTop: "0.25rem" }}>
                {arxivStatus}
              </div>
            )}
            {arxivPapers.length > 0 && (
              <div style={{ marginTop: "0.5rem", maxHeight: "400px", overflowY: "auto", backgroundColor: "rgba(15, 23, 42, 0.6)", padding: "0.6rem", borderRadius: "0.5rem", border: "1px solid #1e293b" }}>
                {arxivPapers.map((p, i) => {
                  const key = p.arxiv_url || p.title;
                  const fb = arxivFeedback[key] || { like: 0, dislike: 0 };
                  return (
                    <div key={i} style={{ marginBottom: "0.8rem", borderBottom: "1px dashed #334155", paddingBottom: "0.6rem" }}>
                      <div style={{ color: "#60a5fa", fontWeight: "bold", fontSize: "0.8rem", lineHeight: 1.4 }}>{p.title}</div>
                      <div style={{ color: "#94a3b8", fontSize: "0.7rem", marginTop: "0.2rem" }}>
                        {p.authors} | {p.published}
                        {p.source === "mock_offline" && <span style={{ color: "#fbbf24" }}> | 离线兜底</span>}
                      </div>
                      <div style={{ display: "flex", gap: "0.4rem", marginTop: "0.4rem", flexWrap: "wrap" }}>
                        {p.github_url ? (
                          <a href={p.github_url} target="_blank" rel="noreferrer" style={{ fontSize: "0.65rem", color: "#0f172a", backgroundColor: "#4ade80", padding: "2px 8px", borderRadius: "4px", fontWeight: "bold", textDecoration: "none" }}>
                            ✓ GitHub
                          </a>
                        ) : (
                          <span style={{ fontSize: "0.65rem", color: "#64748b", border: "1px solid #334155", padding: "2px 8px", borderRadius: "4px" }}>
                            无代码
                          </span>
                        )}
                        {p.local_relevance > 0 && (
                          <span style={{ fontSize: "0.65rem", color: "#f1f5f9", backgroundColor: "#3b82f6", padding: "2px 8px", borderRadius: "4px" }}>
                            本地相关 {p.local_relevance} 分
                          </span>
                        )}
                      </div>
                      <div style={{ fontSize: "0.7rem", color: "#cbd5e1", marginTop: "0.4rem", fontStyle: "italic" }}>
                        💡 {p.recommend_reason}
                      </div>
                      <div style={{ fontSize: "0.68rem", color: "#64748b", marginTop: "0.3rem", maxHeight: "2.8em", overflow: "hidden", textOverflow: "ellipsis" }}>
                        {p.summary}
                      </div>
                      <div style={{ display: "flex", gap: "0.4rem", marginTop: "0.4rem", flexWrap: "wrap" }}>
                        <button
                          onClick={() => handleArxivFeedback(p, "like")}
                          style={{ fontSize: "0.65rem", padding: "2px 8px", backgroundColor: "#10b981", color: "white", border: "none", borderRadius: "4px", cursor: "pointer" }}
                        >👍 {fb.like}</button>
                        <button
                          onClick={() => handleArxivFeedback(p, "dislike")}
                          style={{ fontSize: "0.65rem", padding: "2px 8px", backgroundColor: "#ef4444", color: "white", border: "none", borderRadius: "4px", cursor: "pointer" }}
                        >👎 {fb.dislike}</button>
                        <button
                          disabled={arxivDownloading === key}
                          onClick={() => handleArxivDownload(p)}
                          style={{ fontSize: "0.65rem", padding: "2px 8px", backgroundColor: "#8b5cf6", color: "white", border: "none", borderRadius: "4px", cursor: "pointer", opacity: arxivDownloading === key ? 0.5 : 1 }}
                        >{arxivDownloading === key ? "下载中..." : "⬇ 下载入库"}</button>
                        {p.arxiv_url && (
                          <a href={p.arxiv_url} target="_blank" rel="noreferrer" style={{ fontSize: "0.65rem", padding: "2px 8px", backgroundColor: "#334155", color: "#cbd5e1", border: "none", borderRadius: "4px", textDecoration: "none" }}>
                            arXiv 原文
                          </a>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          <div style={{ borderTop: "1px solid #334155", paddingTop: "1rem" }}>
            <h3 style={{ marginBottom: "0.5rem", color: "#60a5fa" }}>📊 数据与写作</h3>
            <div style={{ marginBottom: "0.5rem" }}>
              <label style={{ fontSize: "0.8rem", color: "#cbd5e1", display: "block", marginBottom: "0.25rem" }}>上传 CSV 生成图表:</label>
              <select
                value={chartType} onChange={(e) => setChartType(e.target.value)}
                style={{ ...styles.inputBox, width: "100%", marginBottom: "0.4rem", fontSize: "0.75rem" }}
              >
                <option value="auto">自动推荐</option>
                <option value="table">表格</option>
                <option value="line">折线图</option>
                <option value="bar">柱状图</option>
                <option value="radar">雷达图</option>
                <option value="radar3d">3D 雷达图</option>
              </select>
              <input type="file" accept=".csv" onChange={handleCsvUpload} style={{ width: "100%", fontSize: "0.75rem", color: "#94a3b8" }} />
            </div>
            {isGeneratingChart && <div style={{ fontSize: "0.75rem", color: "#4ade80" }}>图表生成中...</div>}
            {csvChart && (
              <div style={{ backgroundColor: "rgba(15, 23, 42, 0.8)", padding: "0.6rem", borderRadius: "0.5rem", marginBottom: "0.5rem", border: "1px solid #334155" }}>
                <div style={{ fontSize: "0.75rem", color: "#60a5fa", marginBottom: "0.4rem", fontWeight: "bold" }}>图表类型：{csvChart.chartType}</div>
                {csvChart.image && <img src={`data:image/png;base64,${csvChart.image}`} alt="Chart" style={{ width: "100%", borderRadius: "0.4rem", marginBottom: "0.4rem", boxShadow: "0 4px 12px rgba(0,0,0,0.5)" }} />}
                {csvChart.table && (
                  <pre style={{ maxHeight: "120px", overflow: "auto", fontSize: "0.65rem", color: "#cbd5e1", backgroundColor: "rgba(2, 6, 23, 0.8)", padding: "0.4rem", borderRadius: "0.4rem", border: "1px solid #1e293b" }}>
                    {csvChart.table}
                  </pre>
                )}
                <div style={{ fontSize: "0.75rem", color: "#cbd5e1", fontStyle: "italic", whiteSpace: "pre-wrap", marginTop: "0.4rem" }}>
                  {csvChart.caption}
                </div>
              </div>
            )}

            <div style={{ marginTop: "0.8rem" }}>
              <label style={{ fontSize: "0.8rem", color: "#cbd5e1", display: "block", marginBottom: "0.25rem" }}>输入 Idea 生成论文框架:</label>
              <textarea
                value={paperIdea} onChange={(e) => setPaperIdea(e.target.value)}
                placeholder="例如: 用多模态大模型结合 RAG 预测蛋白质结构..."
                style={{ ...styles.inputBox, width: "100%", height: "60px", marginBottom: "0.4rem", fontSize: "0.75rem", resize: "none" }}
              />
              <button
                onClick={handleGenerateFramework}
                disabled={isGeneratingFramework || !paperIdea}
                style={{ ...styles.btnPurple, width: "100%", fontSize: "0.8rem", opacity: (isGeneratingFramework || !paperIdea) ? 0.5 : 1 }}
              >
                {isGeneratingFramework ? "生成中..." : "生成框架"}
              </button>

              {paperFramework && (
                <div style={{ marginTop: "0.5rem", maxHeight: "500px", overflowY: "auto", backgroundColor: "rgba(11, 17, 32, 0.8)", padding: "0.8rem", borderRadius: "0.5rem", fontSize: "0.8rem", color: "#d1d5db", whiteSpace: "pre-wrap", border: "1px solid #334155" }}>
                  {paperFramework}
                </div>
              )}
              
              {frameworkError && (
                <div style={{ marginTop: "0.5rem", padding: "0.6rem", backgroundColor: "rgba(69, 10, 10, 0.8)", color: "#fca5a5", borderRadius: "0.5rem", fontSize: "0.75rem", border: "1px solid #991b1b" }}>
                  ⚠️ {frameworkError}
                </div>
              )}

              {frameworkMermaid && (
                <div style={{ marginTop: "0.5rem", backgroundColor: "rgba(15, 23, 42, 0.8)", padding: "0.6rem", borderRadius: "0.5rem", overflow: "auto", border: "1px solid #334155" }}>
                  <div style={{ fontSize: "0.75rem", color: "#60a5fa", marginBottom: "0.4rem", fontWeight: "bold" }}>Mermaid 架构图</div>
                  {mermaidSvg ? (
                    <div style={{ display: "flex", justifyContent: "center" }} dangerouslySetInnerHTML={{ __html: mermaidSvg }} />
                  ) : (
                    <pre style={{ fontSize: "0.7rem", color: "#cbd5e1", whiteSpace: "pre-wrap" }}>{frameworkMermaid}</pre>
                  )}
                </div>
              )}
              {frameworkTikz && (
                <div style={{ marginTop: "0.5rem", backgroundColor: "rgba(15, 23, 42, 0.8)", padding: "0.6rem", borderRadius: "0.5rem", border: "1px solid #334155" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.4rem" }}>
                    <span style={{ fontSize: "0.75rem", color: "#60a5fa", fontWeight: "bold" }}>TikZ 架构图（LaTeX）</span>
                    <button
                      onClick={() => { navigator.clipboard.writeText(frameworkTikz); alert("已复制 TikZ 脚本"); }}
                      style={{ fontSize: "0.65rem", padding: "2px 8px", backgroundColor: "#3b82f6", color: "white", border: "none", borderRadius: "4px", cursor: "pointer" }}
                    >复制</button>
                  </div>
                  <pre style={{ fontSize: "0.65rem", color: "#cbd5e1", whiteSpace: "pre-wrap", maxHeight: "150px", overflow: "auto", backgroundColor: "rgba(2, 6, 23, 0.6)", padding: "0.4rem", borderRadius: "0.4rem" }}>
                    {frameworkTikz}
                  </pre>
                </div>
              )}
              {frameworkRefs.length > 0 && (
                <div style={{ marginTop: "0.5rem", backgroundColor: "rgba(15, 23, 42, 0.8)", padding: "0.6rem", borderRadius: "0.5rem", fontSize: "0.75rem", color: "#d1d5db", border: "1px solid #334155" }}>
                  <div style={{ color: "#60a5fa", marginBottom: "0.4rem", fontWeight: "bold" }}>References（仅来自本地库）</div>
                  {frameworkRefs.map((r, i) => <div key={i} style={{ marginBottom: "0.2rem" }}>[{i + 1}] {r}</div>)}
                </div>
              )}
              {paperFramework && (
                <button onClick={exportFramework} style={{ ...styles.btnGreen, width: "100%", fontSize: "0.8rem", marginTop: "0.5rem" }}>
                  导出 Markdown
                </button>
              )}
            </div>
          </div>
        </div>

        <div style={styles.card}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid #334155", paddingBottom: "0.5rem", marginBottom: "0.5rem", gap: "0.4rem", flexWrap: "wrap" }}>
            <h3 style={{ margin: 0, color: "#60a5fa", display: "flex", alignItems: "center", gap: "0.5rem" }}>📄 英文原文</h3>
            <div style={{ display: "flex", gap: "0.4rem", alignItems: "center" }}>
              {tocList.length > 0 && (
                <select
                  onChange={(e) => {
                    const page = Number(e.target.value);
                    if (!page || !leftScrollRef.current) return;
                    const target = leftScrollRef.current.querySelector(`[data-page-anchor="${page}"]`);
                    if (target) (target as HTMLElement).scrollIntoView({ behavior: "smooth", block: "center" });
                  }}
                  defaultValue=""
                  style={{ ...styles.inputBox, fontSize: "0.75rem", padding: "0.2rem 0.4rem", maxWidth: "160px" }}
                >
                  <option value="">📑 跳转章节...</option>
                  {tocList.map((t, i) => (
                    <option key={i} value={t.page}>{`${"　".repeat(Math.max(0, t.level - 1))}${t.title} (p.${t.page})`}</option>
                  ))}
                </select>
              )}
              <button
                onClick={handleLoadEnglish}
                disabled={isLoadingEn || !hasRawText}
                style={{ ...styles.btnBlue, fontSize: "0.75rem", padding: "0.3rem 0.6rem", opacity: (isLoadingEn || !hasRawText) ? 0.5 : 1 }}
              >
                {isLoadingEn ? "加载中..." : "显示原文"}
              </button>
            </div>
          </div>
          <div
            ref={leftScrollRef}
            onScroll={(e) => handleScroll(e, "left")}
            onMouseUp={handleMouseUp}
            style={styles.readerBox}
          >{renderedRawText}</div>
        </div>

        <div style={styles.card}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid #334155", paddingBottom: "0.5rem", marginBottom: "0.5rem" }}>
            <h3 style={{ margin: 0, color: "#60a5fa" }}>🇨🇳 中文对照</h3>
            <button
              onClick={handleFullTranslate}
              disabled={isTranslating || !hasRawText}
              style={{ ...styles.btnBlue, fontSize: "0.75rem", padding: "0.3rem 0.6rem", opacity: (isTranslating || !hasRawText) ? 0.5 : 1 }}
            >
              {isTranslating ? "翻译中..." : "一键翻译"}
            </button>
          </div>
          <div
            ref={rightScrollRef}
            onScroll={(e) => handleScroll(e, "right")}
            style={styles.readerBox}
          >{translatedText}</div>
        </div>
      </div>

      {popupPos.visible && (
        <div style={styles.popup} onMouseDown={(e) => e.stopPropagation()}>
          <div style={{ display: "flex", gap: "0.5rem", borderBottom: "1px solid #475569", paddingBottom: "0.5rem", flexWrap: "wrap" }}>
            <button onClick={() => handleTextAction("translate")} style={{ ...styles.btnBlue, flex: 1, fontSize: "0.75rem", minWidth: "80px" }}>划词翻译</button>
            <button onClick={() => handleTextAction("rewrite")} style={{ ...styles.btnBlue, flex: 1, fontSize: "0.75rem", minWidth: "80px", backgroundColor: "#8b5cf6", boxShadow: "0 2px 8px rgba(139, 92, 246, 0.4)" }}>学术重写</button>
            <button onClick={() => handleTextAction("academic_en")} style={{ ...styles.btnBlue, flex: 1, fontSize: "0.75rem", minWidth: "80px", backgroundColor: "#f59e0b", boxShadow: "0 2px 8px rgba(245, 158, 11, 0.4)" }}>中译英</button>
            <button onClick={() => setPopupPos(prev => ({ ...prev, visible: false }))} style={{ ...styles.btnBlue, backgroundColor: "#ef4444", padding: "0.2rem 0.5rem", boxShadow: "0 2px 8px rgba(239, 68, 68, 0.4)" }}>X</button>
          </div>
          <div style={{ fontSize: "0.85rem", color: "#94a3b8", fontStyle: "italic", maxHeight: "50px", overflow: "hidden", textOverflow: "ellipsis", marginTop: "0.2rem" }}>
            "{selectedText.slice(0, UI.SELECTION_PREVIEW_LEN)}{selectedText.length > UI.SELECTION_PREVIEW_LEN ? "..." : ""}"
          </div>
          {(popupResult || popupLoading) && (
            <div style={{ marginTop: "0.4rem", fontSize: "0.9rem", color: "#d1d5db", maxHeight: "200px", overflowY: "auto", borderTop: "1px solid #475569", paddingTop: "0.6rem", lineHeight: 1.6 }}>
              {popupLoading ? "正在处理..." : popupResult}
            </div>
          )}
        </div>
      )}
    </div>
  );
}