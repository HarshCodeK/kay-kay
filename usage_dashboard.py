"""Usage dashboard for the Kay-Kay gateway (reads the telemetry DB).

Run:  streamlit run usage_dashboard.py
"""
import sqlite3
import pandas as pd
import streamlit as st

from src.config import DB_PATH
from src.telemetry import usage_summary

st.set_page_config(page_title="Kay-Kay — Usage", layout="wide")
st.title("Kay-Kay Gateway — Usage")
st.caption("Chapter 1: Connect + Observe. All figures come from the local telemetry DB.")

summary = usage_summary()

m1, m2, m3, m4 = st.columns(4)
m1.metric("Requests", summary["total_requests"])
m2.metric("Successful", summary["successful"])
m3.metric("Est. cost (USD)", f"${summary['est_cost_usd']:.4f}")
m4.metric("Avg latency", f"{summary['avg_latency_ms']:.0f} ms")

if summary["by_model"]:
    st.subheader("By provider / model")
    st.dataframe(pd.DataFrame(summary["by_model"],
                 columns=["provider", "model", "requests", "est_cost_usd"]))

st.subheader("Recent requests")
if summary["recent"]:
    st.dataframe(pd.DataFrame(summary["recent"],
                 columns=["ts", "key_id", "provider", "model", "status", "latency_ms", "est_cost_usd"]))
else:
    st.info("No requests logged yet. Send one through the gateway first.")
