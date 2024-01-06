# I am just starting - please report any issue
# You need to check path, bot token and chat id
#Command List
#listpeers - List information about available peers
#listswaprequests - List PeerSwap Requests
#swapin - amount_in_sats channel_id asset | Initiate a swapin  asset should be lbtc or btc
#swapout - amount_in_sats channel_id asset  | Initiate a swapout asset should be lbtc or btc
#listswaps - List information about swaps - use /listswaps last to get the most recent
#lbtcbalance - Get the LBTC balance
#lbtctaddress - Get the LBTC address
#addpeer - pub_key | Add a peer by providing their public key
#reloadpolicy - Reload policy settings
#start - Get started with PeerSwapBot
#help - Display this help message

import telebot
import subprocess
import json
import time
import requests

BOT_TOKEN= 'BOT_TOKEN'
CHAT_ID = YOUR_CHAT_ID
PATH_COMMAND = "PATH_TO_PSCLI" #Ex. /home/<user>/go/bin
MEMPOOL_TX="https://mempool.space/tx/"
LIQUID_TX="https://liquid.network/tx/"

# Replace 'YOUR_BOT_TOKEN' with your actual bot token
bot = telebot.TeleBot(BOT_TOKEN)
print("PeerSwapBot Started...")

def get_node_alias(pub_key):
    try:
        response = requests.get(f"https://mempool.space/api/v1/lightning/nodes/{pub_key}")
        data = response.json()
        return data.get('alias', '')
    except Exception as e:
        print(f"Error fetching node alias: {str(e)}")
        return ''
    
def execute_command(command):
    try:
        output = subprocess.check_output(command, text=True)
        return output
    except subprocess.CalledProcessError as e:
        # Handle specific error messages
        error_message = str(e.output).strip()
        if "insufficient walletbalance" in error_message:
            return f"Error Executing Command: {command} Insufficient Wallet Balance"
        #elif "Error" in error_message:
        #    return f"Error Executing Command: {command}  use /listswaps to get detail"
        else:
        # If not a specific error, return a generic error message
            return f"Error executing command: {command} - {error_message}\n Use /listswaps to get detail"
    except Exception as e:
        # Handle other exceptions
        return f"Error executing command: {str(e)}"

def send_formatted_output(chat_id, formatted_text):
    bot.send_message(chat_id, formatted_text)
    
def format_output(data):
    if not data['requested_swaps']:
        return "No PeerSwap Requests available"
    
    # You can customize the formatting based on the structure of requested_swaps
    return json.dumps(data['requested_swaps'], indent=2)

def format_swap_output(data):
    if 'swap' not in data:
        return "Error executing swap command"

    swap = data['swap']
    initiator_alias = get_node_alias(swap['initiator_node_id'])
    peer_alias = get_node_alias(swap['peer_node_id'])
    if swap['asset'] == 'btc':
        network = MEMPOOL_TX 
    else: 
        network = LIQUID_TX
        
    formatted_output = (
        f"ID: {swap['id']}\n"
        f"Created At: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(swap['created_at'])))}\n"
        f"Asset: {swap['asset']}\n"
        f"Type: {swap['type']}\n"
        f"Role: {swap['role']}\n"
        f"State: {swap['state']}\n"
        f"Initiator Node ID: {initiator_alias} | {swap['initiator_node_id']}\n"
        f"Peer Node ID: {peer_alias} | {swap['peer_node_id']}\n"
        f"Amount: {swap['amount']}\n"
        f"Channel ID: {swap['channel_id']}\n"
        f"Opening TX ID: {network}{swap['opening_tx_id']}\n"
        f"Claim TX ID: {swap['claim_tx_id']}\n"
        f"Cancel Message: {swap['cancel_message']}\n"
        f"LND Channel ID: {swap['lnd_chan_id']}\n"
    )
    return formatted_output

