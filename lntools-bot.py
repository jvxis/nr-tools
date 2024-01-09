import subprocess
import telebot
import requests
import json
import shutil
import sys
sys.path.append("..")
import os
from config import *

# Your Telegram bot token
TELEGRAM_BOT_TOKEN = "YOUR-TELEGRAM-BOT-TOKEN"

# Emoji constants
SUCCESS_EMOJI = "✅"
ERROR_EMOJI = "❌"
MONEY_EMOJI = "💰"
PAY_EMOJI = "💸"
ATTENTION_EMOJI = "⚠️"

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
print("Bot LNtools started")

@bot.message_handler(commands=['start'])
def start(message):
    welcome_message = (
        "Welcome to LNtools Bot!\n\nYou can use the /help command to see the list of available commands and their descriptions.\n"
    )
    bot.reply_to(message, welcome_message)


@bot.message_handler(commands=['help'])
def help_command(message):
    help_text = (
        "Available Commands:\n"
        "/onchainfee <amount> <fee_per_vbyte> - Calculate on-chain fee\n"
        "/pay <payment_request> - Pay a Lightning invoice\n"
        "/invoice <amount> <message> <expiration_seconds> - Create a Lightning invoice\n"
        "/bckliquidwallet - Backup Liquid wallet\n"
        "/newaddress - Get a new onchain address\n"
    )
    bot.reply_to(message, help_text)


def get_lncli_utxos():
    command = f"{PATH_TO_UMBREL}/scripts/app compose lightning exec lnd lncli listunspent --min_confs=3"
    process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, error = process.communicate()
    output = output.decode("utf-8")

    utxos = []

    try:
        data = json.loads(output)
        utxos = data.get("utxos", [])
    except json.JSONDecodeError as e:
        print(f"Error decoding lncli output: {e}")
    print(f"Utxos:{utxos}")
    return utxos

# Calculate transaction size in vBytes
def calculate_transaction_size(utxos_needed):
    inputs_size = utxos_needed * 57.5  # Each UTXO is 57.5 vBytes
    outputs_size = 2 * 43  # Two outputs of 43 vBytes each
    overhead_size = 10.5  # Overhead of 10.5 vBytes
    total_size = inputs_size + outputs_size + overhead_size
    return total_size

# Update the function to use lncli
def calculate_utxos_required_and_fees(amount_input, fee_per_vbyte):
    utxos = get_lncli_utxos()
    total = sum(utxo["amount_sat"] for utxo in utxos)
    utxos_needed = 0
    amount_with_fees = amount_input
    print(f"Total UTXOS: {total} Sats")
    print(f"Amount: {amount_input} Sats")
    if total < amount_input:
        return -1, 0

    for utxo in utxos:
        utxos_needed += 1
        transaction_size = calculate_transaction_size(utxos_needed)
        fee_cost = transaction_size * fee_per_vbyte
        amount_with_fees = amount_input + fee_cost

        if utxo["amount_sat"] >= amount_with_fees:
            break
        amount_input -= utxo["amount_sat"]

    return utxos_needed, fee_cost

def make_invoice(amount_to_pay, message, expire):
    url = LNBITS_URL
    headers = {
        "X-Api-Key": LNBITS_INVOICE_KEY,
        "Content-type": "application/json"
    }

    data = {
        "out": False,
        "amount": amount_to_pay,
        "memo": message,
        "expiry": expire
    }

    # Ensure the payload is formatted as JSON
    payload = json.dumps(data)

    try:
        # Make the POST request
        response = requests.post(url, data=payload, headers=headers)
        response.raise_for_status()  # Raise an exception for 4xx and 5xx status codes

        return response.text

    except requests.exceptions.RequestException as e:
        return f"{ERROR_EMOJI} An error occurred while processing the request: {str(e)}"

