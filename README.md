# Bedrock CloudWatch Log Analyzer

A Streamlit app that fetches AWS CloudWatch Logs and uses Amazon Bedrock
(via LangChain) to analyze them and answer natural-language questions
about errors and root causes.

## Architecture Flow

```mermaid
flowchart TD
    A[User] -->|Selects region, log group, date/time range, question| B[Streamlit UI<br/>streamlite.py]

    B -->|list_log_groups region| C[app.py<br/>CloudWatch fetch layer]
    C -->|logs:DescribeLogGroups| D[(Amazon CloudWatch Logs)]
    D -->|Available log groups| B

    B -->|fetch_logs / fetch_logs_by_date| C
    C -->|logs:FilterLogEvents| D
    D -->|Log events + timestamps| C
    C -->|Formatted log events| B

    B -->|Display logs table| A

    B -->|logs + question| E[cw_lang.py<br/>Bedrock analysis layer]
    E -->|ChatBedrockConverse.invoke<br/>amazon.nova-lite-v1:0| F[(Amazon Bedrock)]
    F -->|Root cause + fix + evidence| E
    E -->|Structured analysis| B

    B -->|Display AI analysis| A
```

## Components

- **`streamlite.py`** — Streamlit UI. Lets the user pick a region, log
  group (auto-populated from the account), a time range (relative hours
  or a specific date), and a question to ask about the logs.
- **`app.py`** — CloudWatch integration layer (`boto3`). Lists log
  groups (`list_log_groups`) and fetches log events either by relative
  hours (`fetch_logs`) or by a specific calendar date (`fetch_logs_by_date`).
- **`cw_lang.py`** — Bedrock/LangChain integration layer. Sends the
  fetched logs plus the user's question to `amazon.nova-lite-v1:0` via
  `ChatBedrockConverse` and returns a structured analysis (summary,
  evidence, root cause, recommended fix, confidence).

## Setup

```bash
pip install -r requirements.txt
streamlit run streamlite.py
```

Requires AWS credentials configured locally (`aws configure` or
environment variables) with permissions for:
- `logs:DescribeLogGroups`
- `logs:FilterLogEvents`
- `bedrock:InvokeModel` (for `amazon.nova-lite-v1:0` in the selected region)
