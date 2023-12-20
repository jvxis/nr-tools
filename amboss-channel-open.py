import requests
import telebot
import json
from telebot import types
import subprocess

TOKEN = 'YOUR-BOT-TOKEN'
CHAT_ID = "YOUR-TELEGRAM_CHAT-ID"
AMBOSS_TOKEN = 'AMBOSS TOKEN'
API_MEMPOOL = 'https://mempool.space/api/v1/fees/recommended'
# Acceptable cost limit
limit_cost = 0.95
# Replace with your Umbrel full path Ex. /home/<user>/umbrel
path_to_umbrel = "YOUR-PATH-TO-UMBREL"

bot = telebot.TeleBot(TOKEN)
print("Amboss Channel Open Bot Started")

def confirm_channel_point_to_amboss(order_id, transaction):
    url = 'https://api.amboss.space/graphql'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {AMBOSS_TOKEN}'
    }

    graphql_query = f'mutation Mutation($sellerAddTransactionId: String!, $transaction: String!) {{\n  sellerAddTransaction(id: $sellerAddTransactionId, transaction: $transaction)\n}}'
    
    data = {
        'query': graphql_query,
        'variables': {
            'sellerAddTransactionId': order_id,
            'transaction': transaction
        }
    }

    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()  # Raise an HTTPError for bad responses (4xx or 5xx)
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error making the request: {e}")
        return None
    

def get_channel_point(hash_to_find):
    def execute_lightning_command():
        command = [
            f"{path_to_umbrel}/scripts/app",
            "compose",
            "lightning",
            "exec",
            "lnd",
            "lncli",
            "pendingchannels"
        ]

        try:
            print(f"Command: {command}")
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            output = result.stdout

            # Parse JSON result
            result_json = json.loads(output)
            return result_json

        except subprocess.CalledProcessError as e:
            print(f"Error executing the command: {e}")
            return None

    result = execute_lightning_command()

    if result:
        pending_open_channels = result.get("pending_open_channels", [])

        for channel_info in pending_open_channels:
            channel_point = channel_info["channel"]["channel_point"]
            channel_hash = channel_point.split(":")[0]

            if channel_hash == hash_to_find:
                return channel_point

    return None

def execute_lnd_command(node_pub_key, fee_per_vbyte, formatted_outpoints, input_amount):
    # Format the command
    command = (
        f"{path_to_umbrel}/scripts/app compose lightning exec lnd lncli openchannel "
        f"--node_key {node_pub_key} --sat_per_vbyte={fee_per_vbyte} "
        f"{formatted_outpoints} --local_amt={input_amount}"
    )

    try:
        # Run the command and capture the output
        print(f"Command: {command}")
        result = subprocess.run(command, shell=True, check=True, capture_output=True)

        # Print the command output
        print("Command Output:", result.stdout.decode("utf-8"))

        # Parse the JSON output
        try:
            output_json = json.loads(result.stdout.decode("utf-8"))
            funding_txid = output_json.get("funding_txid")
            return funding_txid
        except json.JSONDecodeError as json_error:
            print(f"Error decoding JSON: {json_error}")
            return None

    except subprocess.CalledProcessError as e:
        # Handle command execution errors
        print("Error executing command:", e)
        return None

def get_fast_fee():
    response = requests.get(API_MEMPOOL)
    data = response.json()
    if data:
        fast_fee = data['fastestFee']
        return fast_fee
    else:
        return None

def get_address_by_pubkey(peer_pubkey):
    url = 'https://api.amboss.space/graphql'
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {AMBOSS_TOKEN}'
    }

    query = f"""
    query List($pubkey: String!) {{
      getNode(pubkey: $pubkey) {{
        graph_info {{
          node {{
            addresses {{
              addr
            }}
          }}
        }}
      }}
    }}
    """

    variables = {
        "pubkey": peer_pubkey
    }

    payload = {
        "query": query,
        "variables": variables
    }

    response = requests.post(url, json=payload, headers=headers)

    if response.status_code == 200:
        data = response.json()
        addresses = data.get('data', {}).get('getNode', {}).get('graph_info', {}).get('node', {}).get('addresses', [])
        first_address = addresses[0]['addr'] if addresses else None

        if first_address:
            return f"{peer_pubkey}@{first_address}"
        else:
            return None
    else:
        print(f"Error: {response.status_code}")
        return None


def connect_to_node(node_key_address):
    command = f"{path_to_umbrel}/scripts/app compose lightning exec lnd lncli connect {node_key_address} --timeout 120s"
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