# Function to format the response content with emojis
def format_response(response_content):
    # Convert the JSON response to a dictionary
    response_dict = json.loads(response_content)

    # Format the response with emojis
    formatted_hash = f"{SUCCESS_EMOJI} Payment Hash: {response_dict['payment_hash']}\n"
    formatted_request = f"{response_dict['payment_request']}\n"
    #formatted_response += f"{SUCCESS_EMOJI} Checking ID: {response_dict['checking_id']}\n"

    return formatted_hash, formatted_request

def send_long_message(chat_id, long_message):
    max_length = 4096
    for i in range(0, len(long_message), max_length):
        chunk = long_message[i:i+max_length]
        print(chunk)
        bot.send_message(chat_id, chunk)
                
@bot.message_handler(commands=['onchainfee'])
def onchain_fee(message):
    try:
        input_amount = float(message.text.split()[1])
        fee_per_vbyte = float(message.text.split()[2])

        utxos_needed, onchain_fee_cost = calculate_utxos_required_and_fees(input_amount, fee_per_vbyte)

        if utxos_needed >= 0:
            formatted_input_amount = f"{input_amount:,.0f}".replace(",", ".")
            formatted_onchain_fee_cost = f"{onchain_fee_cost:,.0f}".replace(",", ".")
            
            message_text = (
                f"✅ {utxos_needed} UTXOs are required to transfer {formatted_input_amount} satoshis.\n"
                f"💰 The on-chain fee needed for the transaction is: {formatted_onchain_fee_cost} satoshis"
            )
            bot.reply_to(message, message_text)
        else:
            bot.reply_to(message, "🙈 Not enough UTXOs available.")
    except IndexError:
        bot.reply_to(message, "🙋‍ Please provide the amount and fee per vByte after the /onchain-fee command. Ex: /onchain-fee 4000000 74")

@bot.message_handler(commands=['pay'])
def pay_invoice(message):
    chat_id = message.chat.id
    command = message.text.split(' ', 1)
    if len(command) == 2:
        payment_request = command[1]
        print("Paying Invoice...\n")
        bot.send_message(chat_id, f'💸 Paying Invoice {payment_request}...')

        # Replace the command with your actual command
        pay_invoice_cmd = f"{PATH_TO_UMBREL}/scripts/app compose lightning exec lnd lncli payinvoice {payment_request} --force"

        try:
            # Execute the command and capture both stdout and stderr
            print(f"Executing Command:{pay_invoice_cmd}\n\n")
            result = subprocess.run(pay_invoice_cmd, shell=True, capture_output=True, text=True)
            print(f"THIS IS THE RESULT: {result}\n")
            if result.returncode == 1:
            # Capture both stdout and stderr
                output = result.stdout.strip()
                print(f"THIS IS THE OUTPUT: {output}\n")
                bot.send_message(chat_id, "💸 Pay Result Output:\n")
                if 'invoice expired' in output:
                    bot.send_message(chat_id, "⚠️ Sorry This Invoice Expired\n")
                elif 'invoice is already paid' in output:
                    bot.send_message(chat_id, "❌ Sorry Invoice Already Paid\n")
                elif 'Payment status: FAILED, reason: FAILURE_REASON_TIMEOUT' in output:
                    bot.send_message(chat_id, "💤 Sorry Time out. Try again\n")
                elif output is None and 'Payment status: SUCCEEDED' in result:
                    bot.send_message(chat_id, "✅ Invoice Paid\n")
                # Split the output into smaller chunks
                if output is None:
                    send_long_message(chat_id, result)
                else:
                    send_long_message(chat_id, output)
        except Exception as e:
            bot.send_message(chat_id, f"❌ An error occurred: {e}")
    else:
        bot.send_message(chat_id, '🙋 You need to type /pay payment-request')

        
