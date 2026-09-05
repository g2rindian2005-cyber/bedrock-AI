"""
Log Forge - EC2 web app that manufactures backdated application logs.

Every browser hit generates events across the last N days (today, yesterday, the
day before...), appends them to per-date files, and streams them to CloudWatch
Logs in the background. That is all it does.

This app never calls Bedrock. Analysis is a separate, deliberate step: run
02_direct_analysis/analyze_logs.py against the log group once logs are flowing.

    python app.py                          # http://localhost:8080
    LOG_DIR=./logs SHIP_TO_CLOUDWATCH=0 python app.py    # local, no AWS

SECURITY: there is no authentication unless APP_TOKEN is set. See the note in
create_app() and the README before exposing this to 0.0.0.0.
"""

from __future__ import annotations

import hmac
import os
import random
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
from flask import Flask, jsonify, make_response, render_template, request

sys.path.insert(0, str(Path(__file__).parent))

from generator import MAX_DAYS_BACK, ROUTES, generate_visit, window_summary  # noqa: E402
from shipper import CloudWatchShipper, LogFileWriter, NullShipper  # noqa: E402

LOG_DIR = os.environ.get("LOG_DIR", "/var/log/myapp")
LOG_GROUP = os.environ.get("LOG_GROUP", "/workshop/app/logs")
REGION = os.environ.get("AWS_REGION", "us-east-1")
DAYS_BACK = min(int(os.environ.get("DAYS_BACK", "7")), MAX_DAYS_BACK)
SHIP = os.environ.get("SHIP_TO_CLOUDWATCH", "1") == "1"
# Built-in default so the app is gated without touching /etc/logforge.env.
# `or` rather than a get() default on purpose: the systemd EnvironmentFile ships
# APP_TOKEN= (empty), and an empty value would otherwise disable the gate.
# This value is committed to git, so treat it as a speed bump, not a secret -
# the security group is what actually protects this instance.
APP_TOKEN = os.environ.get("APP_TOKEN") or ""


def instance_id() -> str:
    """IMDSv2, with a local fallback so the app runs off-EC2 too."""
    if os.environ.get("INSTANCE_ID"):
        return os.environ["INSTANCE_ID"]
    try:
        import urllib.request

        req = urllib.request.Request(
            "http://169.254.169.254/latest/api/token",
            method="PUT",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"},
        )
        token = urllib.request.urlopen(req, timeout=1).read().decode()
        req = urllib.request.Request(
            "http://169.254.169.254/latest/meta-data/instance-id",
            headers={"X-aws-ec2-metadata-token": token},
        )
        return urllib.request.urlopen(req, timeout=1).read().decode()
    except Exception:
        return f"local-{os.uname().nodename if hasattr(os, 'uname') else 'dev'}"


def build_shipper():
    if not SHIP:
        return NullShipper("shipping disabled (SHIP_TO_CLOUDWATCH=0)")
    try:
        client = boto3.client("logs", region_name=REGION)
        shipper = CloudWatchShipper(client, LOG_GROUP, instance_id())
        shipper.start()
        return shipper
    except (NoCredentialsError, ClientError, BotoCoreError) as err:
        return NullShipper(f"CloudWatch unavailable: {err}"[:300])


