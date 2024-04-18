import telebot
import os
import time
import subprocess
import json
import requests
channel = 0
filtered_channels = []
success_counter = 1
# Please provide your telegram bot token, and telegram user ID. Strongly recommend to use a new bot token
TELEGRAM_TOKEN = ''
TELEGRAM_USER_ID = ""
# ex /home/user/umbrel
PATH_UMBREL = ""
BOS_PATH = "full_path_to_your_BOS_binary"

LN_CLI = f"{PATH_UMBREL}/scripts/app compose lightning exec lnd lncli listchannels"
# Initialize the Telebot instance with your bot token
bot = telebot.TeleBot(TELEGRAM_TOKEN)
print("Swap-bot started...")
# Function to check if the user is authorized
def is_authorized_user(user_id):
    return str(user_id) == TELEGRAM_USER_ID
# Decorator function for authorization check
def authorized_only(func):
    def wrapper(message):
        if is_authorized_user(message.from_user.id):
            func(message)
        else:
            bot.reply_to(message, "⛔️ You are not authorized to execute this command.")
    return wrapper
def get_node_alias(pub_key):
    try:
        response = requests.get(f"https://mempool.space/api/v1/lightning/nodes/{pub_key}")
        data = response.json()
        return data.get('alias', '')
    except Exception as e:
        return pub_key
def execute_command(command):
    try:
        result = subprocess.run(command, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return result.stdout.decode('utf-8')
    except subprocess.CalledProcessError as e:
        return None
def filter_channels(data):
    channels = data.get('channels', [])
    global filtered_channels
    for channel in channels:
        local_balance = int(channel.get('local_balance', 0))
        capacity = int(channel.get('capacity', 1))
        if local_balance >= 0.3 * capacity:
            filtered_channels.append({
                'remote_pubkey': channel.get('remote_pubkey', ''),
                'local_balance': local_balance,
                'capacity': capacity
            })
    return filtered_channels
@bot.message_handler(commands=['help'])
@authorized_only
def help_command(message):
    help_text = (
        "Available Commands:\n"
        "/swap - The bot will ask you all the info to start the swap process\n"
        
    )
    bot.reply_to(message, help_text)
    
@bot.message_handler(commands=['swap'])
@authorized_only
def swap(message):
    bot.send_message(message.chat.id, "🔄 Starting Swap Out... Please answer all questions.")
    bot.send_message(message.chat.id, "📧 Enter LN address:")
    bot.register_next_step_handler(message, process_ln_address_step)
def process_ln_address_step(message):
    ln_address = message.text
    bot.send_message(message.chat.id, "💰 Enter total amount to transfer:")
    bot.register_next_step_handler(message, process_total_amount_step, ln_address)
def process_total_amount_step(message, ln_address):
    total_amount_to_transfer = message.text
    bot.send_message(message.chat.id, "💸 Enter amount per transaction:")
    bot.register_next_step_handler(message, process_amount_step, ln_address, total_amount_to_transfer)
def process_amount_step(message, ln_address, total_amount_to_transfer):
    amount = message.text
    bot.send_message(message.chat.id, "⌛ Enter the interval in seconds between transactions:")
    bot.register_next_step_handler(message, process_interval_step, ln_address, total_amount_to_transfer, amount)
def process_interval_step(message, ln_address, total_amount_to_transfer, amount):
    interval = message.text
    bot.send_message(message.chat.id, "🫰 Enter the max fee rate in ppm:")
    bot.register_next_step_handler(message, process_fee_rate_step, ln_address, total_amount_to_transfer, amount, interval)
def process_fee_rate_step(message, ln_address, total_amount_to_transfer, amount, interval):
    fee_rate = message.text
    bot.send_message(message.chat.id, "🗯️ Payment Message:")
    bot.register_next_step_handler(message, process_payment_message_step, ln_address, total_amount_to_transfer, amount, interval, fee_rate)
def process_payment_message_step(message, ln_address, total_amount_to_transfer, amount, interval, fee_rate):
    payment_message = message.text
    bot.send_message(message.chat.id, "🫗 Out Peer Alias or Pubkey (type none for no specific source):")
    bot.register_next_step_handler(message, process_peer_step, ln_address, total_amount_to_transfer, amount, interval, fee_rate, payment_message)
def process_peer_step(message, ln_address, total_amount_to_transfer, amount, interval, fee_rate, payment_message):
    peer = message.text if message.text else None
    if not peer or peer=="none":
        peer = None
        bot.send_message(message.chat.id, "📢 No peer specified, trying first with heavy outbound peers...")
        bot.send_message(message.chat.id, "📋 Getting peers with local balance >= 30%...")
        lncli_command = LN_CLI
        command_output = execute_command(lncli_command)
        data = json.loads(command_output)
        filtered_channels = filter_channels(data)
    interval_seconds = int(interval)
    total_amount = int(total_amount_to_transfer)
    execute_transaction(message.chat.id, ln_address, amount, total_amount, interval_seconds, fee_rate, payment_message, peer)
def execute_transaction(chat_id, ln_address, amount, total_amount, interval_seconds, fee_rate, payment_message, peer):
    global channel
    global success_counter
    while total_amount > 0:
        try:
            amount = int(amount)
        except ValueError:
            bot.send_message(chat_id, "🛑 Invalid amount. Please enter a valid number. Please start again.")
            break
        if peer is not None:
            comando = f"{BOS_PATH}/bos send {ln_address} --amount {amount} --message {payment_message} --max-fee-rate {fee_rate} --out {peer}"
        else:
            if channel < len(filtered_channels):
                comando = f"{BOS_PATH}/bos send {ln_address} --amount {amount} --message {payment_message} --max-fee-rate {fee_rate} --out {get_node_alias(filtered_channels[channel]['remote_pubkey'])}"
            else:
                comando = f"{BOS_PATH}/bos send {ln_address} --amount {amount} --message {payment_message} --max-fee-rate {fee_rate}"
        bot.send_message(chat_id, f"▶️ Executing command: {comando}")
        output = subprocess.run(comando, shell=True, capture_output=True, text=True)
        if "success" in output.stdout:
            total_amount -= amount
            remaining_amount_message = f"💲Remaining amount: {total_amount}"
            bot.send_message(chat_id, "✅ Transaction successful.")
            for chunk in [output.stdout[i:i+4096] for i in range(0, len(output.stdout), 4096)]:
                bot.send_message(chat_id, chunk)
                if remaining_amount_message:
                    bot.send_message(chat_id, remaining_amount_message)
                    remaining_amount_message = None
            if peer is None:
                if channel < len(filtered_channels):
                    success_counter += amount
                    remain_capacity_tx = (int(filtered_channels[channel]['local_balance']) - success_counter) / int(filtered_channels[channel]['capacity'])
                    if remain_capacity_tx >= 0.3 and total_amount > 0:
                        bot.send_message(chat_id, f"Trying again as remain local balance is higher than 30%: {get_node_alias(filtered_channels[channel]['remote_pubkey'])}")
                    else:
                        channel += 1
            if total_amount > 0:
                bot.send_message(chat_id, f"⌛ Waiting {interval_seconds} seconds to execute next transaction")
                time.sleep(interval_seconds)
            else:
                bot.send_message(chat_id, f"✅ Transfer Finished - Bot waiting for new commands...")
        else:
            bot.send_message(chat_id, f"❌ Transaction failed. {output.stderr}. Retrying...")
            channel += 1
            success_counter = 0
            bot.send_message(chat_id, "⌛ Waiting in 5 seconds to try again")
            time.sleep(5)
# Start the bot
bot.polling()
