"""PaperPilot 全局配置中心。所有业务可调参数集中于此，支持 .env 覆盖。"""
import os
import re
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _int(k, d):
    try: return int(os.getenv(k, str(d)))
    except (ValueError, TypeError): return d


def _float(k, d):
    try: return float(os.getenv(k, str(d)))
    except (ValueError, TypeError): return d


def _list(k, d):
    v = os.getenv(k, "")
    return [x.strip() for x in v.split(",") if x.strip()] if v.strip() else d


CONFIG = {
    # ---------- 路径 ----------
    "doc_registry_path": os.path.join(BASE_DIR, "doc_registry.json"),
    "mock_arxiv_path": os.path.join(BASE_DIR, "mock_arxiv.json"),
    "user_feedback_path": os.path.join(BASE_DIR, "user_feedback.json"),
    "chroma_path": os.getenv("CHROMA_PATH", "./chroma_db"),

    # ---------- 服务 ----------
    "cors_origins": _list("CORS_ORIGINS", ["*"]),

    # ---------- PDF 解析 ----------
    "chunk_size": _int("CHUNK_SIZE", 1000),
    "chunk_overlap": _int("CHUNK_OVERLAP", 200),
    "ingest_batch_size": _int("INGEST_BATCH_SIZE", 500),
    "ocr_dpi": _int("OCR_DPI", 200),
    "parse_log_interval": _int("PARSE_LOG_INTERVAL", 50),
    "toc_dot_threshold": _int("TOC_DOT_THRESHOLD", 10),
    "toc_line_threshold": _int("TOC_LINE_THRESHOLD", 20),
    "toc_dot_char": os.getenv("TOC_DOT_CHAR", "..."),
    "pdf_max_bytes": _int("PDF_MAX_BYTES", 50 * 1024 * 1024),

    # ---------- 元数据 ----------
    "meta_head_chars": _int("META_HEAD_CHARS", 3000),
    "meta_ref_chars": _int("META_REF_CHARS", 3000),
    "meta_refs_min": _int("META_REFS_MIN", 5),
    "meta_refs_max": _int("META_REFS_MAX", 8),
    "references_section_pattern": os.getenv("REFERENCES_SECTION_PATTERN", r"(?i)\n\s*(References|Bibliography)\s*\n"),

    # ---------- 协议常量 ----------
    "reference_page_sentinel": _int("REFERENCE_PAGE_SENTINEL", 999),
    "page_label_template": os.getenv("PAGE_LABEL_TEMPLATE", "《第 {page} 页》"),
    "chunk_id_format": os.getenv("CHUNK_ID_FORMAT", "{filename}_p{page:03d}_c{chunk:03d}"),
    "page_marker_format": os.getenv("PAGE_MARKER_FORMAT", "[Page {page}]"),
    "page_marker_pattern": os.getenv("PAGE_MARKER_PATTERN", r"\[Page \d+\]"),
    # 🚨 新增：/chat 流式兜底时检测 LLM 输出里是否已含页码（避免重复追加）
    "page_marker_probe": os.getenv("PAGE_MARKER_PROBE", "[Page"),
    "references_meta_type": os.getenv("REFERENCES_META_TYPE", "references"),
    "references_meta_refs_key": os.getenv("REFERENCES_META_REFS_KEY", "refs"),
    "references_meta_title_key": os.getenv("REFERENCES_META_TITLE_KEY", "paper_title"),
    "references_block_id_suffix": os.getenv("REFERENCES_BLOCK_ID_SUFFIX", "_references"),
    "review_macro_label_prefix": os.getenv("REVIEW_MACRO_LABEL_PREFIX", "《第"),

    # ---------- 引用锚点 ----------
    "citation_anchor_pattern": os.getenv("CITATION_ANCHOR_PATTERN", r"\n\[(\d+)\]"),
    "citation_anchor_replacement": os.getenv("CITATION_ANCHOR_REPLACEMENT", r'\n<span id="ref-\1">[\1]</span>'),
    "ref_prefix_cleanup_pattern": os.getenv("REF_PREFIX_CLEANUP_PATTERN", r"^([\(\[]\d+[\)\]]|\d+[\.\)])\s*"),

    # ---------- 查重 ----------
    "dedup_threshold": _float("DEDUP_THRESHOLD", 85.0),
    "dedup_preview_chars": _int("DEDUP_PREVIEW_CHARS", 15000),
    "dedup_preview_pages": _int("DEDUP_PREVIEW_PAGES", 5),
    "dedup_compare_chars": _int("DEDUP_COMPARE_CHARS", 15000),
    "dedup_prompt_chars": _int("DEDUP_PROMPT_CHARS", 4000),
    "diff_prompt_chars": _int("DIFF_PROMPT_CHARS", 3000),
    "diff_summary_sentences": _int("DIFF_SUMMARY_SENTENCES", 3),

    # ---------- RAG ----------
    "rag_top_k": _int("RAG_TOP_K", 20),
    "rag_sparse_top_k": _int("RAG_SPARSE_TOP_K", 3),
    "rag_tokens_max": _int("RAG_TOKENS_MAX", 3),
    "rag_min_token_len": _int("RAG_MIN_TOKEN_LEN", 3),
    "rag_refusal_keywords": _list("RAG_REFUSAL_KEYWORDS", ["抱歉", "未在文献中", "未找到", "无法回答", "无法提供"]),
    "trans_keywords_count": _int("TRANS_KEYWORDS_COUNT", 3),

    # ---------- arXiv ----------
    "arxiv_categories": _list("ARXIV_CATEGORIES", ["cs.CL", "cs.CV", "cs.LG", "cs.AI", "cs.IR"]),
    "arxiv_default_category": os.getenv("ARXIV_DEFAULT_CATEGORY", "cs.CL"),
    "arxiv_max_results": _int("ARXIV_MAX_RESULTS", 10),
    "arxiv_max_results_cap": _int("ARXIV_MAX_RESULTS_CAP", 50),
    "arxiv_timeout": _int("ARXIV_TIMEOUT", 15),
    "arxiv_download_timeout": _int("ARXIV_DOWNLOAD_TIMEOUT", 60),
    "arxiv_agent_fetch_n": _int("ARXIV_AGENT_FETCH_N", 5),
    "arxiv_user_agent": os.getenv("ARXIV_USER_AGENT", "Mozilla/5.0 PaperPilot/1.0"),
    "arxiv_sort_by": os.getenv("ARXIV_SORT_BY", "submittedDate"),
    "arxiv_sort_order": os.getenv("ARXIV_SORT_ORDER", "descending"),
    "arxiv_authors_max": _int("ARXIV_AUTHORS_MAX", 5),
    "arxiv_authors_etc_suffix": os.getenv("ARXIV_AUTHORS_ETC_SUFFIX", " 等"),

    # ---------- 相关度 ----------
    "relevance_smoothing": _float("RELEVANCE_SMOOTHING", 1.0),
    "relevance_high": _float("RELEVANCE_HIGH", 50.0),
    "relevance_medium": _float("RELEVANCE_MEDIUM", 20.0),
    "relevance_summary_chars": _int("RELEVANCE_SUMMARY_CHARS", 300),
    "recent_year_window": _int("RECENT_YEAR_WINDOW", 1),

    # ---------- 图谱 ----------
    "pillar_ratio": _float("PILLAR_RATIO", 1.5),
    "graph_agent_top_nodes": _int("GRAPH_AGENT_TOP_NODES", 10),
    "pagerank_scale": _float("PAGERANK_SCALE", 1000.0),
    "graph_node_base_size": _float("GRAPH_NODE_BASE_SIZE", 20.0),
    "graph_node_size_range": _float("GRAPH_NODE_SIZE_RANGE", 50.0),
    "graph_node_fallback_size": _float("GRAPH_NODE_FALLBACK_SIZE", 30.0),
    "graph_node_local_size": _float("GRAPH_NODE_LOCAL_SIZE", 30.0),
    "graph_fallback_pr": _float("GRAPH_FALLBACK_PR", 1.0),

    # ---------- 对比 ----------
    "compare_min_docs": _int("COMPARE_MIN_DOCS", 2),
    "compare_max_docs": _int("COMPARE_MAX_DOCS", 5),
    "compare_per_doc_chunks": _int("COMPARE_PER_DOC_CHUNKS", 3),
    "compare_default_aspect": os.getenv("COMPARE_DEFAULT_ASPECT", "核心架构、贡献与差异"),

    # ---------- Future Work ----------
    "future_work_max_docs": _int("FUTURE_WORK_MAX_DOCS", 5),
    "future_work_chunks_per_doc": _int("FUTURE_WORK_CHUNKS_PER_DOC", 3),
    "future_work_query": os.getenv("FUTURE_WORK_QUERY", "future work future direction limitations next steps open problems"),

    # ---------- 综述 ----------
    "review_macro_chunks": _int("REVIEW_MACRO_CHUNKS", 3),
    "review_local_chunks": _int("REVIEW_LOCAL_CHUNKS", 3),
    "review_queries": _list("REVIEW_QUERIES", ["core architecture and contribution", "future work and limitations"]),

    # ---------- 框架 ----------
    "framework_rag_k": _int("FRAMEWORK_RAG_K", 5),
    "framework_max_candidates": _int("FRAMEWORK_MAX_CANDIDATES", 5),

    # ---------- Agent ----------
    "agent_result_preview_chars": _int("AGENT_RESULT_PREVIEW_CHARS", 300),
    "agent_route_timeout": _int("AGENT_ROUTE_TIMEOUT", 60),
    "agent_final_timeout": _int("AGENT_FINAL_TIMEOUT", 90),

    # ---------- CSV ----------
    "csv_max_bytes": _int("CSV_MAX_BYTES", 2_000_000),
    "csv_max_columns": _int("CSV_MAX_COLUMNS", 30),
    "csv_max_rows": _int("CSV_MAX_ROWS", 5000),
    "csv_preview_rows": _int("CSV_PREVIEW_ROWS", 20),
    "csv_bar_max_rows": _int("CSV_BAR_MAX_ROWS", 12),
    "csv_radar_max_dims": _int("CSV_RADAR_MAX_DIMS", 5),
    "csv_radar_max_rows": _int("CSV_RADAR_MAX_ROWS", 8),
    "csv_radar_min_cols": _int("CSV_RADAR_MIN_COLS", 3),
    "csv_line_min_rows": _int("CSV_LINE_MIN_ROWS", 6),
    "csv_stats_chars": _int("CSV_STATS_CHARS", 3000),
    "csv_figsize_w": _float("CSV_FIGSIZE_W", 8.0),
    "csv_figsize_h": _float("CSV_FIGSIZE_H", 5.0),
    "csv_dpi": _int("CSV_DPI", 150),
    "csv_chart_types": _list("CSV_CHART_TYPES", ["auto", "table", "line", "bar", "radar", "radar3d"]),
    "csv_bar_width_ratio": _float("CSV_BAR_WIDTH_RATIO", 0.8),
    "csv_xlabel_rotation": _int("CSV_XLABEL_ROTATION", 30),
    "csv_caption_figure_no": _int("CSV_CAPTION_FIGURE_NO", 1),

    # ---------- 兜底串 ----------
    "fallback_no_context": os.getenv("FALLBACK_NO_CONTEXT", "暂无文献数据"),
    "fallback_no_detail": os.getenv("FALLBACK_NO_DETAIL", "暂无详细内容"),
    "fallback_no_candidates": os.getenv("FALLBACK_NO_CANDIDATES", "（本地知识库暂无相关文献候选）"),
    "fallback_no_context_fragment": os.getenv("FALLBACK_NO_CONTEXT_FRAGMENT", "（本地知识库暂无相关文献片段）"),
    "fallback_no_candidates_short": os.getenv("FALLBACK_NO_CANDIDATES_SHORT", "（无）"),
    "fallback_ocr_failed": os.getenv("FALLBACK_OCR_FAILED", "[扫描页 {page}，OCR提取失败]"),
    "fallback_no_refs_found": os.getenv("FALLBACK_NO_REFS_FOUND", "本地知识库暂无相关文献，未生成引用。"),
    "fallback_arxiv_id": os.getenv("FALLBACK_ARXIV_ID", "paper"),
    "fallback_unknown_source": os.getenv("FALLBACK_UNKNOWN_SOURCE", "未知文献"),
    "fallback_framework_template": os.getenv(
        "FALLBACK_FRAMEWORK_TEMPLATE",
        "# 论文框架\n\n## Abstract\n围绕以下 Idea 展开：{idea}\n\n"
        "## Introduction\n待补充。\n\n## Related Work\n待补充。\n\n"
        "## Method\n待补充。\n\n## Conclusion\n待补充。\n\n{refs_note}",
    ),
    "fallback_mermaid_flowchart": os.getenv(
        "FALLBACK_MERMAID_FLOWCHART",
        "flowchart TD\n    A[Research Idea] --> B[Abstract]\n    B --> C[Introduction]\n"
        "    C --> D[Related Work]\n    D --> E[Method]\n    E --> F[Conclusion]",
    ),

    # ---------- Prompt 模板 ----------
    "vision_ocr_prompt": os.getenv(
        "VISION_OCR_PROMPT",
        "请提取这张学术论文图片中的所有文本内容，保持原有排版格式。绝对不要输出任何废话，只输出纯文本。",
    ),
    "trans_expand_prompt_template": os.getenv(
        "TRANS_EXPAND_PROMPT_TEMPLATE",
        "将以下问题翻译成英文，并提取出最核心的 {n} 个英文检索词。\n"
        "格式严格如下（不要输出任何其他解释）：\n"
        "翻译：<完整英文翻译>\n"
        "关键词：<关键词1> <关键词2> <关键词3>\n"
        "问题：{message}",
    ),

    # ---------- LLM ----------
    "llm_model": os.getenv("MODEL_NAME", ""),
    "llm_timeout": _int("LLM_TIMEOUT", 90),
    "llm_temperature": _float("LLM_TEMPERATURE", 0.0),
}


def recent_cutoff_date():
    return f"{datetime.now().year - CONFIG['recent_year_window']}-01-01"


def format_page_label(page_num):
    return CONFIG["page_label_template"].format(page=page_num)


def format_page_marker(page):
    return CONFIG["page_marker_format"].format(page=page)


def format_chunk_id(filename, page, chunk):
    return CONFIG["chunk_id_format"].format(filename=filename, page=page, chunk=chunk)


def format_rag_context(source, page, chunk, sparse=False):
    if sparse:
        return f"[文献: {source} | Page {page} | 稀疏检索命中]: {chunk}"
    return f"[文献: {source} | Page {page}]: {chunk}"


def is_reference_page(page):
    try: return int(page) == CONFIG["reference_page_sentinel"]
    except (ValueError, TypeError): return False


def is_reference_type(meta):
    return meta.get("type") == CONFIG["references_meta_type"]


def wrap_citation_anchors(text):
    return re.sub(CONFIG["citation_anchor_pattern"], CONFIG["citation_anchor_replacement"], text)


def clean_ref_name(ref):
    return re.sub(CONFIG["ref_prefix_cleanup_pattern"], "", ref).strip()