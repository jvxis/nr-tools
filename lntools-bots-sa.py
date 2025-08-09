import subprocess
import telebot
import requests
import json
import shutil
import sys
from io import StringIO
sys.path.append('/path/to/nr-tools/')
import os
from config import *
import datetime

# Please, before using the bot, enter the necessary paths in the /nr-tools/config.py file
# Attention this is the Standalone version, for Umbrel installations use lntools-bot.py

# Insert your Telegram bot token
TELEGRAM_BOT_TOKEN = "YOUR-TELEGRAM-BOT-TOKEN"
#Get it on https://t.me/userinfobot
TELEGRAM_USER_ID = "YOUR-TELEGRAM-USER-ID" 
BOS_PATH = "path_to_your_BOS_binary"

#LNDG Credentials
AR_ENABLED_API_URL = 'http://SEU_IP:8889/api/settings/AR-Enabled/?format=api'
LNDG_USERNAME = "lndg-admin"
LNDG_PASSWORD = "LNDG_PASSWORD"

# Emoji constants
SUCCESS_EMOJI = "✅"
ERROR_EMOJI = "❌"
MONEY_EMOJI = "💰"
PAY_EMOJI = "💸"
ATTENTION_EMOJI = "⚠️"

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
print("Bot LNtools started")

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

def send_sats(ln_address, amount, message, peer):

    # Validate the amount as a number
    try:
        amount = int(amount)
    except ValueError:
        msg = ("Invalid amount. Please enter a valid number.")
        print(msg)
        return msg
        

    # Build the command with user input
    if peer is not None:
        comando = f"{BOS_PATH}bos send {ln_address} --amount {amount} --message {message} --max-fee-rate 2000 --out {peer}"
    else:
        comando = f"{BOS_PATH}bos send {ln_address} --amount {amount} --message {message} --max-fee-rate 2000"

    print(f"Executing command: {comando}\n")
    output = subprocess.run(comando, shell=True, capture_output=True, text=True)

    # Check if the output contains a success message
    if "success" in output.stdout:
        msg = f"{SUCCESS_EMOJI} Transaction successful. {amount} sats sent to {ln_address}\n{output.stdout}\n"
        print(msg)
        
    else:
        msg = f"{ERROR_EMOJI} Transaction failed! {output.stderr}. Please try again.\n"
        print(msg)
    return msg


def connect_to_node(node_key_address):
    command = f"lncli connect {node_key_address} --timeout 120s"
    print(f"Command:{command}")
    process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, error = process.communicate()
    output = output.decode("utf-8")

    if process.returncode == 0:
        print(f"Successfully connected to node {node_key_address}")
        return process.returncode
    else:
        print(f"Error connecting to node {node_key_address}: {error}")
        return process.returncode


def execute_lnd_command(node_pub_key, fee_per_vbyte, formatted_outpoints, input_amount):
    # Format the command
    command = (
        f"lncli openchannel "
        f"--node_key {node_pub_key} --sat_per_vbyte={fee_per_vbyte} "
        f"{formatted_outpoints} --local_amt={input_amount}"
    )
    print(f"UTXOs: {formatted_outpoints}")
    
    # Option to not use the UTXOs
    #command = (
    #    f"lncli openchannel "
    #    f"--node_key {node_pub_key} --sat_per_vbyte={fee_per_vbyte} "
    #    f"--local_amt={input_amount}"
    #)

    try:
        # Run the command and capture both stdout and stderr in real-time
        print(f"Command: {command}")
        process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        
        line = process.stdout.readline()
        line = line.decode("utf-8").strip()
        combined_output, error = process.communicate()
        combined_output = combined_output.decode("utf-8")
        if "error" in str(line):
            log_content = f"Error: {str(line)}"
            
            return log_content
            
        # Parse the JSON output
        try:
            output_json = json.loads(combined_output)
            funding_txid = output_json.get("funding_txid")
            return funding_txid
        except json.JSONDecodeError as json_error:
            print(f"Error decoding JSON: {json_error}")

            # Save the command and JSON error to a log file
            log_content = f"Command: {command}\nJSON Decode Error: {json_error}\n"
            
            return log_content

    except subprocess.CalledProcessError as e:
        # Handle command execution errors
        print(f"Error executing command: {e}")

        # Save the command and error to a log file
        log_content = f"Command: {command}\nError: {e}\n"
        
        return log_content
