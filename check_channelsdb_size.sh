#!/bin/bash

# Replace /path_to_umbrel with the path for your Umbrel Directory
file_path="/path_to_umbrel/app-data/lightning/data/lnd/data/graph/mainnet/channel.db"

# Setup with the size that you usually restart LND
threshold_size="12000000000"  # 12 GB in bytes

#Setup Telegram bot
TOKEN="BOT_TOKEN"
CHATID="CHAT_ID"
#Replace with your Node Name
NODE="NODE_NAME"


# push message to TG bot
pushover() {
    msg=$(echo -e "🤖 Check LND Database $NODE\n$1")
    curl -s \
    -d parse_mode="HTML" \
    -d text="$msg" \
    -d chat_id="$CHATID" \
    https://api.telegram.org/bot$TOKEN/sendmessage > /dev/null 2>&1
}

pushover "🔎 Checking LND Database..."

# Echo current date and time
echo "Checking Channel DB size at $(date)"

# Check if the file exists
if [ -e "$file_path" ]; then
    # Get the size of the file in bytes
    file_size=$(stat -c %s "$file_path")

    # Compare the file size with the threshold
    if [ "$file_size" -gt "$threshold_size" ]; then
        echo "Channel DB is $file_size. Restart LND  needed"  # Send message if size is greater than 12 GB
        pushover "⚠️  Channel DB is $file_size. Restarting LND..."
        sleep 60 # Wait 1 min to restart LND
        /bin/bash /path_to_umbrel/scripts/app restart lightning #if you just want to reboot, only replace the line to reboot
        sleep 600
        echo "LND Restarted"
        pushover "✅ LND Restarted."
        sleep 900
        echo "Restarting LIT service"
        pushover "Restarting LIT Service..."
        /bin/bash /path_to_umbrel/scripts/app restart lightning-terminal
        sleep 30
        echo "LIT Restarted"
        pushover "✅ LIT Restarted."
    else
        echo "✅ File size is $file_size. Which is within the acceptable range."
        pushover "✅ File size is $file_size. Which is within the acceptable range."
    fi
else
    echo "File not found: $file_path"
fi
