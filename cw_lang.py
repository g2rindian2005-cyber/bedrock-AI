from langchain_aws import ChatBedrockConverse


def analyze_logs(region, logs, question):

    llm = ChatBedrockConverse(
        model="amazon.nova-lite-v1:0",
        region_name=region,
        max_tokens=1000,
        temperature=0.2
    )

    prompt = f"""
You are an expert Site Reliability Engineer (SRE) with deep experience
debugging distributed systems from raw log output. You are thorough,
specific, and never give vague or generic answers.

## CloudWatch Logs
```
{logs}
```

## Question
{question}

## Instructions
Analyze the logs above line by line and answer the question with concrete
evidence from the logs (quote the exact error lines/timestamps you relied on).
Do not give a generic or high-level answer — be specific to what is actually
present in these logs. If the logs do not contain enough information to be
certain, say so explicitly and list what additional data/logs you would need.

Respond in this exact structure:

**Summary**
One or two sentences describing what happened.

**Evidence**
- Bullet list of the specific log lines/timestamps/error codes that support your analysis.

**Root Cause**
The most likely root cause, explained clearly and specifically.

**Recommended Fix**
Concrete, actionable steps to resolve the issue (code changes, config changes,
infra changes, etc.). Avoid generic advice like "check your configuration" —
name the specific configuration, parameter, or resource involved.

**Confidence**
High / Medium / Low, with a one-line justification.
"""

    response = llm.invoke(prompt)

    return response.content