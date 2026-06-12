"""
Reconciliation AI Agent — Streamlit Dashboard
Dubai Department of Finance | Use Case 5

Bilingual Arabic + English interface.
Runs against the FastAPI backend on http://localhost:8000
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import requests
import streamlit as st

from dashboard.components.match_view import render_match_results, render_confidence_badge
from dashboard.components.exception_view import render_exception_summary, render_exception_detail, PRIORITY_COLORS
from dashboard.components.audit_view import render_audit_log

# ── Page config ────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="نظام المطابقة | Reconciliation System",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

BASE_URL = "http://localhost:8000"


def api(method: str, path: str, **kwargs):
    try:
        r = requests.request(method, f"{BASE_URL}{path}", timeout=30, **kwargs)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        st.error("Cannot connect to API server. Ensure uvicorn is running on port 8000.")
        return None
    except requests.exceptions.HTTPError as e:
        code = e.response.status_code
        try:
            detail = e.response.json().get("detail", e.response.text[:300])
        except Exception:
            detail = e.response.text[:300]
        if code == 503 or code == 401:
            st.warning(f"AI Agent not available: {detail}")
        else:
            st.error(f"API error {code}: {detail}")
        return None


# ── Sidebar ────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## نظام المطابقة المالية\n## Financial Reconciliation AI")
    st.caption("Dubai Department of Finance — Use Case 5")
    st.markdown("---")
    page = st.radio(
        "Navigation | التنقل",
        options=[
            "📊 Dashboard | لوحة التحكم",
            "🔄 New Run | تشغيل جديد",
            "⚠️ Exceptions | الاستثناءات",
            "🔍 Match Results | نتائج المطابقة",
            "📋 Audit Log | سجل التدقيق",
            "💬 AI Agent | المساعد الذكي",
        ],
    )
    st.markdown("---")

# ── Health check ───────────────────────────────────────────────────────────
health = api("GET", "/health")
if health:
    st.sidebar.success(f"API Online | {health.get('app', '')}")
else:
    st.sidebar.error("API Offline")


# ══════════════════════════════════════════════════════════════════════════
# Page: Dashboard
# ══════════════════════════════════════════════════════════════════════════
if page.startswith("📊"):
    st.title("📊 Reconciliation Dashboard | لوحة متابعة المطابقة")

    runs = api("GET", "/api/reports/runs?limit=10") or []

    if not runs:
        st.info("No reconciliation runs yet. Start a new run from the 'New Run' page.")
    else:
        latest = runs[0]

        col1, col2, col3, col4 = st.columns(4)
        col1.metric(
            "Auto-Reconciled % | المطابقة التلقائية",
            f"{latest.get('auto_reconciled_pct') or 0:.1f}%",
        )
        col2.metric("Matched | مطابق", latest.get("matched_count", 0))
        col3.metric("Exceptions | استثناءات", latest.get("exception_count", 0))
        col4.metric("Run Status | الحالة", latest.get("status", "—"))

        st.markdown("---")
        st.subheader("Recent Runs | التشغيلات الأخيرة")

        df = pd.DataFrame(runs)
        display_cols = ["id", "run_date", "status", "total_transactions",
                        "matched_count", "exception_count", "auto_reconciled_pct"]
        display_cols = [c for c in display_cols if c in df.columns]
        st.dataframe(df[display_cols], use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════
# Page: New Run
# ══════════════════════════════════════════════════════════════════════════
elif page.startswith("🔄"):
    st.title("🔄 Start Reconciliation Run | بدء تشغيل المطابقة")

    # ── Step 1: Create a new source (optional) ─────────────────────────
    with st.expander("Step 0 — Register a new data source (first time only) | تسجيل مصدر جديد"):
        c1, c2, c3 = st.columns(3)
        with c1:
            new_src_name = st.text_input("Source name (English)", placeholder="e.g. ENBD Bank Jan 2025")
        with c2:
            new_src_name_ar = st.text_input("Source name (Arabic) | الاسم بالعربي", placeholder="بنك الإمارات")
        with c3:
            new_src_type = st.selectbox("Source type", ["bank", "ledger", "erp", "manual"])
        if st.button("Register Source | تسجيل المصدر"):
            if not new_src_name:
                st.error("Source name is required.")
            else:
                r = api("POST", "/api/reconciliation/sources", json={
                    "name": new_src_name,
                    "name_ar": new_src_name_ar,
                    "source_type": new_src_type,
                })
                if r:
                    st.success(f"Source '{r['name']}' registered with ID {r['id']}. Refresh to see it below.")

    sources = api("GET", "/api/reconciliation/sources") or []
    if not sources:
        st.warning("No sources yet. Register at least two sources above (one bank, one ledger).")
        st.stop()

    source_map = {f"{s['id']}: {s['name']} ({s['source_type']})": s["id"] for s in sources}
    labels = list(source_map.keys())

    st.markdown("---")

    # ── Step 1: Upload files ────────────────────────────────────────────
    st.subheader("Step 1 — Upload data files | رفع ملفات البيانات")
    st.caption("Upload a CSV or Excel file for each source. Supported columns are auto-detected.")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Bank Statement / كشف بنكي**")
        bank_source_label = st.selectbox("Select bank source", labels, key="upload_bank")
        bank_file = st.file_uploader(
            "Upload bank CSV / XLSX", type=["csv", "xlsx", "xls"], key="bank_upload"
        )
        if bank_file and st.button("Ingest Bank File | رفع الملف البنكي"):
            with st.spinner("Ingesting..."):
                r = requests.post(
                    f"{BASE_URL}/api/reconciliation/ingest/{source_map[bank_source_label]}",
                    files={"file": (bank_file.name, bank_file.getvalue(), bank_file.type)},
                    timeout=60,
                )
            if r.status_code == 200:
                d = r.json()
                st.success(f"Ingested {d['inserted']} rows from {bank_file.name}")
                if d["error_count"]:
                    st.warning(f"{d['error_count']} row(s) had validation errors.")
            else:
                st.error(f"Ingestion failed: {r.text[:200]}")

    with col2:
        st.markdown("**GL / Ledger / ERP | دفتر الأستاذ**")
        ledger_source_label = st.selectbox("Select ledger source", labels, key="upload_ledger",
                                           index=min(1, len(labels) - 1))
        ledger_file = st.file_uploader(
            "Upload ledger CSV / XLSX", type=["csv", "xlsx", "xls"], key="ledger_upload"
        )
        if ledger_file and st.button("Ingest Ledger File | رفع ملف الأستاذ"):
            with st.spinner("Ingesting..."):
                r = requests.post(
                    f"{BASE_URL}/api/reconciliation/ingest/{source_map[ledger_source_label]}",
                    files={"file": (ledger_file.name, ledger_file.getvalue(), ledger_file.type)},
                    timeout=60,
                )
            if r.status_code == 200:
                d = r.json()
                st.success(f"Ingested {d['inserted']} rows from {ledger_file.name}")
                if d["error_count"]:
                    st.warning(f"{d['error_count']} row(s) had validation errors.")
            else:
                st.error(f"Ingestion failed: {r.text[:200]}")

    st.markdown("---")

    # ── Step 2: Run reconciliation ──────────────────────────────────────
    st.subheader("Step 2 — Run Reconciliation | تشغيل المطابقة")

    col1, col2 = st.columns(2)
    with col1:
        src_a_label = st.selectbox("Source A — Bank | المصدر الأول (البنك)", labels, key="run_a")
    with col2:
        src_b_label = st.selectbox("Source B — Ledger | المصدر الثاني (الأستاذ)", labels,
                                   key="run_b", index=min(1, len(labels) - 1))

    use_ai = st.toggle("Enable AI Matching | تفعيل المطابقة الذكية", value=True)
    st.caption("AI matching uses multilingual semantic embeddings for Arabic and English descriptions.")

    if st.button("Run Reconciliation | تشغيل المطابقة", type="primary"):
        with st.spinner("Running reconciliation... | جارٍ التشغيل..."):
            result = api("POST", "/api/reconciliation/run", json={
                "source_a_id": source_map[src_a_label],
                "source_b_id": source_map[src_b_label],
                "use_ai": use_ai,
            })
        if result:
            st.success(f"Run #{result['run_id']} completed!")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Auto-Matched", result.get("auto_matched", 0))
            c2.metric("Pending Review", result.get("pending_review", 0))
            c3.metric("Exceptions", result.get("exceptions", 0))
            c4.metric("Auto-Reconciled %", f"{result.get('auto_reconciled_pct', 0):.1f}%")
            st.info(result.get("message", ""))
            st.caption(f"Go to 'Match Results' and enter Run ID {result['run_id']} to see details.")


# ══════════════════════════════════════════════════════════════════════════
# Page: Exceptions
# ══════════════════════════════════════════════════════════════════════════
elif page.startswith("⚠️"):
    st.title("⚠️ Exception Queue | قائمة الاستثناءات")

    col1, col2 = st.columns(2)
    with col1:
        run_id_filter = st.number_input("Filter by Run ID (0 = all) | تصفية", min_value=0, value=0, step=1)
    with col2:
        priority_filter = st.selectbox("Priority | الأولوية", ["all", "critical", "high", "medium", "low"])

    params: dict = {}
    if run_id_filter > 0:
        params["run_id"] = int(run_id_filter)
    if priority_filter != "all":
        params["priority_level"] = priority_filter

    query_str = "&".join(f"{k}={v}" for k, v in params.items())
    exceptions = api("GET", f"/api/exceptions{'?' + query_str if query_str else ''}") or []

    render_exception_summary(exceptions)

    if exceptions:
        st.markdown("---")
        st.subheader("Analyse with AI | تحليل بالذكاء الاصطناعي")
        exc_id = st.number_input("Exception ID to analyse | رقم الاستثناء", min_value=1, step=1)
        if st.button("Analyse | تحليل", type="primary"):
            with st.spinner("Consulting AI agent... | جارٍ التحليل..."):
                result = api("POST", f"/api/exceptions/{int(exc_id)}/analyse")
            if result:
                render_exception_detail(result)
                st.markdown(f"**AI Response | رد الذكاء الاصطناعي:**")
                st.markdown(result.get("response", ""))
                st.warning("Human approval required before any action | مطلوب موافقة بشرية قبل أي إجراء")

        st.markdown("---")
        st.subheader("Resolve Exception | حل الاستثناء")
        c1, c2 = st.columns(2)
        with c1:
            resolve_id = st.number_input("Exception ID to resolve", min_value=1, step=1)
            action = st.selectbox("Action | الإجراء", ["manual_match", "write_off", "escalate", "rejected"])
        with c2:
            resolved_by = st.number_input("Resolved By (User ID) | بواسطة", min_value=1, value=1, step=1)
            notes = st.text_input("Notes | ملاحظات", "")

        if st.button("Resolve | حل"):
            result = api("POST", f"/api/exceptions/{int(resolve_id)}/resolve", json={
                "action_type": action,
                "resolved_by": int(resolved_by),
                "notes": notes or None,
            })
            if result:
                st.success(f"Exception #{resolve_id} resolved as `{action}`.")


# ══════════════════════════════════════════════════════════════════════════
# Page: Match Results
# ══════════════════════════════════════════════════════════════════════════
elif page.startswith("🔍"):
    st.title("🔍 Match Results | نتائج المطابقة")

    run_id = st.number_input("Run ID | رقم التشغيل", min_value=1, step=1, value=1)

    if st.button("Load Results | تحميل النتائج", type="primary"):
        results = api("GET", f"/api/reconciliation/run/{int(run_id)}/results") or []
        if not results:
            st.info("No results for this run.")
        else:
            render_match_results(results)

            with st.expander("Raw data | البيانات الخام"):
                st.dataframe(pd.DataFrame(results), use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════
# Page: Audit Log
# ══════════════════════════════════════════════════════════════════════════
elif page.startswith("📋"):
    st.title("📋 Immutable Audit Log | سجل التدقيق غير القابل للتغيير")
    st.info("Every entry is permanent and cannot be edited or deleted (RFP TR-11). | كل إدخال دائم ولا يمكن تغييره.")

    col1, col2 = st.columns(2)
    with col1:
        entity_type_filter = st.selectbox(
            "Entity Type | نوع الكيان",
            ["", "reconciliation_runs", "exception_queue", "match_results"],
        )
    with col2:
        entity_id_filter = st.number_input("Entity ID (0 = all) | رقم الكيان", min_value=0, step=1)

    params = {}
    if entity_type_filter:
        params["entity_type"] = entity_type_filter
    if entity_id_filter > 0:
        params["entity_id"] = int(entity_id_filter)

    query_str = "&".join(f"{k}={v}" for k, v in params.items())
    entries = api("GET", f"/api/reports/audit{'?' + query_str if query_str else ''}") or []

    render_audit_log(entries)


# ══════════════════════════════════════════════════════════════════════════
# Page: AI Agent
# ══════════════════════════════════════════════════════════════════════════
elif page.startswith("💬"):
    st.title("💬 AI Reconciliation Agent | المساعد الذكي للمطابقة")
    st.info(
        "Ask questions about reconciliation runs, exceptions, and match results. "
        "The agent fetches live data and provides bilingual recommendations.\n\n"
        "اطرح أسئلة حول التشغيلات والاستثناءات ونتائج المطابقة."
    )
    st.warning("All AI suggestions require human approval before any action is taken. (FR-08)")

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("tool_calls"):
                with st.expander(f"Tools used: {len(msg['tool_calls'])} call(s)"):
                    for tc in msg["tool_calls"]:
                        st.code(f"{tc['tool']}({tc['input']})", language="python")

    if prompt := st.chat_input("Ask the reconciliation agent... | اسأل مساعد المطابقة..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Thinking... | جارٍ التفكير..."):
                result = api("POST", "/api/agent/chat", json={"message": prompt})

            if result:
                response_text = result.get("response", "No response.")
                tool_calls = result.get("tool_calls", [])
                st.markdown(response_text)
                if tool_calls:
                    with st.expander(f"Tools used: {len(tool_calls)} call(s)"):
                        for tc in tool_calls:
                            st.code(f"{tc['tool']}({tc['input']})", language="python")
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": response_text,
                    "tool_calls": tool_calls,
                })
            else:
                fallback = "Could not reach the AI agent. Check that the API server is running."
                st.markdown(fallback)
                st.session_state.messages.append({"role": "assistant", "content": fallback})
