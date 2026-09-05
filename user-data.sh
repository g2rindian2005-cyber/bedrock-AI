#!/bin/bash

# EC2 User Data - Amazon Linux 2023
# Installs and starts the CloudWatch Agent

set -euxo pipefail

LOG_DIR=/var/log/myapp
CFG=/opt/aws/amazon-cloudwatch-agent/bin/config.json

# Install CloudWatch Agent
yum install amazon-cloudwatch-agent -y

# Create application log directory
mkdir -p "$LOG_DIR"

# Create CloudWatch Agent configuration
cat > "$CFG" <<'CFG_JSON'
{
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          {
            "file_path": "/var/log/myapp/*.log",
            "log_group_name": "LOG-FROM-EC2",
            "log_stream_name": "{instance_id}",
            "retention_in_days": 5,
            "run_as_user": "root"
          }
        ]
      }
    }
  }
}
CFG_JSON

# Load configuration and start CloudWatch Agent
/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl \
  -a fetch-config \
  -m ec2 \
  -c file:"$CFG" \
  -s

# Check agent status
/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a status
