#LNDG Auto-REBAL 0n/Off Trigger - Version Umbrel Users
#Based on the code https://github.com/TrezorHannes/Lightning-Python-Tools/blob/dev/LNDg/mempool_rebalancer_trigger.py
#Insert the code on your Crontab
#Example to run on each 30 minutes:*/30 * * * * /usr/bin/python3 /home/<user>/lndg_rebal_trigger.py >> /home/<user>/lndg-trigger.log 2>&1 

import requests
import time
import datetime
import telebot

#Replace with your Telegram Bot Token
TELEGRAM_TOKEN = "YOUR BOT TOKEN"
#Replace with your Chat ID
CHATID="YOUR TELEGRAM CHAT ID"
# Initialize Telebot with your Telegram bot token
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Get the current timestamp
def get_current_timestamp():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# Variables
MEMPOOL_API_URL = 'https://mempool.space/api/v1/fees/recommended'
#Umbrel users Only
AR_ENABLED_API_URL = 'http://10.21.21.75:8889/api/settings/AR-Enabled/?format=api'
MEMPOOL_FEE_THRESHOLD = 150  # Adjust this value as needed

# LNDG Username and Password from Umbrel Store
username = "lndg-admin"
password = "YOUR LNDG UMBREL STORE PASSWORD"

# Error classes
class MempoolAPIError(Exception):
    """Represents an error when interacting with the Mempool API."""

    def __init__(self, message, status_code=None, response_data=None):
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data

class LNDGAPIError(Exception):
    """Represents an error when interacting with the LNDg API."""

    def __init__(self, message, status_code=None, response_data=None):
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data

def send_telegram_message(message):
    bot.send_message(CHATID, message)

def check_mempool_fees():
    """Checks the mempool API and adjusts LNDg AR-Enabled setting if necessary."""
    try:
        response = requests.get(MEMPOOL_API_URL)
        response.raise_for_status()  # Raise exception for HTTP errors

        data = response.json()
        if data:
            half_hour_fee = data['halfHourFee']
            message = f"{get_current_timestamp()}: 🚗 [MEMPOOL] Half-hour mempool fee: {half_hour_fee} sats/vB"
            print(message)
            send_telegram_message(message)
            if int(half_hour_fee) > MEMPOOL_FEE_THRESHOLD:
                print("⚠️ Half-hour mempool fee is too high. Turning LNDG AR Off")
                send_telegram_message("⚠️ Half-hour mempool fee is too high. Turning LNDG AR Off")
                return False
            else:
                print("🙌 Half-hour mempool fee is ok. Keeping LNDG AR ON")
                send_telegram_message("🙌 Half-hour mempool fee is ok. Keeping LNDG AR ON")
                return True
        else:
            return None

    except requests.exceptions.RequestException as e:
        raise MempoolAPIError("Mempool API unavailable") from e
    return None

def adjust_ar_enabled(ar_enabled):
    timestamp = get_current_timestamp()
    # Convert the boolean ar_enabled to "1" for True or "0" for False
    ar_enabled_str = "1" if ar_enabled else "0"

    try:
        response = requests.put(AR_ENABLED_API_URL, json={"value": ar_enabled_str}, auth=(username, password))
        
        if response.status_code == 200:
            message = f"{timestamp}: ✅ AR-Enabled setting adjusted to {ar_enabled_str}"
            print(message)
            send_telegram_message(message)
        else:
            message = f"{timestamp}: ❌ Failed to adjust AR-Enabled setting to {ar_enabled_str}: Status Code {response.status_code}"
            print(message)
            send_telegram_message(message)

    except requests.exceptions.RequestException as e:
        message = f"{timestamp}: ❌ LNDg API request failed: {e}"
        print(message)
        send_telegram_message(message)
        raise LNDGAPIError("LNDg API unavailable") from e

if __name__ == "__main__":
    print("⚡️LNDG Auto-Rebal Trigger⚡️")
    send_telegram_message("⚡️LNDG Auto-Rebal Trigger⚡️")
    print("🔎Checking Mempool Fee...")
    send_telegram_message("🔎Checking Mempool Fee...")
    # Check mempool fees
    mempool_fees_ok = check_mempool_fees()

    # Adjust AR-Enabled setting if necessary
    if mempool_fees_ok is not None:
        if mempool_fees_ok:
            ar_enabled = True
        else:
            ar_enabled = False
        adjust_ar_enabled(ar_enabled)