# Function Channel Open
def open_channel(pubkey, size, fee_rate):
    # get fastest fee

    # Check UTXOS and Fee Cost
    print("Getting UTXOs, Fee Cost and Outpoints to open the channel")
    utxos_needed, fee_cost, related_outpoints = calculate_utxos_required_and_fees(size,fee_rate)
    # Check if enough UTXOS
    if utxos_needed == -1:
        msg_open = f"There isn't enough confirmed Balance to open a {size} SATS channel"
        print(msg_open)
        return -1, msg_open 
    # Good to open channel
    formatted_outpoints = ' '.join([f'--utxo {outpoint}' for outpoint in related_outpoints])
    print(f"Opening Channel: {pubkey}")
    # Run function to open channel
    funding_tx = execute_lnd_command(pubkey, fee_rate, formatted_outpoints, size)
    if funding_tx is None:
        msg_open = f"Problem to execute the LNCLI command to open the channel."
        print(msg_open)
        return -3, msg_open
    msg_open = f"Channel with {get_node_alias(pubkey)} | {pubkey} opened with funding transaction: {funding_tx} and Fee Cost: {fee_cost} sats"
    print(msg_open)
    return funding_tx, msg_open       

def adjust_ar_enabled(ar_enabled, chat_id):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ar_enabled_str = "1" if ar_enabled else "0"
    try:
        response = requests.put(
            AR_ENABLED_API_URL,
            json={"value": ar_enabled_str},
            auth=(LNDG_USERNAME, LNDG_PASSWORD)
        )
        if response.status_code == 200:
            msg = f"{timestamp}: ✅ AR-Enabled set to {ar_enabled_str}"
        else:
            msg = f"{timestamp}: ❌ Failed to set AR-Enabled to {ar_enabled_str}: Status {response.status_code}"
    except Exception as e:
        msg = f"{timestamp}: ❌ LNDg API request failed: {e}"
    bot.send_message(chat_id, msg)
    
def get_node_alias(pub_key):
    try:
        response = requests.get(f"https://mempool.space/api/v1/lightning/nodes/{pub_key}")
        data = response.json()
        return data.get('alias', '')
    except Exception as e:
        print(f"Error fetching node alias: {str(e)}")
        return ''

def get_lncli_utxos():
    command = f"lncli listunspent --min_confs=3"
    process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, error = process.communicate()
    output = output.decode("utf-8")

    utxos = []

    try:
        data = json.loads(output)
        utxos = data.get("utxos", [])
    except json.JSONDecodeError as e:
        print(f"Error decoding lncli output: {e}")
    
    # Sort utxos based on amount_sat in reverse order
    utxos = sorted(utxos, key=lambda x: x.get("amount_sat", 0), reverse=True)
    
    print(f"Utxos:{utxos}")
    return utxos

def get_utxos():
    command = f"{BOS_PATH}bos utxos --confirmed"
    process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, error = process.communicate()
    output = output.decode("utf-8")
    utxos = {'amounts': [], 'outpoints': []}
    
    if output:
        print(output)
        lines = output.split('\n')
        for line in lines:
            if "amount:" in line:
                amount = float(line.split()[1]) * 100000000
                utxos['amounts'].append(amount)
            if "outpoint:" in line:
                outpoint = str(line.split()[1])
                utxos['outpoints'].append(outpoint)
    
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
    related_outpoints = []
    print(f"Total UTXOS: {total} Sats")
    print(f"Amount: {amount_input} Sats")
    
    if total < amount_input:
        return -1, 0, None

    #for utxo_amount, utxo_outpoint in zip(utxos_data['amounts'], utxos_data['outpoints']):
    for utxo in utxos:
        utxos_needed += 1
        transaction_size = calculate_transaction_size(utxos_needed)
        fee_cost = transaction_size * fee_per_vbyte
        amount_with_fees = amount_input + fee_cost

        related_outpoints.append(utxo['outpoint'])

        if utxo['amount_sat'] >= amount_with_fees:
            break
        channel_size -= utxo['amount_sat']

    return utxos_needed, fee_cost,related_outpoints if related_outpoints else None

