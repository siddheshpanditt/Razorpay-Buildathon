"""
Streamlit dashboard.
Launch: streamlit run dashboard/app.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
import pandas as pd

from audit.reporter import (
    revenue_summary, breakdown_by_leak_type,
    breakdown_by_root_cause, audit_flags, per_case_trail,
)
from audit.writer import get_case_trail

st.set_page_config(page_title="AI Revenue Recovery", layout="wide")
st.title("AI Revenue Recovery — Batch Dashboard")

# ── top-line metrics ──────────────────────────────────────────────────────────

s = revenue_summary()

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Total Cases", s["total_cases"])
c2.metric("Revenue at Risk", f"₹{s['total_at_risk']:,.0f}")
c3.metric("Recovered", f"₹{s['total_recovered']:,.0f}")
c4.metric("Recovery Rate", f"{s['recovery_rate']*100:.1f}%")
c5.metric("Escalated", f"₹{s['total_escalated']:,.0f}")

st.divider()

# ── audit flags ───────────────────────────────────────────────────────────────

flags = audit_flags()
f1, f2, f3 = st.columns(3)
f1.metric("LLM Output Corrected", flags["llm_output_corrected"],
          help="Diagnoses where Claude returned an invalid enum — fell back to unknown/suppress")
f2.metric("Rules-Engine Escalations", flags["rules_engine_forced_escalations"],
          help="Cases escalated by the rules engine due to high value, not by the LLM")
f3.metric("Hard-Blocked Cases", flags["hard_blocked_cases"],
          help="Cases blocked by DNC, opt-out, max attempts, cooldown, or suppress list")

st.divider()

# ── breakdowns ────────────────────────────────────────────────────────────────

col_left, col_right = st.columns(2)

with col_left:
    st.subheader("By Leak Type")
    lt_rows = breakdown_by_leak_type()
    if lt_rows:
        df_lt = pd.DataFrame(lt_rows)
        df_lt["recovery_rate"] = (df_lt["recovery_rate"] * 100).round(1)
        df_lt.columns = ["Leak Type", "Cases", "At Risk (₹)", "Recovered (₹)", "Rate (%)"]
        st.dataframe(df_lt, use_container_width=True, hide_index=True)
        st.bar_chart(df_lt.set_index("Leak Type")["Rate (%)"])
    else:
        st.info("No data yet — run the batch first.")

with col_right:
    st.subheader("By Root Cause")
    rc_rows = breakdown_by_root_cause()
    if rc_rows:
        df_rc = pd.DataFrame(rc_rows)
        df_rc["recovery_rate"] = (df_rc["recovery_rate"] * 100).round(1)
        df_rc.columns = ["Leak Type", "Root Cause", "Cases", "At Risk (₹)", "Recovered (₹)", "Rate (%)"]
        st.dataframe(df_rc, use_container_width=True, hide_index=True)
        st.bar_chart(df_rc.set_index("Root Cause")["Rate (%)"])
    else:
        st.info("No data yet — run the batch first.")

st.divider()

# ── per-case audit table ──────────────────────────────────────────────────────

st.subheader("Per-Case Audit Trail")

cases = per_case_trail()
if not cases:
    st.info("No cases yet.")
else:
    df = pd.DataFrame(cases)

    # Search / filter controls
    search_col, lt_col, status_col = st.columns([3, 2, 2])
    search = search_col.text_input("Search case_id / customer_id")
    lt_filter = lt_col.selectbox("Leak type", ["all"] + sorted(df["leak_type"].unique().tolist()))
    status_filter = status_col.selectbox("Status", ["all"] + sorted(df["status"].unique().tolist()))

    if search:
        df = df[df["case_id"].str.contains(search, case=False) |
                df["customer_id"].str.contains(search, case=False)]
    if lt_filter != "all":
        df = df[df["leak_type"] == lt_filter]
    if status_filter != "all":
        df = df[df["status"] == status_filter]

    # Highlight corrected diagnoses
    def _highlight(row):
        if row.get("diagnosis_corrected"):
            return ["background-color: #fff3cd"] * len(row)
        return [""] * len(row)

    display_cols = [
        "case_id", "leak_type", "customer_id", "amount", "status",
        "root_cause", "recommended_intervention", "confidence",
        "requires_human_escalation", "diagnosis_corrected", "created_at",
    ]
    df_display = df[[c for c in display_cols if c in df.columns]]
    st.dataframe(
        df_display.style.apply(_highlight, axis=1),
        use_container_width=True,
        hide_index=True,
    )

    # Drill-down: full audit log for a selected case
    st.subheader("Case Drill-Down")
    selected_id = st.text_input("Paste a case_id to see its full audit trail")
    if selected_id:
        trail = get_case_trail(selected_id.strip())
        if trail:
            st.dataframe(pd.DataFrame(trail), use_container_width=True, hide_index=True)
        else:
            st.warning("No audit entries found for that case_id.")
