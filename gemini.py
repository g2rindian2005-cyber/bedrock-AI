from google import genai


def analyze_logs(region, logs, question):

    client = genai.Client(
        api_key=""
    )

    prompt = f"""
You are an expert Site Reliability Engineer (SRE) with deep experience
debugging distributed systems from raw log output. You are thorough,
specific, and never give vague or generic answers.

## CloudWatch Logs

'''
{logs}
'''

## Question

{question}

## Instructions

Analyze the logs above line by line and answer the question with concrete
evidence from the logs.

Quote the exact error lines/timestamps you relied on.

Only include relevant error logs in the Evidence section.

In the Recommended Fix section, list troubleshooting steps in logical order
and suggest quick connectivity tests such as telnet or nc.

If the application does not retry failed connections, mention adding retry logic.

Do not give a generic or high-level answer.

Be specific to what is actually present in these logs.

If the logs do not contain enough information to be certain, say so explicitly
and list what additional data/logs would be required.

Respond in this exact structure:

Summary
One or two sentences describing what happened.

Evidence
- Bullet list of the specific log lines/timestamps/error codes that support your analysis.

Root Cause
The most likely root cause, explained clearly and specifically.

Recommended Fix
Concrete, actionable steps to resolve the issue.

Confidence
High / Medium / Low, with a one-line justification.
"""

    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=prompt
    )

    return response.text
