"""
Audit log Streamlit component.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st


def render_audit_log(entries: list[dict]) -> None:
    if not entries:
        st.info("No audit entries.")
        return

    df = pd.DataFrame(entries)

    st.caption(
        f"Showing {len(df)} entries. This log is immutable — all entries are permanent (RFP TR-11)."
        " | السجل غير قابل للتغيير"
    )
    st.dataframe(df, use_container_width=True)
