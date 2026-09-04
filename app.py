import boto3
from datetime import datetime, timedelta, timezone


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