@bot.message_handler(commands=['invoice'])
def invoice(message):
    try:
        input_amount = float(message.text.split()[1])
        memo = message.text.split()[2]
        time = int(message.text.split()[3])
        
        payment_response = make_invoice(input_amount, memo, time)
        hash, request = format_response(payment_response)
        bot.send_message(message.chat.id, f"{PAY_EMOJI} Total Invoice: {input_amount} sats :\n{memo}")
        bot.send_message(message.chat.id, hash)
        bot.send_message(message.chat.id, f"{MONEY_EMOJI} Invoice:")
        bot.send_message(message.chat.id, f"```\n{request}\n```", parse_mode='Markdown')
        bot.send_message(message.chat.id, f"{ATTENTION_EMOJI} This invoice will expire in {(time/3600):.2f} hours")
       
    except IndexError:
        bot.reply_to(message, "🙋‍ Please provide the amount, message and expiration time in seconds after the /invoice command. Ex: /invoice 100000 node-services-payment 1000")

@bot.message_handler(commands=['bckliquidwallet'])
def bckliquidwallet(message):
    try:
        source_folder = BCK_SOURCE_PATH
        destination_folder = BCK_DEST_PATH
        bot.reply_to(message, f"🗄️ Starting Liquid Wallet Backup...")
        print("🗄️ Starting Liquid Wallet Backup...")

        # Check if the destination folder exists, create it if not
        if not os.path.exists(destination_folder):
            bot.reply_to(message, f"📂 Creating folder {destination_folder}...")
            print("📂 Creating folder {destination_folder}...")
            os.makedirs(destination_folder)

        # Copy files from the source folder to the destination folder
        bot.reply_to(message, "💾 Backup started")
        print("💾 Backup started")
        updated_files = []
        def copy_recursive(src, dest):
            for item_name in os.listdir(src):
                source_item = os.path.join(src, item_name)
                destination_item = os.path.join(dest, item_name)

                try:
                    if os.path.isfile(source_item):
                        shutil.copy2(source_item, destination_item)
                        updated_files.append(destination_item)
                    elif os.path.isdir(source_item):
                        if not os.path.exists(destination_item):
                            os.makedirs(destination_item)
                        copy_recursive(source_item, destination_item)
                except Exception as e:
                    print(f"Error copying {source_item} to {destination_item}: {str(e)}")
                    bot.reply_to(message,f"Error copying {source_item} to {destination_item}: {str(e)}")
        
        copy_recursive(source_folder, destination_folder)
        bot.reply_to(message, f"✅ Backup Operation successful. Wallets copied to {destination_folder}")
        print(f"✅ Backup Operation successful. Wallets copied to {destination_folder}")
        bot.reply_to(message, f"✅ Updated Files: {updated_files}")
        print("📂 Updated Files:", updated_files)
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")
        print(f"❌ Error: {str(e)}")


@bot.message_handler(commands=['newaddress'])
def generate_new_address(message):
    #lncli newaddress p2tr
    try:
        output = subprocess.check_output(["./lncli", "newaddress", "p2tr"], universal_newlines=True)
        address_data = json.loads(output)

        if "address" in address_data:
            new_address = address_data["address"]
            bot.reply_to(message, f"New address: {new_address}")
        else:
            bot.reply_to(message, "Error: Unable to retrieve new address.")
    except subprocess.CalledProcessError as e:
        bot.reply_to(message, f"Error: {e}")

@bot.message_handler(commands=['newaddress'])
def generate_new_address(message):
    umbrel_command = f"{PATH_TO_UMBREL}/scripts/app compose lightning exec lnd lncli newaddress p2tr"
    try:
        output = subprocess.check_output(umbrel_command, shell=True, universal_newlines=True)
        address_data = json.loads(output)

        if "address" in address_data:
            new_address = address_data["address"]
            formatted_output = f"New Onchain Address:"
            bot.reply_to(message, formatted_output)
            bot.send_message(message.chat.id, f"```\n{new_address}\n```", parse_mode="Markdown")
        else:
            bot.reply_to(message, "Error: Unable to retrieve new address.")
    except subprocess.CalledProcessError as e:
        bot.reply_to(message, f"Error: {e}")


# Polling loop to keep the bot running
bot.polling(none_stop=True, interval=0, timeout=20)
