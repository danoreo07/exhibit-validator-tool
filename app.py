# app.py
import streamlit as st
import requests
import json
import pandas as pd
import time
from dotenv import load_dotenv

# Load environment variables (for local testing)
load_dotenv()

# --- CONFIGURATION ---
st.set_page_config(page_title="Exhibit Validator", page_icon="🏛️", layout="wide")

# Backend URL (Change to your Render URL when deployed)
BACKEND_URL = "http://127.0.0.1:8000"

# Translations
TRANSLATIONS = {
    "en": {
        "title": "🏛️ Intent-Driven Data Validator",
        "subtitle": "Upload your raw dataset, define your objective, and let the AI filter the junk.",
        "config_header": "⚙️ Configuration",
        "upload_label": "Upload Data File (JSON or CSV)",
        "objective_label": "Objective (What are you looking for?)",
        "objective_default": "Find all museums, art galleries, and exhibition venues. Exclude training centers, schools, and shops.",
        "llm_label": "Enable LLM Semantic Judge",
        "run_btn": "🚀 Run Validation",
        "preview_header": "👀 Data Preview (First 5 rows)",
        "results_header": "📊 Validation Results",
        "metric_total": "Total Records",
        "metric_ok": "✅ Valid (Keep)",
        "metric_susp": "⚠️ Suspicious (Review)",
        "metric_wrong": "❌ Invalid (Exclude)",
        "filter_label": "Filter by Verdict",
        "download_btn": "📥 Download Results as CSV",
        "error_no_file": "Please upload a file first.",
        "success_msg": "Validation Complete!",
        "processing_msg": "Sending file to server for processing...",
        "data_table_cols": ["ID", "Name", "Verdict", "Reason"],
        "history_header": "📜 Validation History"
    },
    "zh": {
        "title": "🏛️ 意图驱动的数据验证器",
        "subtitle": "上传原始数据集，定义您的目标，让AI过滤垃圾数据。",
        "config_header": "⚙️ 配置",
        "upload_label": "上传数据文件 (JSON 或 CSV)",
        "objective_label": "目标 (您在寻找什么？)",
        "objective_default": "查找所有博物馆、美术馆和展览馆。排除培训中心、学校和商店。",
        "llm_label": "启用大模型语义判断",
        "run_btn": "🚀 开始验证",
        "preview_header": "👀 数据预览 (前5行)",
        "results_header": "📊 验证结果",
        "metric_total": "总记录数",
        "metric_ok": "✅ 有效 (保留)",
        "metric_susp": "⚠️ 可疑 (需审核)",
        "metric_wrong": "❌ 无效 (排除)",
        "filter_label": "按判定结果筛选",
        "download_btn": "📥 下载结果为 CSV",
        "error_no_file": "请先上传文件。",
        "success_msg": "验证完成！",
        "processing_msg": "正在将文件发送至服务器处理...",
        "data_table_cols": ["ID", "名称", "判定", "原因"],
        "history_header": "📜 历史记录"
    }
}

if "lang" not in st.session_state:
    st.session_state.lang = "en"

with st.sidebar:
    lang_choice = st.radio("Language / 语言", ["English", "中文"], index=0 if st.session_state.lang == "en" else 1)
    st.session_state.lang = "en" if lang_choice == "English" else "zh"
    
T = TRANSLATIONS[st.session_state.lang]

st.title(T["title"])
st.markdown(T["subtitle"])

# --- SIDEBAR INPUTS ---
with st.sidebar:
    st.header(T["config_header"])
    uploaded_file = st.file_uploader(T["upload_label"], type=["json", "csv"])
    objective = st.text_area(T["objective_label"], value=T["objective_default"], height=150)
    use_llm = st.checkbox(T["llm_label"], value=True)
    run_btn = st.button(T["run_btn"], type="primary", use_container_width=True)

# --- MAIN LOGIC ---
if uploaded_file is not None:
    # Preview Data
    file_extension = uploaded_file.name.split(".")[-1].lower()
    try:
        if file_extension == "json":
            raw_data = json.load(uploaded_file)
            points = raw_data.get("points", []) if isinstance(raw_data, dict) else raw_data
            preview_df = pd.DataFrame(points).head(5)
        elif file_extension == "csv":
            preview_df = pd.read_csv(uploaded_file).head(5)
        
        st.subheader(T["preview_header"])
        st.dataframe(preview_df, use_container_width=True)
    except Exception as e:
        st.error(f"Error reading file: {e}")

    # Run Button Clicked
    if run_btn:
        with st.spinner(T["processing_msg"]):
            try:
                # Prepare payload
                files = {"file": (uploaded_file.name, uploaded_file.getvalue())}
                data = {
                    "objective": objective,
                    "use_llm": str(use_llm).lower()
                }
                
                # Call Backend API
                response = requests.post(f"{BACKEND_URL}/api/validate", files=files, data=data)
                
                if response.status_code == 200:
                    result = response.json()
                    st.success(T["success_msg"])
                    
                    # Show Results
                    st.subheader(T["results_header"])
                    summary = result["summary"]
                    col1, col2, col3, col4 = st.columns(4)
                    col1.metric(T["metric_total"], summary["total"])
                    col2.metric(T["metric_ok"], summary["ok"])
                    col3.metric(T["metric_susp"], summary["suspicious"])
                    col4.metric(T["metric_wrong"], summary["wrong"])
                    
                    df_results = pd.DataFrame(result["records"])
                    
                    st.markdown("---")
                    verdict_filter = st.multiselect(
                        T["filter_label"], 
                        options=["ok", "suspicious", "wrong"], 
                        default=["ok", "suspicious"]
                    )
                    
                    filtered_df = df_results[df_results["verdict"].isin(verdict_filter)]
                    display_df = filtered_df[["id", "name", "verdict", "reason"]].copy()
                    display_df.columns = T["data_table_cols"]
                    
                    st.dataframe(display_df, use_container_width=True, height=400)
                    
                    # Download Button
                    csv_data = filtered_df.to_csv(index=False).encode('utf-8-sig')
                    st.download_button(
                        label=T["download_btn"],
                        data=csv_data,
                        file_name=f"validated_results_{int(time.time())}.csv",
                        mime="text/csv"
                    )
                else:
                    st.error(f"Server Error: {response.text}")
            except Exception as e:
                st.error(f"Connection Error: {e}")
else:
    st.info("👈 " + ("Please upload a file in the sidebar to get started." if st.session_state.lang == "en" else "请在左侧边栏上传文件以开始。"))

# --- HISTORY TAB (Optional) ---
st.markdown("---")
with st.expander(T["history_header"]):
    try:
        hist_resp = requests.get(f"{BACKEND_URL}/api/history")
        if hist_resp.status_code == 200:
            history_data = hist_resp.json()
            if history_data:
                st.table(pd.DataFrame(history_data)[["filename", "total", "ok_count", "wrong_count", "created_at"]])
            else:
                st.write("No history found.")
    except:
        st.write("Could not load history from server.")