def execute_lncli_addinvoice(amt, memo, expiry):
    # Command to be executed
    command = [
        f"lncli",
        "addinvoice",
        "--memo", memo,
        "--amt", amt,
        "--expiry", expiry
    ]

    try:
        # Execute the command and capture the output
        result = subprocess.check_output(command, text=True)
        
        # Parse the JSON output
        output_json = json.loads(result)

        # Extract the required values
        r_hash = output_json.get("r_hash", "")
        payment_request = output_json.get("payment_request", "")

        return r_hash, payment_request

    except subprocess.CalledProcessError as e:
        # Handle any errors that occur during command execution
        print(f"Error executing command: {e}")
        return f"Error executing command: {e}", None

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

@bot.message_handler(commands=['help'])
@authorized_only
def help_command(message):
    help_text = (
        "Available Commands:\n"
        "/onchainfee <amount> <fee_per_vbyte> - Calculate on-chain fee\n"
        "/pay <payment_request> - Pay a Lightning invoice\n"
        "/invoice <amount> <message> <expiration_seconds> - Create a Lightning invoice\n"
        "/bckliquidwallet - Backup Liquid wallet\n"
        "/newaddress - Get a new onchain address\n"
        "/sign <message> - Sign a message\n"
        "/connectpeer <peer address> - connect to a peer\n"
        "/openchannel <public key> <size in sats> <fee rate in sats/vB> - open a channel using UTXOS\n"
        "/lndlog <optional all docker logs parameters> and | grep something - Shows LND logs\n"
        "/sendsats <lnaddress> <amount> <memo> <peer> (optional) - send sats to a lnaddress"
    )
    bot.reply_to(message, help_text)
                
@bot.message_handler(commands=['onchainfee'])
@authorized_only
def onchain_fee(message):
    try:
        input_amount = float(message.text.split()[1])
        fee_per_vbyte = float(message.text.split()[2])

        utxos_needed, onchain_fee_cost, related_outpoints = calculate_utxos_required_and_fees(input_amount, fee_per_vbyte)

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

@bot.message_handler(commands=['sendsats'])
@authorized_only
def send_sats_lnaddress(message):
    try:
        lnaddress = message.text.split()[1]
        amount = message.text.split()[2]
        memo = message.text.split()[3]
        
        # Check if the user provided a peer, otherwise use a default value or handle it as needed
        if len(message.text.split()) > 4:
            peer = message.text.split()[4]
        else:
            peer = None  # You can set a default peer or handle it in your specific way
        
        output = send_sats(lnaddress,amount,memo,peer)
        send_long_message(message.chat.id, output)
        
    except IndexError:
        bot.reply_to(message, "🙋‍ Please provide the lnaddress amount message and peer (Pub Key or Alias) after the /sendsats command.")    