def format_single_swap_output(swap):
    initiator_alias = get_node_alias(swap['initiator_node_id'])
    peer_alias = get_node_alias(swap['peer_node_id'])
    if swap['asset'] == 'btc':
        network = MEMPOOL_TX 
    else: 
        network = LIQUID_TX
    formatted_output = (
        f"ID: {swap['id']}\n"
        f"Created At: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(swap['created_at'])))}\n"
        f"Asset: {swap['asset']}\n"
        f"Type: {swap['type']}\n"
        f"Role: {swap['role']}\n"
        f"State: {swap['state']}\n"
        f"Initiator Node ID: {initiator_alias} | {swap['initiator_node_id']}\n"
        f"Peer Node ID: {peer_alias} | {swap['peer_node_id']}\n"
        f"Amount: {swap['amount']}\n"
        f"Channel ID: {swap['channel_id']}\n"
        f"Opening TX ID: {network}{swap['opening_tx_id']}\n"
        f"Claim TX ID: {swap['claim_tx_id']}\n"
        f"Cancel Message: {swap['cancel_message']}\n"
        f"LND Channel ID: {swap['lnd_chan_id']}\n\n"
    )
    return formatted_output

def list_recent_swaps(message, count=1):
    send_formatted_output(message.chat.id, "Checking most recent PeerSwap Swap...")
    command = [f'{PATH_COMMAND}/pscli', 'listswaps']
    output = execute_command(command)
    try:
        data = json.loads(output)
        swaps = data.get('swaps', [])
        if swaps:
            latest_swap = swaps[-1]  # Get the most recent swap
            formatted_output = format_single_swap_output(latest_swap)
            send_formatted_output(message.chat.id, formatted_output)
        else:
            send_formatted_output(message.chat.id, "No PeerSwap Swaps available")
    except json.JSONDecodeError as e:
        formatted_output = f"Error decoding JSON: {str(e)}"
        print(formatted_output)
        send_formatted_output(message.chat.id, formatted_output)
        
def format_listswaps_output(data):
    if not data['swaps']:
        return "No PeerSwap Swaps available"

    formatted_output = ""
    for swap in data['swaps']:
        initiator_alias = get_node_alias(swap['initiator_node_id'])
        peer_alias = get_node_alias(swap['peer_node_id'])
        if swap['asset'] == 'btc':
            network = MEMPOOL_TX 
        else: 
            network = LIQUID_TX
        formatted_output += (
            f"ID: {swap['id']}\n"
            f"Created At: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(int(swap['created_at'])))}\n"
            f"Asset: {swap['asset']}\n"
            f"Type: {swap['type']}\n"
            f"Role: {swap['role']}\n"
            f"State: {swap['state']}\n"
            f"Initiator Node ID: {initiator_alias} | {swap['initiator_node_id']}\n"
            f"Peer Node ID: {peer_alias} | {swap['peer_node_id']}\n"
            f"Amount: {swap['amount']}\n"
            f"Channel ID: {swap['channel_id']}\n"
            f"Opening TX ID: {network}{swap['opening_tx_id']}\n"
            f"Claim TX ID: {swap['claim_tx_id']}\n"
            f"Cancel Message: {swap['cancel_message']}\n"
            f"LND Channel ID: {swap['lnd_chan_id']}\n\n"
        )
    return formatted_output

def format_generic_output(data):
    if not data:
        return "Error executing command"

    formatted_output = ""
    formatted_output += f"Reserve Onchain: {data.get('reserve_onchain_msat', 'N/A')}\n"
    formatted_output += f"Min Swap Amount: {data.get('min_swap_amount_msat', 'N/A')}\n"
    formatted_output += f"Accept All Peers: {'Yes' if data.get('accept_all_peers', False) else 'No'}\n"
    formatted_output += f"Allow New Swaps: {'Yes' if data.get('allow_new_swaps', False) else 'No'}\n"

    allowlisted_peers = data.get('allowlisted_peers', [])
    formatted_output += "Peers Allowed:\n" if allowlisted_peers else ""
    for peer in allowlisted_peers:
        formatted_output += f"  - {get_node_alias(peer)} | {peer}\n"

    suspicious_peer_list = data.get('suspicious_peer_list', [])
    formatted_output += "Suspicious Peers List:\n" if suspicious_peer_list else ""
    for peer in suspicious_peer_list:
        formatted_output += f"  - {get_node_alias(peer)} | {peer}\n"

    return formatted_output