def create_app() -> Flask:
    app = Flask(__name__)
    writer = LogFileWriter(LOG_DIR)
    shipper = build_shipper()
    rng = random.Random()
    lock = threading.Lock()
    state = {"visits": 0, "generated": 0, "started": datetime.now(tz=timezone.utc)}

    if not APP_TOKEN:
        app.logger.warning(
            "APP_TOKEN is not set - every endpoint is open to anyone who can reach "
            "this port. Restrict the security group to your own IP, or set APP_TOKEN."
        )
    elif APP_TOKEN == "veera@123":
        app.logger.warning(
            "APP_TOKEN is the built-in default, which is public in the git repo. "
            "Anyone who reads the source can get in. Override it in "
            "/etc/logforge.env and restrict the security group to your own IP."
        )

    # ---------------- auth (opt-in) ---------------- #
    @app.before_request
    def gate():
        if not APP_TOKEN:
            return None
        supplied = (
            request.headers.get("X-App-Token")
            or request.args.get("token")
            or request.cookies.get("app_token")
            or ""
        )
        if hmac.compare_digest(supplied, APP_TOKEN):
            return None
        return jsonify(error="unauthorized", hint="append ?token=... or send X-App-Token"), 401

    @app.after_request
    def persist_token(resp):
        token = request.args.get("token")
        if APP_TOKEN and token and hmac.compare_digest(token, APP_TOKEN):
            resp.set_cookie("app_token", token, httponly=True, samesite="Lax")
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        return resp

    # ---------------- log generation ---------------- #
    def do_visit(route: str) -> dict:
        events = generate_visit(route, days_back=DAYS_BACK, rng=rng)
        per_day = writer.write(events)
        queued = shipper.enqueue(events)
        with lock:
            state["visits"] += 1
            state["generated"] += len(events)
        levels: dict[str, int] = {}
        for ev in events:
            levels[ev.level] = levels.get(ev.level, 0) + 1
        return {
            "route": route,
            "events_generated": len(events),
            "days_touched": len(per_day),
            "per_day": dict(sorted(per_day.items(), reverse=True)),
            "by_level": levels,
            "cloudwatch": queued,
        }

    # ---------------- routes ---------------- #
    @app.get("/")
    def index():
        # Loading the page is itself an access, so it generates logs.
        result = do_visit("/")
        html = render_template(
            "index.html",
            days_back=DAYS_BACK,
            log_group=LOG_GROUP,
            region=REGION,
            routes=ROUTES,
            boot=result,
        )
        return make_response(html)

    @app.post("/api/visit")
    def api_visit():
        route = (request.json or {}).get("route", "/api/orders")
        if route not in ROUTES and route != "/":
            return jsonify(error=f"unknown route {route}"), 400
        return jsonify(do_visit(route))

    @app.post("/api/burst")
    def api_burst():
        """Several visits at once, for filling a window quickly."""
        n = max(1, min(int((request.json or {}).get("count", 10)), 100))
        total, per_day = 0, {}
        for _ in range(n):
            r = do_visit(rng.choice(ROUTES))
            total += r["events_generated"]
            for day, count in r["per_day"].items():
                per_day[day] = per_day.get(day, 0) + count
        return jsonify(visits=n, events_generated=total,
                       per_day=dict(sorted(per_day.items(), reverse=True)))

    @app.get("/api/stats")
    def api_stats():
        now = datetime.now(tz=timezone.utc)
        counts = writer.day_counts()
        days = []
        for day in window_summary(DAYS_BACK, now):
            days.append({**day, "events": counts.get(day["date"], 0)})
        return jsonify(
            log_group=LOG_GROUP,
            region=REGION,
            log_dir=LOG_DIR,
            instance=instance_id(),
            days_back=DAYS_BACK,
            visits=state["visits"],
            events_generated=state["generated"],
            uptime_seconds=int((now - state["started"]).total_seconds()),
            days=days,
            older_files={k: v for k, v in counts.items()
                         if k not in {d["date"] for d in days}},
            shipper=shipper.stats,
        )

    @app.get("/api/logs")
    def api_logs():
        day = request.args.get("date") or datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        try:
            datetime.strptime(day, "%Y-%m-%d")
        except ValueError:
            return jsonify(error="date must be YYYY-MM-DD"), 400
        limit = max(1, min(int(request.args.get("limit", 200)), 2000))
        return jsonify(date=day, lines=writer.tail(day, limit),
                       file=str(writer.path_for(day)))

    @app.get("/health")
    def health():
        return jsonify(status="ok", shipping=shipper.stats["enabled"])

    app.config["SHIPPER"] = shipper
    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    host = os.environ.get("HOST", "0.0.0.0")

    print(f"Log Forge on http://{host}:{port}  (log group {LOG_GROUP}, {DAYS_BACK} days back)")
    app.run(host=host, port=port, threaded=True)