@bot.message_handler(commands=['pay'])
@authorized_only
def pay_invoice(message):
    chat_id = message.chat.id
    command = message.text.split(' ', 1)
    if len(command) == 2:
        payment_request = command[1]
        print("Paying Invoice...\n")
        bot.send_message(chat_id, f'💸 Paying Invoice {payment_request}...')

        # Replace the command with your actual command
        pay_invoice_cmd = f"lncli payinvoice {payment_request} --force"

        try:
            # Execute the command and capture both stdout and stderr
            print(f"Executing Command:{pay_invoice_cmd}\n\n")
            result = subprocess.run(pay_invoice_cmd, shell=True, capture_output=True, text=True)
            print(f"THIS IS THE RESULT: {result}\n")
            #
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
            else:
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
@authorized_only
def invoice(message):
    try:
        input_amount = message.text.split()[1]
        memo = message.text.split()[2]
        time = message.text.split()[3]
        
        #payment_response = make_invoice(input_amount, memo, time)
        hash, request = execute_lncli_addinvoice(input_amount, memo, time)
        if "Error" in hash:
            bot.send_message(message.chat.id, f"{ERROR_EMOJI}  {hash}")
        else:
        #hash, request = format_response(payment_response)
            bot.send_message(message.chat.id, f"{PAY_EMOJI} Total Invoice: {input_amount} sats :\n{memo}")
            bot.send_message(message.chat.id, hash)
            bot.send_message(message.chat.id, f"{MONEY_EMOJI} Invoice:")
            bot.send_message(message.chat.id, f"```\n{request}\n```", parse_mode='Markdown')
            bot.send_message(message.chat.id, f"{ATTENTION_EMOJI} This invoice will expire in {(int(time)/3600):.2f} hours")
       
    except IndexError:
        bot.reply_to(message, "🙋‍ Please provide the amount, message and expiration time in seconds after the /invoice command. Ex: /invoice 100000 node-services-payment 1000")

@bot.message_handler(commands=["connectpeer"])
@authorized_only
def connect_peer(message):
    try:
        peer_address = message.text.split()[1]
        connect = connect_to_node(peer_address)
        if connect ==0:
            print(f"Successfully connected to node {peer_address}")
            bot.send_message(message.chat.id, text=f"Successfully connected to node {peer_address}")
        
        else:
            print(f"Error connecting to node {peer_address}:")
            bot.send_message(message.chat.id, text=f"Can't connect to node {peer_address}. Maybe it is already connected or off-line")
    except IndexError:
        bot.reply_to(message, "🙋‍ Please provide the command /connectpeer peer_address Ex: /connectpeer public_key@host")

@bot.message_handler(commands=["openchannel"])
@authorized_only
def open_channelcmd(message):
    try:
        pub_key = message.text.split()[1]
        size = int(message.text.split()[2])
        fee_rate = int(message.text.split()[3])
        funding_tx, msg_open = open_channel(pub_key,size,fee_rate)
        #Open Channel
        bot.send_message(message.chat.id, text=f"Opening a {size} SATS channel with {pub_key} | {get_node_alias(pub_key)} at Fee Rate: {fee_rate} sats/vB")    
        funding_tx, msg_open = open_channel(pub_key,size, fee_rate)
        # Deal with  errors and show on Telegram
        if funding_tx == -1 or funding_tx == -2 or funding_tx == -3:
            bot.send_message(message.chat.id, text=msg_open)
            return
        # Send funding tx to Telegram
        bot.send_message(message.chat.id, text=msg_open)
    except IndexError:
        bot.send_message(message.chat.id, "🙋‍ Please provide the command /openchannel public_key channel_size fee_rate")
        