def list_all_swaps(message):
    send_formatted_output(message.chat.id, "Checking PeerSwap Swaps...")
    output = execute_command([f'{PATH_COMMAND}/pscli', 'listswaps'])
    try:
        data = json.loads(output)
        swaps = data.get('swaps', [])
        if swaps:
            for swap in swaps:
                formatted_output = format_single_swap_output(swap)
                send_formatted_output(message.chat.id, formatted_output)
        else:
            send_formatted_output(message.chat.id, "No PeerSwap Swaps available")
    except json.JSONDecodeError as e:
        formatted_output = f"Error decoding JSON: {str(e)}"
        print(formatted_output)
        send_formatted_output(message.chat.id, formatted_output)

@bot.message_handler(commands=['start'])
def start_command(message):
    send_formatted_output(message.chat.id, "Welcome to PeerSwapBot! Type /help to see the list of available commands and their usage.")

@bot.message_handler(commands=['help'])
def help_command(message):
    help_text = (
        "Available commands:\n"
        "/listpeers - List information about available peers\n"
        "/listswaprequests - List PeerSwap Requests\n"
        "/swapin amount_in_sats channel_id asset - Initiate a swap-in - asset should be lbtc or btc\n"
        "/swapout amount_in_sats channel_id asset - Initiate a swap-out - asset should be lbtc or btc\n"
        "/listswaps - List information about swaps\n"
        "/lbtcbalance - Get the LBTC balance\n"
        "/lbtctaddress - Get the LBTC address\n"
        "/addpeer pub_key - Add a peer by providing their public key\n"
        "/reloadpolicy - Reload policy settings\n"
        "/start - Get started with PeerSwapBot\n"
        "/help - Display this help message\n"
    )
    send_formatted_output(message.chat.id, help_text)
    
@bot.message_handler(commands=['listpeers'])
def list_peers(message):
        # Execute the command and capture the output
    output = subprocess.check_output([f'{PATH_COMMAND}/pscli', 'listpeers'], text=True)
    if not output.startswith("Error"):
        # Parse the JSON output
        data = json.loads(output)

        # Iterate through peers and send information in a readable way
        for peer in data['peers']:
            peer_alias = get_node_alias(peer['node_id'])
            peer_info = f"Node ID: {peer_alias} | {peer['node_id']}\n"
            peer_info += f"Swaps Allowed: {'Yes' if peer['swaps_allowed'] else 'No'}\n"
            peer_info += f"Supported Assets: {', '.join(peer['supported_assets'])}\n"

            # Iterate through channels
            for channel in peer['channels']:
                peer_info += f"\nChannel ID: {channel['channel_id']}\n"
                peer_info += f"Local Balance: {channel['local_balance']} sats\n"
                peer_info += f"Remote Balance: {channel['remote_balance']} sats\n"
                peer_info += f"Active: {'Yes' if channel['active'] else 'No'}\n"

            peer_info += f"\nAs Sender:\nSwaps Out: {peer['as_sender']['swaps_out']}\nSwaps In: {peer['as_sender']['swaps_in']}\n"
            peer_info += f"Sats Out: {peer['as_sender']['sats_out']} sats\nSats In: {peer['as_sender']['sats_in']} sats\n"

            peer_info += f"\nAs Receiver:\nSwaps Out: {peer['as_receiver']['swaps_out']}\nSwaps In: {peer['as_receiver']['swaps_in']}\n"
            peer_info += f"Sats Out: {peer['as_receiver']['sats_out']} sats\nSats In: {peer['as_receiver']['sats_in']} sats\n"

            peer_info += f"\nPaid Fee: {peer['paid_fee']} sats\n"

            # Send the formatted information to the user
            print(peer_info)
            send_formatted_output(message.chat.id, peer_info)
            

    else:
        print(output)
        send_formatted_output(message.chat.id, output)
        
@bot.message_handler(commands=['listswaprequests'])
def list_swap_requests(message):
    send_formatted_output(message.chat.id, "Checking PeerSwap Requests...")
    output = execute_command([f'{PATH_COMMAND}/pscli', 'listswaprequests'])
    formatted_output = format_output(json.loads(output))
    print(formatted_output)
    send_formatted_output(message.chat.id, formatted_output)
    
