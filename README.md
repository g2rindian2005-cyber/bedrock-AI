# Bedrock CloudWatch Log Analyzer

A Streamlit app that fetches AWS CloudWatch Logs and uses Amazon Bedrock
(via LangChain) to analyze them and answer natural-language questions
about errors and root causes.

## Architecture Flow

```mermaid
flowchart TD
    A[User] -->|Selects region, log group, date/time range, question| B[Streamlit UI<br/>app.py]

    B -->|list_log_groups region| B
    B -->|logs:DescribeLogGroups| D[(Amazon CloudWatch Logs)]
    D -->|Available log groups| B

    B -->|fetch_logs / fetch_logs_by_date| B
    B -->|logs:FilterLogEvents| D
    D -->|Log events + timestamps| B

    B -->|Display logs table| A

    B -->|logs + question| E[cw_lang.py<br/>Bedrock analysis layer]
    E -->|ChatBedrockConverse.invoke<br/>amazon.nova-lite-v1:0| F[(Amazon Bedrock)]
    F -->|Root cause + fix + evidence| E
    E -->|Structured analysis| B

    B -->|Display AI analysis| A
```

## Components

- **`app.py`** — Streamlit UI + CloudWatch integration layer (`boto3`)
  in one file. Lists log groups (`list_log_groups`) and fetches log
  events either by relative hours (`fetch_logs`) or by a specific
  calendar date (`fetch_logs_by_date`). `render_ui()` builds the page
  (region, log group, time range, question), and `__main__` launches
  it under Streamlit bound to `0.0.0.0:8082` so it's reachable
  externally (e.g. from an EC2 instance).
- **`cw_lang.py`** — Bedrock/LangChain integration layer. Sends the
  fetched logs plus the user's question to `amazon.nova-lite-v1:0` via
  `ChatBedrockConverse` and returns a structured analysis (summary,
  evidence, root cause, recommended fix, confidence).

## Setup

```bash
pip install -r requirements.txt
python app.py
```

This starts Streamlit listening on `0.0.0.0:8082`, so the UI is
reachable at `http://<host-ip>:8082`. Equivalent manual command:

```bash
streamlit run app.py --server.address 0.0.0.0 --server.port 8082
```


Requires AWS credentials configured locally (`aws configure` or
environment variables) with permissions for:
- `logs:DescribeLogGroups`
- `logs:FilterLogEvents`
- `bedrock:InvokeModel` (for `amazon.nova-lite-v1:0` in the selected region)
