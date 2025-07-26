#!/bin/sh

. "$(dirname "$0")/.env"

# Fail on error
set -e

DATE=$(date +%F)
LOG_FILE="./logs/deployments/$DATE.log"
mkdir -p "$(dirname "$LOG_FILE")"

echo "==============================================================================" >> $LOG_FILE
echo "Starting deployment..." >> $LOG_FILE

# Update what to deploy script here

# Force pull latest changes
# git reset --hard HEAD
# git pull --force

# Rebuild and restart containers
# docker compose up --build -d

env | grep '^REPO' >> $LOG_FILE

echo "Deployment complete."

if [ -n "$TELEGRAM_BOT_TOKEN" ] && [ -n "$TELEGRAM_CHAT_ID" ]; then
    hostname=$(hostname)
    commit_info=$(git log -3 --pretty=format:"➕ %s by %an on %cd" --date=format:'%Y-%m-%d %I:%M %p')
    message="✅ $APP_URL: deployed on $hostname:"
    echo "$message"
    echo "$commit_info"
    curl -s -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" \
        -d "chat_id=$TELEGRAM_CHAT_ID" \
        -d "text=$message%0A%0A$commit_info" > /dev/null 2>&1
else
    echo "⚠️ Telegram notification skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set"
fi