@bot.message_handler(commands=['swapin'])
def swapin_command(message):
    # Extracting parameters from the user's message
    try:
        _, sat_amt, channel_id, asset = message.text.split()
    except ValueError:
        send_formatted_output(message.chat.id, "Usage: /swapin sat_amt channel_id asset")
        return

    command = [f'{PATH_COMMAND}/pscli', 'swapin', '--sat_amt', sat_amt, '--channel_id', channel_id, '--asset', asset]
    output = execute_command(command)
    if "Error" in output:
        print(output)
        send_formatted_output(message.chat.id, output)
    else:
        formatted_output = format_swap_output(json.loads(output))
        print(formatted_output)
        send_formatted_output(message.chat.id, formatted_output)

@bot.message_handler(commands=['swapout'])
def swapin_command(message):
    # Extracting parameters from the user's message
    try:
        _, sat_amt, channel_id, asset = message.text.split()
    except ValueError:
        send_formatted_output(message.chat.id, "Usage: /swapout sat_amt channel_id asset")
        return

    command = [f'{PATH_COMMAND}/pscli', 'swapout', '--sat_amt', sat_amt, '--channel_id', channel_id, '--asset', asset]
    output = execute_command(command)
    if "Error" in output:
        print(output)
        send_formatted_output(message.chat.id, output)
    else:
        formatted_output = format_swap_output(json.loads(output))
        print(formatted_output)
        send_formatted_output(message.chat.id, formatted_output)

    
@bot.message_handler(commands=['listswaps'])
def list_swaps(message):
    args = message.text.split()[1:]
    if "last" in args:
        list_recent_swaps(message)
    else:
        list_all_swaps(message)

@bot.message_handler(commands=['lbtcbalance'])
def lbtc_getbalance(message):
    send_formatted_output(message.chat.id, "Fetching LBTC Balance...")
    output = execute_command([f'{PATH_COMMAND}/pscli', 'lbtc-getbalance'])
    try:
        data = json.loads(output)
        formatted_output = f"Amount: {data['sat_amount']} sats"
    except json.JSONDecodeError as e:
        formatted_output = f"Error decoding JSON: {str(e)}"
    print(formatted_output)
    send_formatted_output(message.chat.id, formatted_output)

@bot.message_handler(commands=['lbtcaddress'])
def lbtc_getaddress(message):
    send_formatted_output(message.chat.id, "Fetching LBTC Address...")
    output = execute_command([f'{PATH_COMMAND}/pscli', 'lbtc-getaddress'])
    try:
        data = json.loads(output)
        formatted_output = f"LBTC Address: {data['address']}"
    except json.JSONDecodeError as e:
        formatted_output = f"Error decoding JSON: {str(e)}"
    print(formatted_output)
    send_formatted_output(message.chat.id, formatted_output)

@bot.message_handler(commands=['addpeer'])
def add_peer(message):
    try:
        # Extracting the public key from the message text
        pub_key = message.text.split(" ")[1]
    except IndexError:
        send_formatted_output(message.chat.id, "Please provide the public key as a parameter.")
        return

    send_formatted_output(message.chat.id, f"Adding Peer with Public Key: {pub_key}...")
    output = execute_command([f'{PATH_COMMAND}/pscli', 'addpeer', '--peer_pubkey', pub_key])
    try:
        data = json.loads(output)
        formatted_output = format_generic_output(data)
    except json.JSONDecodeError as e:
        formatted_output = f"Error decoding JSON: {str(e)}"
    print(formatted_output)
    send_formatted_output(message.chat.id, formatted_output)
    
@bot.message_handler(commands=['reloadpolicy'])
def reload_policy(message):
    send_formatted_output(message.chat.id, "Reloading Policy...")
    output = execute_command([f'{PATH_COMMAND}/pscli', 'reloadpolicy'])
    try:
        data = json.loads(output)
        formatted_output = format_generic_output(data)
    except json.JSONDecodeError as e:
        formatted_output = f"Error decoding JSON: {str(e)}"
    print(formatted_output)
    send_formatted_output(message.chat.id, formatted_output)

def scheduled_check():
    while True:
        send_formatted_output(CHAT_ID, "Checking PeerSwap Requests...")
        output = execute_command([f'{PATH_COMMAND}/pscli', 'listswaprequests'])
        formatted_output = format_output(json.loads(output))
        print(formatted_output)
        send_formatted_output(CHAT_ID, formatted_output)
        time.sleep(1200)  # Sleep for 20 minutes (1200 seconds)

# Start the scheduled check in a separate thread
import threading
threading.Thread(target=scheduled_check).start()

# Polling to keep the bot running
bot.polling()

