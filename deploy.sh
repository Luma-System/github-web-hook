#!/bin/sh

. "$(dirname "$0")/.env"

# Fail on error
set -e

echo "Starting deployment..."

# Force pull latest changes
# git reset --hard HEAD
git pull --force

# Rebuild and restart containers
# docker compose up --build -d

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
