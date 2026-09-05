import sys

import boto3
import streamlit as st
from datetime import datetime, timedelta, timezone

from cw_lang import analyze_logs


def list_log_groups(region):

    client = boto3.client("logs", region_name=region)

    log_groups = []
    paginator = client.get_paginator("describe_log_groups")

    for page in paginator.paginate():
        for group in page.get("logGroups", []):
            log_groups.append(group["logGroupName"])

    return sorted(log_groups)


def fetch_logs(region, log_group, hours=2, limit=100):

    client = boto3.client("logs", region_name=region)

    now = datetime.now(timezone.utc)

    response = client.filter_log_events(
        logGroupName=log_group,
        startTime=int(
            (now - timedelta(hours=hours)).timestamp() * 1000
        ),
        endTime=int(now.timestamp() * 1000),
        limit=limit
    )

    return response.get("events", [])


def fetch_logs_by_date(region, log_group, target_date, limit=1000):
    """Fetch all logs for a specific calendar date (UTC), from
    00:00:00 to 23:59:59 on that date."""

    client = boto3.client("logs", region_name=region)

    start = datetime(
        target_date.year, target_date.month, target_date.day,
        0, 0, 0, tzinfo=timezone.utc
    )
    end = start + timedelta(days=1)

    events = []
    kwargs = {
        "logGroupName": log_group,
        "startTime": int(start.timestamp() * 1000),
        "endTime": int(end.timestamp() * 1000),
        "limit": limit,
    }

    while True:
        response = client.filter_log_events(**kwargs)
        events.extend(response.get("events", []))
        next_token = response.get("nextToken")
        if not next_token or len(events) >= limit:
            break
        kwargs["nextToken"] = next_token

    return events


def render_ui():

    st.set_page_config(
        page_title="CloudWatch Log Analyzer",
        page_icon="📊",
        layout="wide"
    )

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
        with st.spinner("Fetching logs from CloudWatch..."):
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
        with st.spinner("Analyzing logs with Amazon Bedrock..."):
            answer = analyze_logs(
                region,
                logs,
                question
            )

        # 4. Display AI response
        st.subheader("🤖 Bedrock Analysis")
        st.write(answer)


if __name__ == "__main__":
    # Allow running directly via `python app.py`, which re-launches
    # itself under `streamlit run` bound to 0.0.0.0:8082 so the UI is
    # reachable from outside the host (e.g. an EC2 instance).
    if st.runtime.exists():
        render_ui()
    else:
        from streamlit.web import cli as stcli

        sys.argv = [
            "streamlit",
            "run",
            sys.argv[0],
            "--server.address=0.0.0.0",
            "--server.port=8082",
        ]
        sys.exit(stcli.main())