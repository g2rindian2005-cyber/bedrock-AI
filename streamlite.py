import streamlit as st
from datetime import datetime, timedelta, timezone

from app import fetch_logs, fetch_logs_by_date, list_log_groups
from cw_lang import analyze_logs


st.title("📊 CloudWatch Log Analyzer")

region = st.text_input(
    "AWS Region",
    "us-east-1"
)

# Auto-fetch log groups for the selected region
try:
    log_groups = list_log_groups(region)
except Exception as e:
    log_groups = []
    st.error(f"Could not fetch log groups: {e}")

if log_groups:
    log_group = st.selectbox(
        "CloudWatch Log Group",
        log_groups
    )
else:
    st.warning("No log groups found (or unable to list). Enter one manually.")
    log_group = st.text_input(
        "CloudWatch Log Group",
        "/aws/lambda/my-function"
    )

fetch_mode = st.radio(
    "Fetch logs by",
    ["Last N hours", "Specific date"],
    horizontal=True
)

if fetch_mode == "Last N hours":
    hours = st.slider(
        "Last N hours",
        1,
        72,
        2
    )
    selected_date = None
else:
    selected_date = st.date_input(
        "Date (UTC)",
        datetime.now(timezone.utc).date() - timedelta(days=1)
    )
    hours = None

question = st.text_input(
    "Ask about the logs",
    "Why did the application fail?"
)


if st.button("Fetch & Analyze"):

    # 1. Get logs from CloudWatch
    if fetch_mode == "Last N hours":
        events = fetch_logs(
            region,
            log_group,
            hours
        )
    else:
        events = fetch_logs_by_date(
            region,
            log_group,
            selected_date
        )

    if not events:
        st.warning("No logs found.")
        st.stop()

    # Format each event with a readable timestamp
    formatted_events = []
    for event in events:
        ts = datetime.fromtimestamp(
            event["timestamp"] / 1000,
            tz=timezone.utc
        ).strftime("%Y-%m-%d %H:%M:%S UTC")
        formatted_events.append({
            "Timestamp": ts,
            "Message": event["message"].rstrip()
        })

    logs = "\n".join(
        f"[{e['Timestamp']}] {e['Message']}"
        for e in formatted_events
    )

    # 2. Display logs
    st.subheader("CloudWatch Logs")
    st.dataframe(
        formatted_events,
        use_container_width=True,
        hide_index=True
    )

    # 3. Send logs to Bedrock through LangChain
    answer = analyze_logs(
        region,
        logs,
        question
    )

    # 4. Display AI response
    st.subheader("🤖 Bedrock Analysis")
    st.write(answer)