def get_utxos():
    command = "bos utxos"
    process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, error = process.communicate()
    output = output.decode("utf-8")
    utxos = {'amounts': [], 'outpoints': []}

    if output:
        lines = output.split('\n')
        for line in lines:
            if "amount:" in line:
                amount = float(line.split()[1]) * 100000000
                utxos['amounts'].append(amount)
            if "outpoint:" in line:
                outpoint = str(line.split()[1])
                utxos['outpoints'].append(outpoint)

    return utxos

# Calcula o tamanho da transação em vBytes
def calculate_transaction_size(utxos_needed):
    inputs_size = utxos_needed * 57.5  # Cada UTXO é de 57.5 vBytes
    outputs_size = 2 * 43  # Dois outputs de 43 vBytes cada
    overhead_size = 10.5  # Overhead de 10.5 vBytes
    total_size = inputs_size + outputs_size + overhead_size
    return total_size

def calculate_utxos_required_and_fees(amount_input, fee_per_vbyte):
    utxos_data = get_utxos()
    channel_size = float(amount_input)
    total = sum(utxos_data['amounts'])
    utxos_needed = 0
    amount_with_fees = channel_size
    related_outpoints = []

    if total < channel_size:
        print("Não há UTXOs suficientes para transferir o valor desejado.")
        return -1, 0, None

    for utxo_amount, utxo_outpoint in zip(utxos_data['amounts'], utxos_data['outpoints']):
        utxos_needed += 1
        transaction_size = calculate_transaction_size(utxos_needed)
        fee_cost = transaction_size * fee_per_vbyte
        amount_with_fees = channel_size + fee_cost

        related_outpoints.append(utxo_outpoint)

        if utxo_amount >= amount_with_fees:
            break
        channel_size -= utxo_amount

    return utxos_needed, fee_cost, related_outpoints if related_outpoints else None

def check_offers():
    url = 'https://api.amboss.space/graphql'
    headers = {
        'content-type': 'application/json',
        'Authorization': f'Bearer {AMBOSS_TOKEN}',
    }
    payload = {
        "query": "query List {\n  getUser {\n    market {\n      offer_orders {\n        list {\n          id\n          size\n          status\n        account\n        seller_invoice_amount\n        }\n      }\n    }\n  }\n}"
    }

    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()  # Raise an exception for 4xx and 5xx status codes

        data = response.json().get('data', {})
        market = data.get('getUser', {}).get('market', {})
        offer_orders = market.get('offer_orders', {}).get('list', [])

        # Print the entire offer list for debugging
        print("All Offers:", offer_orders)

        # Find the first offer with status "WAITING_FOR_CHANNEL_OPEN"
        valid_channel_opening_offer = next((offer for offer in offer_orders if offer.get('status') == "WAITING_FOR_CHANNEL_OPEN"), None)

        # Print the found offer for debugging
        print("Found Offer:", valid_channel_opening_offer)

        if not valid_channel_opening_offer:
            print("No orders with status 'WAITING_FOR_CHANNEL_OPEN' waiting for execution.")
            return None

        return valid_channel_opening_offer

    except requests.exceptions.RequestException as e:
        print(f"An error occurred while processing the request: {str(e)}")
        return None

# Function Channel Open
def open_channel(pubkey, size, invoice):
    # get fastest fee
    print("Getting fastest fee...")
    fee_rate = get_fast_fee()
    if fee_rate:
        print(f"Fastest Fee:{fee_rate} sat/vB")
       # Check UTXOS and Fee Cost
        print("Getting UTXOs, Fee Cost and Outpoints to open the channel")
        utxos_needed, fee_cost, related_outpoints = calculate_utxos_required_and_fees(size,fee_rate)
       # Check if enough UTXOS
        if utxos_needed == -1:
            msg_open = f"There isn't enough confirmed Balance to open a {size} SATS channel"
            print(msg_open)
            return "-1", msg_open 
        # Check if Fee Cost is less than the Invoice
        if (fee_cost) >= float(invoice):
            msg_open = f"Can't open this channel now, the fee {fee_cost} is bigger or equal to {limit_cost*100}% of the Invoice paid by customer"
            print(msg_open)
            return "-2", msg_open
        # Good to open channel
        formatted_outpoints = ' '.join([f'--utxo {outpoint}' for outpoint in related_outpoints])
        print(f"Opening Channel: {pubkey}")
        # Run function to open channel
        funding_tx = execute_lnd_command(pubkey, fee_rate, formatted_outpoints, size)
        if funding_tx is None:
            msg_open = "Problem to execute the LNCLI command to open the channel."
            print(msg_open)
            return "-3", msg_open
        msg_open = f"Channel opened with funding transaction: {funding_tx}"
        print(msg_open)
        return funding_tx, msg_open       

    else:
        return None

