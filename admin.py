"""
CrediGraph Feedback Admin Dashboard
Usage: streamlit run admin.py
"""
import sqlite3
import os
import pandas as pd
import streamlit as st

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "feedback.db")

st.set_page_config(page_title="CrediGraph Admin", page_icon="📊", layout="wide")


@st.cache_data(ttl=5)
def load_feedback():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("""
        SELECT f.id, f.domain, f.vote, f.correction, f.model_prediction,
               u.username, f.timestamp, f.created_at
        FROM feedback f LEFT JOIN users u ON f.user_id = u.id
        ORDER BY f.id DESC
    """, conn)
    conn.close()
    return df


@st.cache_data(ttl=5)
def load_users():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM users ORDER BY id", conn)
    conn.close()
    return df


# ── Header ──
st.title("📊 CrediGraph Feedback Admin")
st.caption(f"Database: `{DB_PATH}`")

if st.button("🔄 Refresh"):
    st.cache_data.clear()

df = load_feedback()
users = load_users()

if df.empty:
    st.info("No feedback yet. Go query some domains on the frontend!")
    st.stop()

# ── Overview metrics ──
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Total Feedback", len(df))
col2.metric("Unique Domains", df["domain"].nunique())
col3.metric("👍 Upvotes", (df["vote"] == "up").sum())
col4.metric("👎 Downvotes", (df["vote"] == "down").sum())
col5.metric("Users", len(users))

# ── Charts ──
st.divider()
chart_col1, chart_col2 = st.columns(2)

with chart_col1:
    st.subheader("Votes by Domain")
    vote_stats = df.groupby("domain")["vote"].value_counts().unstack(fill_value=0)
    st.bar_chart(vote_stats)

with chart_col2:
    st.subheader("Corrections Distribution")
    corrections = df[df["correction"].notna()]["correction"].value_counts()
    if not corrections.empty:
        st.bar_chart(corrections)
    else:
        st.caption("No corrections yet")

# ── Model Accuracy (based on user corrections) ──
st.divider()
st.subheader("🎯 Model Accuracy (from user corrections)")
corrected = df[df["correction"].notna() & df["model_prediction"].notna()].copy()
if not corrected.empty:
    corrected["model_label"] = corrected["model_prediction"].map(
        lambda x: "credible" if x == "credible" else "not_credible"
    )
    corrected["correct"] = corrected["correction"] == corrected["model_label"]
    acc = corrected["correct"].mean()
    total_corrected = len(corrected)
    n_correct = corrected["correct"].sum()

    ac1, ac2, ac3 = st.columns(3)
    ac1.metric("Accuracy", f"{acc:.1%}")
    ac2.metric("Correct", int(n_correct))
    ac3.metric("Total Corrections", total_corrected)

    # Per-domain accuracy
    domain_acc = corrected.groupby("domain")["correct"].agg(["mean", "count"]).reset_index()
    domain_acc.columns = ["domain", "accuracy", "n_corrections"]
    domain_acc = domain_acc.sort_values("n_corrections", ascending=False)
    st.dataframe(domain_acc, use_container_width=True, hide_index=True)
else:
    st.caption("No corrections with model predictions yet")

# ── Filters & Table ──
st.divider()
st.subheader("📋 All Feedback")

filter_col1, filter_col2, filter_col3 = st.columns(3)
with filter_col1:
    domain_filter = st.multiselect("Domain", options=sorted(df["domain"].unique()))
with filter_col2:
    vote_filter = st.multiselect("Vote", options=["up", "down"])
with filter_col3:
    user_filter = st.multiselect("User", options=sorted(df["username"].dropna().unique()))

filtered = df.copy()
if domain_filter:
    filtered = filtered[filtered["domain"].isin(domain_filter)]
if vote_filter:
    filtered = filtered[filtered["vote"].isin(vote_filter)]
if user_filter:
    filtered = filtered[filtered["username"].isin(user_filter)]

st.dataframe(filtered, use_container_width=True, hide_index=True)
st.caption(f"Showing {len(filtered)} / {len(df)} records")

# ── Export ──
st.divider()
exp1, exp2 = st.columns(2)
with exp1:
    csv_data = filtered.to_csv(index=False).encode("utf-8")
    st.download_button("⬇ Download CSV", csv_data, "credigraph_feedback.csv", "text/csv")
with exp2:
    json_data = filtered.to_json(orient="records", force_ascii=False, indent=2).encode("utf-8")
    st.download_button("⬇ Download JSON", json_data, "credigraph_feedback.json", "application/json")

# ── Users ──
st.divider()
st.subheader("👥 Users")
st.dataframe(users, use_container_width=True, hide_index=True)
