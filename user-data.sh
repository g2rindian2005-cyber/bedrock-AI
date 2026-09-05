#!/bin/bash
# EC2 user-data (Amazon Linux 2023) - installs and starts the CloudWatch agent.
#
# This is ALL it does. Python, the venv, the systemd unit and the app itself are
# deployed by hand afterwards (see "Manual deploy" in the README).
#
# The agent tails /var/log/myapp/*.log into the single log group
# /workshop/app/logs. The directory does not have to exist yet - the agent polls
# and picks the files up once the app starts writing them.
set -euxo pipefail

LOG_DIR=/var/log/myapp
CFG=/opt/aws/amazon-cloudwatch-agent/etc/cw-config.json

dnf install -y amazon-cloudwatch-agent

# Created up front so the agent has something to watch and so the app can write
# here later without a root-owned-parent surprise.
mkdir -p "$LOG_DIR"

# run_as_user must be root: the log files are not world-readable, and the
# default cwagent user would fail every read silently.
cat > "$CFG" <<'CFG_JSON'
{
  "agent": {
    "metrics_collection_interval": 60,
    "run_as_user": "root"
  },
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          {
            "file_path": "/var/log/myapp/*.log",
            "log_group_name": "/nareshit/devops",
            "log_stream_name": "{instance_id}",
            "timestamp_format": "%Y-%m-%d %H:%M:%S,%f",
            "timezone": "UTC",
            "retention_in_days": 7
          }
        ]
      }
    }
  }
}
CFG_JSON

# fetch-config loads the file and -s starts the agent; it also survives reboots.
/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
  -a fetch-config -m ec2 -s -c file:"$CFG"

/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a status
