"""Streamlit view of the same telemetry the HTML dashboard shows.

Run:  streamlit run usage_dashboard.py
"""
import streamlit as st

from src import telemetry

ACCENT, INK, MUTED = "#1F7A5C", "#12181F", "#5A6673"

st.set_page_config(page_title="Kay-Kay Usage", layout="wide", page_icon="◈")
st.markdown(f"""
<style>
  .block-container {{ padding-top:2.2rem; max-width:1060px; }}
  h1 {{ letter-spacing:-.02em; color:{INK}; font-size:1.6rem; margin-bottom:.1rem; }}
  .sub {{ color:{MUTED}; font-size:.9rem; margin-bottom:1.4rem; }}
  .stat {{ border-left:2px solid #DCE3E8; padding-left:.85rem; margin-top:.7rem; }}
  .stat .v {{ font-size:1.05rem; font-weight:600; }}
  .stat .l {{ font-size:.7rem; color:{MUTED}; text-transform:uppercase;
              letter-spacing:.06em; margin-top:.1rem; }}
  .stButton>button[kind="primary"] {{ background:{ACCENT}; border-color:{ACCENT}; }}
</style>""", unsafe_allow_html=True)

st.title("Kay-Kay gateway usage")
st.markdown('<div class="sub">Every call through the gateway, with its provider, latency, '
            "token counts and estimated cost. Cost is estimated from published rates, "
            "not billed.</div>", unsafe_allow_html=True)

s = telemetry.summary()
cols = st.columns(4)
for col, val, lab in [(cols[0], s["total_requests"], "requests"),
                      (cols[1], s["successful"], "successful"),
                      (cols[2], f"${s['est_cost_usd']:.5f}", "est. cost"),
                      (cols[3], f"{s['avg_latency_ms']:.0f} ms", "avg latency")]:
    with col:
        st.markdown(f'<div class="stat"><div class="v">{val}</div><div class="l">{lab}</div></div>',
                    unsafe_allow_html=True)

st.markdown("#### Spend by provider and model")
if s["by_model"]:
    st.dataframe(s["by_model"], column_config={
        "0": "provider", "1": "model", "2": "requests", "3": "est. cost usd",
    }, use_container_width=True)
else:
    st.caption("No traffic yet. Send a request through the gateway first.")

st.markdown("#### Recent requests")
if s["recent"]:
    st.dataframe(s["recent"], column_config={
        "0": "time", "1": "key", "2": "provider", "3": "model",
        "4": "status", "5": "latency ms", "6": "est. cost usd",
    }, use_container_width=True)
else:
    st.caption("Nothing logged yet.")
