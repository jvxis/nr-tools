#!/bin/bash
# Please set up a Cron to run this code daily
# You need: sudo apt install smartmontools
# Telegram bot configuration
TOKEN="YOUR_TELEGRAM_TOKEN"
CHATID="YOUR_TELEGRAM_CHAT_ID"
TELEGRAM_URL="https://api.telegram.org/bot$TOKEN/sendMessage"

# Function to get NVMe info and format the output
get_nvme_info() {
  local nvme_device=$1
  local nvme_data=$(sudo smartctl -a /dev/$nvme_device)

  # Extract relevant fields
  model_number=$(echo "$nvme_data" | grep "Model Number" | awk '{print $3}')
  health=$(echo "$nvme_data" | grep "SMART overall-health self-assessment test result" | awk '{print $6}')
  critical_warning=$(echo "$nvme_data" | grep "Critical Warning" | awk '{print $3}')
  temperature=$(echo "$nvme_data" | grep "Temperature:" | awk '{print $2, $3}')
  percentage_used=$(echo "$nvme_data" | grep "Percentage Used" | awk '{print $3}')
  log_errors=$(echo "$nvme_data" | grep "Error Information Log Entries" | awk '{print $5}')

  # Prepare plain text message with newlines
  local message="💾 Checking NVMEs Health"$'\n'
  message+="NVMe Device: /dev/$nvme_device"$'\n'
  message+="Model Number: $model_number"$'\n'
  message+="Overall Health: $health"$'\n'
  message+="Critical Warnings: $critical_warning"$'\n'
  message+="Temperature: $temperature"$'\n'
  message+="Lifespan: $percentage_used"$'\n'
  message+="Log Error Entries: $log_errors"

  # Escapando caracteres especiais no MarkdownV2
  message=$(echo "$message" | sed 's/\./\\./g; s/-/\\-/g; s/_/\\_/g; s/\!/\\!/g')


  # Add warning if health is not PASSED
  if [[ "$health" != "PASSED" ]]; then
    message+="⚠️ WARNING: NVMe /dev/$nvme_device HAS HEALTH ISSUES! ⚠️"
  fi

  # Return the message
  echo "$message"
}

# Function to send message to Telegram bot
send_to_telegram() {
  local message=$1
  curl -s -X POST "$TELEGRAM_URL" -d chat_id="$CHATID" -d text="$message" -d parse_mode="MarkdownV2"
}
# Replace with your NVMEs
# Get status for both nvme0 and nvme1
nvme0_info=$(get_nvme_info "nvme0")
nvme1_info=$(get_nvme_info "nvme1")

# Send messages to Telegram
send_to_telegram "$nvme0_info"
send_to_telegram "$nvme1_info"

