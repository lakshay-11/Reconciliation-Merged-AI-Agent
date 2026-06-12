"""
Exception queue Streamlit component.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st


PRIORITY_COLORS = {
    "critical": "🔴",
    "high":     "🟠",
    "medium":   "🟡",
    "low":      "🟢",
}


def render_exception_summary(exceptions: list[dict]) -> None:
    if not exceptions:
        st.success("✅ No open exceptions | لا توجد استثناءات مفتوحة")
        return

    df = pd.DataFrame(exceptions)

    # Priority breakdown
    if "priority_level" in df.columns:
        counts = df["priority_level"].value_counts()
        cols = st.columns(len(counts))
        for i, (level, count) in enumerate(counts.items()):
            icon = PRIORITY_COLORS.get(level, "⚪")
            cols[i].metric(f"{icon} {level.title()} | {level}", count)

    st.dataframe(df, use_container_width=True)


def render_exception_detail(exc: dict) -> None:
    st.markdown(f"**Exception #{exc.get('id')}**")
    priority = exc.get("priority_level", "")
    icon = PRIORITY_COLORS.get(priority, "⚪")
    st.markdown(f"Priority: {icon} **{priority.upper()}** (score: {exc.get('priority_score', 0):.2f})")
    st.markdown(f"Amount: **{abs(exc.get('amount', 0)):,.2f} {exc.get('currency', 'AED')}**")
    st.markdown(f"Type: `{exc.get('exception_type', 'unknown')}`")
    if exc.get("ai_suggested_action"):
        st.info(f"AI Suggestion: {exc['ai_suggested_action']}")
