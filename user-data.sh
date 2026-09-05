#!/bin/bash
set -euxo pipefail

# Variables
LOG_DIR=/var/log/myapp
CFG=/opt/aws/amazon-cloudwatch-agent/etc/config.json

# Install CloudWatch Agent (if not already installed)
yum install -y amazon-cloudwatch-agent

# Create log directory
mkdir -p "$LOG_DIR"

# Create CloudWatch Agent config file
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
            "timestamp_format": "%Y-%m-%d %H:%M:%S,%3N",
            "timezone": "UTC",
            "retention_in_days": 7
          }
        ]
      }
    }
  }
}
CFG_JSON

# Add a test log entry with the current timestamp
date "+%Y-%m-%d %H:%M:%S,%3N Test log entry: CloudWatch agent setup successful." >> "$LOG_DIR"/test.log

# Start CloudWatch Agent with the config file
/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
  -a fetch-config -m ec2 -c file:"$CFG" -s

# Show agent status (optional)
/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a status
