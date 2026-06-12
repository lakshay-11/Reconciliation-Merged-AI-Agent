"""
Match results Streamlit component.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st


def render_match_results(results: list[dict]) -> None:
    if not results:
        st.info("No match results.")
        return

    df = pd.DataFrame(results)

    col1, col2, col3 = st.columns(3)
    auto = df[df["match_status"] == "auto_matched"] if "match_status" in df else pd.DataFrame()
    review = df[df["match_status"] == "pending_review"] if "match_status" in df else pd.DataFrame()
    col1.metric("Auto-Matched | مطابقة تلقائية", len(auto))
    col2.metric("Pending Review | قيد المراجعة", len(review))
    col3.metric("Total Matches | إجمالي المطابقات", len(df))

    if "confidence_score" in df.columns:
        st.subheader("Confidence Distribution | توزيع درجات الثقة")
        st.bar_chart(df["confidence_score"].round(1).value_counts().sort_index())

    st.dataframe(df, use_container_width=True)


def render_confidence_badge(confidence: float) -> str:
    if confidence >= 0.90:
        return f"🟢 {confidence:.0%}"
    if confidence >= 0.70:
        return f"🟡 {confidence:.0%}"
    return f"🔴 {confidence:.0%}"
