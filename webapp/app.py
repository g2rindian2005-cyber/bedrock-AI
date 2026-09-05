"""
Multicloud DevOps Portal
by Veera Sir, NIT

A small Flask app that records real access logs and error logs for every
request it serves, and writes them to local files on the server only.
No fake/synthetic log generation, no external log shipping, and the logs
are never exposed through the website itself.

    python app.py                          # http://localhost:8080
    LOG_DIR=./logs python app.py           # choose a different log directory

SECURITY: there is no authentication unless APP_TOKEN is set in the
environment. Restrict network access (firewall / security group) to trusted
sources, or set APP_TOKEN, before exposing this beyond localhost.
"""

from __future__ import annotations

import hmac
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from flask import Flask, g, jsonify, render_template, request

LOG_DIR = os.environ.get("LOG_DIR", "/var/log/myapp")
APP_TOKEN = os.environ.get("APP_TOKEN") or ""
MAX_LOG_BYTES = int(os.environ.get("MAX_LOG_BYTES", 10 * 1024 * 1024))  # 10 MB per file
BACKUP_COUNT = int(os.environ.get("LOG_BACKUP_COUNT", 5))


def _build_logger(name: str, filename: str) -> logging.Logger:
    """File-only logger; rotates locally so disk usage stays bounded."""
    Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = RotatingFileHandler(
            Path(LOG_DIR) / filename, maxBytes=MAX_LOG_BYTES, backupCount=BACKUP_COUNT
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


access_logger = _build_logger("access", "access.log")
error_logger = _build_logger("error", "error.log")


def create_app() -> Flask:
    app = Flask(__name__)

    if not APP_TOKEN:
        app.logger.warning(
            "APP_TOKEN is not set - every endpoint is open to anyone who can reach "
            "this port. Restrict network access to trusted sources, or set APP_TOKEN."
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

    # ---------------- real access/error logging ---------------- #
    @app.before_request
    def start_timer():
        g._start = time.monotonic()
        g._request_id = uuid.uuid4().hex[:12]

    @app.after_request
    def log_access(resp):
        duration_ms = int((time.monotonic() - getattr(g, "_start", time.monotonic())) * 1000)
        access_logger.info(
            "request_id=%s %s %s %s %s latency_ms=%d ip=%s",
            getattr(g, "_request_id", "-"),
            request.method,
            request.path,
            resp.status_code,
            request.headers.get("User-Agent", "-"),
            duration_ms,
            request.headers.get("X-Forwarded-For", request.remote_addr or "-"),
        )
        return resp

    @app.errorhandler(Exception)
    def log_error(err):
        error_logger.exception(
            "request_id=%s %s %s error=%s",
            getattr(g, "_request_id", "-"),
            request.method,
            request.path,
            err,
        )
        code = getattr(err, "code", 500)
        if not isinstance(code, int):
            code = 500
        return jsonify(error="internal_error", request_id=getattr(g, "_request_id", "-")), code

    # ---------------- routes ---------------- #
    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/status")
    def api_status():
        return jsonify(
            app="Multicloud DevOps Portal",
            author="Veera Sir, NIT",
            status="ok",
            time=datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
            endpoints=["/health", "/api/status", "/api/logs/access", "/api/logs/error"],
        )

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    # ---------------- database connectivity check ---------------- #
    @app.post("/api/db/test")
    def api_db_test():
        payload = request.get_json(silent=True) or {}
        engine = str(payload.get("engine", "")).lower()
        host = str(payload.get("host", "")).strip()
        port = payload.get("port")
        user = str(payload.get("user", "")).strip()
        password = str(payload.get("password", ""))
        database = str(payload.get("database", "")).strip()

        if engine not in ("mysql", "postgres", "postgresql"):
            return jsonify(error="engine must be 'mysql' or 'postgres'"), 400
        if not host or not user or not database:
            return jsonify(error="host, user, and database are required"), 400

        request_id = getattr(g, "_request_id", "-")
        # Never log the password. Only non-secret connection details.
        target = f"engine={engine} host={host} port={port} db={database} user={user}"

        try:
            elapsed_ms = _test_db_connection(engine, host, port, user, password, database)
        except Exception as err:  # noqa: BLE001 - surface any driver error as a connection failure
            error_logger.error(
                "request_id=%s db_connect_failed %s error=%s",
                request_id, target, err,
            )
            return jsonify(ok=False, error=str(err)), 200

        access_logger.info(
            "request_id=%s db_connect_ok %s latency_ms=%d",
            request_id, target, elapsed_ms,
        )
        return jsonify(ok=True, message="Connection successful", latency_ms=elapsed_ms)

    def _test_db_connection(engine: str, host: str, port, user: str, password: str, database: str) -> int:
        """Attempt a real DB connection. Returns latency in ms, or raises on failure."""
        start = time.monotonic()
        if engine == "mysql":
            import pymysql

            conn = pymysql.connect(
                host=host,
                port=int(port) if port else 3306,
                user=user,
                password=password,
                database=database,
                connect_timeout=5,
            )
            conn.close()
        else:  # postgres / postgresql
            import pg8000

            conn = pg8000.connect(
                host=host,
                port=int(port) if port else 5432,
                user=user,
                password=password,
                database=database,
                timeout=5,
            )
            conn.close()
        return int((time.monotonic() - start) * 1000)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"Multicloud DevOps Portal on http://{host}:{port}  (logs -> {LOG_DIR})")
    app.run(host=host, port=port, threaded=True)