@bot.message_handler(commands=['consolidator'])
@authorized_only
def consolidator(message):
    try:
        user_amount = float(message.text.split()[1])
        fee_per_vbyte = float(message.text.split()[2])
        new_address = message.text.split()[3]
        utxos_data = get_utxos()
        qtd_utxos=0

        # Filter UTXOs based on user's amount
        filtered_utxos = [(outpoint, amount) for outpoint, amount in zip(utxos_data['outpoints'], utxos_data['amounts']) if amount <= user_amount]

        # Calculate the sum of amounts for filtered UTXOs
        total_filtered_amount = sum(amount for _, amount in filtered_utxos)

        # Display the sum of amounts for filtered UTXOs
        print(f"Total amount of UTXOs with amounts less than or equal to {user_amount:.0f} satoshis: {total_filtered_amount:.0f} satoshis")
        bot.reply_to(message, text=f"Total amount of UTXOs with amounts less than or equal to {user_amount:.0f} satoshis: {total_filtered_amount:.0f} satoshis")
        # Display the list of outpoints and their respective amounts for filtered UTXOs
        print("\nList of UTXOs:")
        bot.send_message(message.chat.id, text="List of UTXOs:")
        for outpoint, amount in filtered_utxos:
            print(f"Outpoint: {outpoint}, Amount: {amount:.0f} satoshis")
            bot.send_message(message.chat.id, text=f"Outpoint: {outpoint}, Amount: {amount:.0f} satoshis")
            qtd_utxos =+ 1
    
        transaction_size = calculate_transaction_size(qtd_utxos)
        fee_cost = transaction_size * fee_per_vbyte
        # Display the bos fund command line
        utxo_arguments = ' '.join([f'--utxo {outpoint}' for outpoint, _ in filtered_utxos])
        bos_fund_command = f"bos fund {new_address} {int(total_filtered_amount)} {utxo_arguments} --fee-rate {str(int(fee_per_vbyte))}"
        print(f"\nBOS Fund Command:")
        bot.send_message(message.chat.id, text="BOS Fund Command:")
        print(f"{bos_fund_command}\n")
        bot.send_message(message.chat.id, text=f"```\n{bos_fund_command}\n```", parse_mode='Markdown')
        print(f"This transaction will cost approximately: {fee_cost} sats")
        bot.send_message(message.chat.id, text=f"This transaction will cost approximately: {fee_cost} sats")
    except IndexError:
        bot.reply_to(message, "🙋‍ Please provide the amount fee-rate and btc address after the /consolidator command. Ex: /consolidator 1000000 40 bc1.....")

@bot.message_handler(commands=['bckliquidwallet'])
@authorized_only
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
@authorized_only
def generate_new_address(message):
    umbrel_command = f"lncli newaddress p2tr"
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
        
bot.message_handler(commands=['sign'])
@authorized_only
def sign_message(message):
    try:
        chat_id = message.chat.id
        command = message.text.split(' ', 1)
        message_sign = command[1]

        sign = f"lncli signmessage {message_sign}"
        output = subprocess.check_output(sign, shell=True, universal_newlines=True)
        data = json.loads(output)
        signed_message = data.get("signature", [])

        bot.send_message(chat_id, f"Message Signed:")
        bot.send_message(chat_id, f"```\n{signed_message}\n```", parse_mode='Markdown')

    except IndexError:
        bot.reply_to(message, "Please provide the message to sign. Ex: /sign <message>")

@bot.message_handler(commands=['lndgrebal'])
@authorized_only
def lndgrebal_command(message):
    args = message.text.split()
    if len(args) < 2 or args[1] not in ["on", "off"]:
        bot.reply_to(message, "Use: /lndgrebal on ou /lndgrebal off")
        return
    ar_enabled = args[1] == "on"
    adjust_ar_enabled(ar_enabled, message.chat.id)
    
@bot.message_handler(commands=['lndlogs'])
@authorized_only
def lndlogs(message):
    chat_id = message.chat.id
    # Get the parameters after the first space
    command_args = message.text.split()[1:]

    # Check if any parameters are provided
    if not command_args:
        bot.reply_to(message, "Logs are usually too long. Please provide parameters for the /lndlogs command.")
        return

    # Combine parameters into a command
    docker_command = "docker logs lightning_lnd_1 " + " ".join(command_args)
    print(f"Docker command: {docker_command}\n")

    try:
        # Execute the docker logs command
        result = subprocess.run(docker_command, capture_output=True, text=True, shell=True)
        print(result)
        # Check the exit status
        if result.returncode == 0:
            # Create a file with the output content
            output_file = StringIO(result.stdout)
            output_file.name = f"lnd-log-{command_args}.txt"

            # Send the file as a document with plain text format
            bot.send_document(chat_id, output_file, caption=f"Output from {docker_command} command")
        else:
            # Print a message indicating no matches
            bot.send_message(chat_id, f"No matching lines found in the logs.")
    except subprocess.CalledProcessError as e:
        # Handle errors
        error_message = f"Command returned non-zero exit status {e.returncode}."
        if e.stderr:
            error_message += f"\nError message: {e.stderr.strip()}"

        bot.send_message(chat_id, f"Error executing command:\n{error_message}")
  

# Polling loop to keep the bot running
bot.polling(none_stop=True, interval=0, timeout=20)