@bot.message_handler(commands=['channel-to-open'])
def send_telegram_message(message):
    if message is None:
        # If message is not provided, create a dummy message for default behavior
        class DummyMessage:
            def __init__(self):
                self.chat = DummyChat()

        class DummyChat:
            def __init__(self):
                self.id = CHAT_ID  # Provide a default chat ID

        message = DummyMessage()
    bot.send_message(message.chat.id, text="Checking Channels to Open...")
    valid_channel_opening_offer = check_offers()

    if not valid_channel_opening_offer:
        bot.send_message(message.chat.id, text="No orders with status 'WAITING_FOR_CHANNEL_OPEN' waiting for your execution.")
        return

    # Display the details of the valid channel opening offer
    bot.send_message(message.chat.id, text="Order:")
    formatted_offer = f"ID: {valid_channel_opening_offer['id']}\n"
    formatted_offer += f"Customer: {valid_channel_opening_offer['account']}\n"
    formatted_offer += f"Size: {valid_channel_opening_offer['size']} SATS\n"
    formatted_offer += f"Invoice: {valid_channel_opening_offer['seller_invoice_amount']} SATS\n"
    formatted_offer += f"Status: {valid_channel_opening_offer['status']}\n"

    bot.send_message(message.chat.id, text=formatted_offer)

    #Connecting to Peer
    bot.send_message(message.chat.id, text=f"Connecting to peer: {valid_channel_opening_offer['account']}")
    customer_addr = get_address_by_pubkey(valid_channel_opening_offer['account'])
    #Connect
    node_connection = connect_to_node(customer_addr)
    if node_connection == 0:
        print(f"Successfully connected to node {customer_addr}")
        bot.send_message(message.chat.id, text=f"Successfully connected to node {customer_addr}")
        
    else:
        print(f"Error connecting to node {customer_addr}:")
        bot.send_message(message.chat.id, text=f"Can't connect to node {customer_addr}. Maybe it is already connected trying to open channel anyway")

    #Open Channel
    bot.send_message(message.chat.id, text=f"Open a {valid_channel_opening_offer['size']} SATS channel")    
    funding_tx, msg_open = open_channel(valid_channel_opening_offer['account'], valid_channel_opening_offer['size'], valid_channel_opening_offer['seller_invoice_amount'])
    # Deal with  errors and show on Telegram
    if funding_tx == -1 or funding_tx == -2 or funding_tx == -3:
        bot.send_message(message.chat.id, text=msg_open)
        return
    # Send funding tx to Telegram
    bot.send_message(message.chat.id, text=msg_open)

    # Get Channel Point
    channel_point = get_channel_point(funding_tx)
    if channel_point is None:
        msg_cp = f"Can't get channel point, please try to get it manually from LNDG"
        print(msg_cp)
        bot.send_message(message.chat.id,text=msg_cp)
        return
    print(f"Channel Point: {channel_point}")
    bot.send_message(message.chat.id, text=f"Channel Point: {channel_point}")
    
    # Send Channel Point to Amboss
    print("Confirming Channel to Amboss...")
    bot.send_message(message.chat.id, text= "Confirming Channel to Amboss...")
    channel_confirmed = confirm_channel_point_to_amboss(valid_channel_opening_offer['id'],channel_point)
    if channel_confirmed is None:
         msg_confirmed = "Can't confirm channel point to Amboss, try to do it manually"
         print(msg_confirmed)
         bot.send_message(message.chat.id, text=msg_confirmed)
         return
    msg_confirmed = "Opened Channel confirmed to Amboss"
    print(msg_confirmed)
    print(f"Result: {channel_confirmed}")
    bot.send_message(message.chat.id, text=msg_confirmed)
    bot.send_message(message.chat.id, text=f"Result: {channel_confirmed}")

def execute_bot_behavior():
    # This function contains the logic you want to execute
    print("Executing bot behavior...")
    send_telegram_message(None)  # Pass None as a placeholder for the message parameter

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == '--cron':
        # If --cron argument is provided, execute the scheduled bot behavior
        execute_bot_behavior()
    else:
        # Otherwise, run the bot polling for new messages
        bot.polling(none_stop=True)
