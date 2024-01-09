#Import Lybraries
import requests
import telebot
import json
from telebot import types
import subprocess
import time
import os
import schedule
from datetime import datetime
import sys
sys.path.append('/path/to/nr-tools/')
import os
from config import *

#Constants
TOKEN = 'BOT-TOKEN'
EXPIRE = 180000
API_MEMPOOL = 'https://mempool.space/api/v1/fees/recommended'
limit_cost = 0.95
log_file_path = "amboss_channel_point.log"
log_file_path2 = "amboss_open_command.log"

#Code
bot = telebot.TeleBot(TOKEN)
print("Amboss Channel Open Bot Started")

# Function to generate an invoice
def invoice(amount_to_pay,order_id):
    url = LNBITS_URL
    headers = {
        "X-Api-Key": LNBITS_INVOICE_KEY,
        "Content-type": "application/json"
    }

    data = {
        "out": False,
        "amount": amount_to_pay,
        "memo": f"Amboss Channel Sale - Order ID: {order_id}",
        "expiry": EXPIRE
    }

    # Ensure the payload is formatted as JSON
    payload = json.dumps(data)

    try:
        # Make the POST request
        response = requests.post(url, data=payload, headers=headers)
        response.raise_for_status()  # Raise an exception for 4xx and 5xx status codes

        return response.json()

    except requests.exceptions.RequestException as e:
        return None

# Function to format the response content with emojis
def format_response(response_content):
    if isinstance(response_content, str):
        # Convert the JSON response to a dictionary
        response_dict = json.loads(response_content)
    elif isinstance(response_content, dict):
        response_dict = response_content
    else:
        raise ValueError("Invalid response content format")
    # Format the response with emojis
    formatted_response = f"Payment Hash: {response_dict['payment_hash']}\n"
    formatted_response += f"Payment Invoice: {response_dict['payment_request']}\n"
    formatted_response += f"Checking ID: {response_dict['checking_id']}\n"
    return formatted_response

# Function to accept the order
def accept_order(order_id, payment_request):
    url = 'https://api.amboss.space/graphql'
    headers = {
        'content-type': 'application/json',
        'Authorization': f'Bearer {AMBOSS_TOKEN}',
    }
    query = '''
        mutation AcceptOrder($sellerAcceptOrderId: String!, $request: String!) {
          sellerAcceptOrder(id: $sellerAcceptOrderId, request: $request)
        }
    '''
    variables = {"sellerAcceptOrderId": order_id, "request": payment_request}

    response = requests.post(url, json={"query": query, "variables": variables}, headers=headers)
    return response.json()


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

        json_response = response.json()

        if 'errors' in json_response:
            # Handle error in the JSON response and log it
            error_message = json_response['errors'][0]['message']
            log_content = f"Error in confirm_channel_point_to_amboss:\nOrder ID: {order_id}\nTransaction: {transaction}\nError Message: {error_message}\n"
            log_file_path_conf = "amboss_confirm_channel.log"
            with open(log_file_path_conf, "w") as log_file:
                log_file.write(log_content)

            return log_content
        else:
            return json_response

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
    print(f"UTXOs: {formatted_outpoints}")
    
    # Option to not use the UTXOs
    #command = (
    #    f"{path_to_umbrel}/scripts/app compose lightning exec lnd lncli openchannel "
    #    f"--node_key {node_pub_key} --sat_per_vbyte={fee_per_vbyte} "
    #    f"--local_amt={input_amount}"
    #)

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

            # Save the command and JSON error to a log file
            log_content = f"Command: {command}\nJSON Decode Error: {json_error}\n"
            log_file_path = "amboss_open_command.log"
            with open(log_file_path, "w") as log_file:
                log_file.write(log_content)

            return None

    except subprocess.CalledProcessError as e:
        # Handle command execution errors
        print("Error executing command:", e)

        # Save the command and error to a log file
        log_content = f"Command: {command}\nError: {e}\n"
        log_file_path = "amboss_open_command.log"
        with open(log_file_path, "w") as log_file:
            log_file.write(log_content)

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
    command = f"{full_path_bos}/bos utxos --confirmed"
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
        print(f"Não há UTXOs suficientes para abrir um canal de {channel_size} SATS. Total UTXOS: {total} SATS")
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

def check_channel():
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
        valid_channel_to_open = next((offer for offer in offer_orders if offer.get('status') == "WAITING_FOR_CHANNEL_OPEN"), None)

        # Print the found offer for debugging
        print("Found Offer:", valid_channel_to_open)

        if not valid_channel_to_open:
            print("No orders with status 'WAITING_FOR_CHANNEL_OPEN' waiting for execution.")
            return None

        return valid_channel_to_open

    except requests.exceptions.RequestException as e:
        print(f"An error occurred while processing the request: {str(e)}")
        return None
#Check Buy offers
def check_offers():
    url = 'https://api.amboss.space/graphql'
    headers = {
        'content-type': 'application/json',
        'Authorization': f'Bearer {AMBOSS_TOKEN}',
    }
    payload = {
        "query": "query List {\n  getUser {\n    market {\n      offer_orders {\n        list {\n          id\n          seller_invoice_amount\n          status\n        }\n      }\n    }\n  }\n}"
    }

    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()  # Raise an exception for 4xx and 5xx status codes

        data = response.json().get('data', {})
        market = data.get('getUser', {}).get('market', {})
        offer_orders = market.get('offer_orders', {}).get('list', [])

        # Print the entire offer list for debugging
        print("All Offers:", offer_orders)

        # Find the first offer with status "VALID_CHANNEL_OPENING"
        valid_channel_opening_offer = next((offer for offer in offer_orders if offer.get('status') == "WAITING_FOR_SELLER_APPROVAL"), None)

        # Print the found offer for debugging
        print("Found Offer:", valid_channel_opening_offer)

        if not valid_channel_opening_offer:
            print("No orders with status 'WAITING_FOR_SELLER_APPROVAL' waiting for approval.")
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
            return -1, msg_open 
        # Check if Fee Cost is less than the Invoice
        if (fee_cost) >= float(invoice):
            msg_open = f"Can't open this channel now, the fee {fee_cost} is bigger or equal to {limit_cost*100}% of the Invoice paid by customer"
            print(msg_open)
            return -2, msg_open
        # Good to open channel
        formatted_outpoints = ' '.join([f'--utxo {outpoint}' for outpoint in related_outpoints])
        print(f"Opening Channel: {pubkey}")
        # Run function to open channel
        funding_tx = execute_lnd_command(pubkey, fee_rate, formatted_outpoints, size)
        if funding_tx is None:
            msg_open = "Problem to execute the LNCLI command to open the channel. Please check the Log Files"
            print(msg_open)
            return -3, msg_open
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
    # Get the current date and time
    current_datetime = datetime.now()

    # Format and print the current date and time
    formatted_datetime = current_datetime.strftime("%Y-%m-%d %H:%M:%S")
    print("Date and Time:", formatted_datetime)
    bot.send_message(message.chat.id, text="Checking new Orders...")
    valid_channel_opening_offer = check_offers()

    if not valid_channel_opening_offer:
        bot.send_message(message.chat.id, text="No Magma orders waiting for your approval.")
    else:

        # Display the details of the valid channel opening offer
        bot.send_message(message.chat.id, text="Found Order:")
        formatted_offer = f"ID: {valid_channel_opening_offer['id']}\n"
        formatted_offer += f"Amount: {valid_channel_opening_offer['seller_invoice_amount']}\n"
        formatted_offer += f"Status: {valid_channel_opening_offer['status']}\n"

        bot.send_message(message.chat.id, text=formatted_offer)

        # Call the invoice function
        bot.send_message(message.chat.id, text=f"Generating Invoice of {valid_channel_opening_offer['seller_invoice_amount']} sats...")
        invoice_result = invoice(valid_channel_opening_offer['seller_invoice_amount'],valid_channel_opening_offer['id'])
        if invoice_result is None:
            print("Error generating invoice, check if your LNBITS is running")
            bot.send_message(message.chat.id, text="Error generating invoice, check if your LNBITS is running")
            return

        # Print the invoice result for debugging
        print("Invoice Result:", invoice_result)

        # Send the payment_request content to Telegram
        formatted_response = format_response(invoice_result)
        bot.send_message(message.chat.id, text=formatted_response)

        # Accept the order
        bot.send_message(message.chat.id, text=f"Accepting Order: {valid_channel_opening_offer['id']}")
        accept_result = accept_order(valid_channel_opening_offer['id'], invoice_result['payment_request'])
        print("Order Acceptance Result:", accept_result)
        bot.send_message(message.chat.id, text=f"Order Acceptance Result: {accept_result}")
    
        # Check if the order acceptance was successful
        if 'data' in accept_result and 'sellerAcceptOrder' in accept_result['data']:
            if accept_result['data']['sellerAcceptOrder']:
                success_message = "Invoice Successfully Sent to Amboss. Now you need to wait for Buyer payment to open the channel."
                bot.send_message(message.chat.id, text=success_message)
                print(success_message)
            else:
                failure_message = "Failed to accept the order. Check the accept_result for details."
                bot.send_message(message.chat.id, text=failure_message)
                print(failure_message)
                return
        
        else:
            error_message = "Unexpected format in the order acceptance result. Check the accept_result for details."
            bot.send_message(message.chat.id, text=error_message)
            print(error_message)
            print("Unexpected Order Acceptance Result Format:", accept_result)
            return
    
    # Wait five minutes to check if the buyer pre-paid the offer
    time.sleep(300)
    # Check if there is no error on a previous attempt to open a channel or confirm channel point to amboss
    
    if not os.path.exists(log_file_path) and not os.path.exists(log_file_path2):
        bot.send_message(message.chat.id, text="Checking Channels to Open...")
        valid_channel_to_open = check_channel()

        if not valid_channel_to_open:
            bot.send_message(message.chat.id, text="No Channels pending to open.")
            return

        # Display the details of the valid channel opening offer
        bot.send_message(message.chat.id, text="Order:")
        formatted_offer = f"ID: {valid_channel_to_open['id']}\n"
        formatted_offer += f"Customer: {valid_channel_to_open['account']}\n"
        formatted_offer += f"Size: {valid_channel_to_open['size']} SATS\n"
        formatted_offer += f"Invoice: {valid_channel_to_open['seller_invoice_amount']} SATS\n"
        formatted_offer += f"Status: {valid_channel_to_open['status']}\n"

        bot.send_message(message.chat.id, text=formatted_offer)

        #Connecting to Peer
        bot.send_message(message.chat.id, text=f"Connecting to peer: {valid_channel_to_open['account']}")
        customer_addr = get_address_by_pubkey(valid_channel_to_open['account'])
        #Connect
        node_connection = connect_to_node(customer_addr)
        if node_connection == 0:
            print(f"Successfully connected to node {customer_addr}")
            bot.send_message(message.chat.id, text=f"Successfully connected to node {customer_addr}")
        
        else:
            print(f"Error connecting to node {customer_addr}:")
            bot.send_message(message.chat.id, text=f"Can't connect to node {customer_addr}. Maybe it is already connected trying to open channel anyway")

        #Open Channel
        bot.send_message(message.chat.id, text=f"Open a {valid_channel_to_open['size']} SATS channel")    
        funding_tx, msg_open = open_channel(valid_channel_to_open['account'], valid_channel_to_open['size'], valid_channel_to_open['seller_invoice_amount'])
        # Deal with  errors and show on Telegram
        if funding_tx == -1 or funding_tx == -2 or funding_tx == -3:
            bot.send_message(message.chat.id, text=msg_open)
            return
        # Send funding tx to Telegram
        bot.send_message(message.chat.id, text=msg_open)
        print("Waiting 10 seconds to get channel point...")
        bot.send_message(message.chat.id, text="Waiting 10 seconds to get channel point...")
        # Wait 10 seconds to get channel point
        time.sleep(10)

        # Get Channel Point
        channel_point = get_channel_point(funding_tx)
        if channel_point is None:
            #log_file_path = "amboss_channel_point.log"
            msg_cp = f"Can't get channel point, please check the log file {log_file_path} and try to get it manually from LNDG for the funding txid: {funding_tx}"
            print(msg_cp)
            bot.send_message(message.chat.id,text=msg_cp)
            # Create the log file and write the channel_point value
            with open(log_file_path, "w") as log_file:
                log_file.write(funding_tx)
            return
        print(f"Channel Point: {channel_point}")
        bot.send_message(message.chat.id, text=f"Channel Point: {channel_point}")

        print("Waiting 10 seconds to Confirm Channel Point to Magma...")
        bot.send_message(message.chat.id, text="Waiting 10 seconds to Confirm Channel Point to Magma...")
        # Wait 10 seconds to get channel point
        time.sleep(10)
        # Send Channel Point to Amboss
        print("Confirming Channel to Amboss...")
        bot.send_message(message.chat.id, text= "Confirming Channel to Amboss...")
        channel_confirmed = confirm_channel_point_to_amboss(valid_channel_to_open['id'],channel_point)
        if channel_confirmed is None or "Error" in channel_confirmed:
            #log_file_path = "amboss_channel_point.log"
            if "Error" in channel_confirmed:
                msg_confirmed = channel_confirmed
            else:
                msg_confirmed = f"Can't confirm channel point {channel_point} to Amboss, check the log file {log_file_path} and try to do it manually"
            print(msg_confirmed)
            bot.send_message(message.chat.id, text=msg_confirmed)
            # Create the log file and write the channel_point value
            with open(log_file_path, "w") as log_file:
                log_file.write(channel_point)
            return
        msg_confirmed = "Opened Channel confirmed to Amboss"
        print(msg_confirmed)
        print(f"Result: {channel_confirmed}")
        bot.send_message(message.chat.id, text=msg_confirmed)
        bot.send_message(message.chat.id, text=f"Result: {channel_confirmed}")
    elif os.path.exists(log_file_path):
        bot.send_message(message.chat.id, text=f"The log file {log_file_path} already exists. This means you need to check if there is a pending channel to confirm to Amboss. Check the {log_file_path} content")
    elif os.path.exists(log_file_path2):
        bot.send_message(message.chat.id, text=f"The log file {log_file_path2} already exists. This means you have a problem with the LNCLI command, check first the {log_file_path2} content and if the channel is opened")


def execute_bot_behavior():
    # This function contains the logic you want to execute
    print("Executing bot behavior...")
    send_telegram_message(None)  # Pass None as a placeholder for the message parameter

# Schedule the bot_behavior function to run every 20 minutes
schedule.every(10).minutes.do(execute_bot_behavior)

# Schedule the bot_behavior function to run every hour at the 21st and 51st minute
#schedule.every().hour.at(":21").do(execute_bot_behavior)
#schedule.every().hour.at(":51").do(execute_bot_behavior)

if __name__ == "__main__":
    import sys

    #log_file_path = "amboss_channel_point.log"
    #log_file_path2 = "amboss_open_command.log"

    # Check if the log file exists
    print(f"Exist File Path1: {os.path.exists(log_file_path)}\n")
    print(f"Exist File Path2: {os.path.exists(log_file_path2)}\n")
    if not os.path.exists(log_file_path) and not os.path.exists(log_file_path2):
        if len(sys.argv) > 1 and sys.argv[1] == '--cron':
             # Execute the scheduled bot behavior immediately
            execute_bot_behavior()
            # If --cron argument is provided and log file doesn't exist, execute the scheduled bot behavior
            while True:
                schedule.run_pending()
                time.sleep(1)
        else:
            # Otherwise, run the bot polling for new messages
            bot.polling(none_stop=True)
    elif os.path.exists(log_file_path):
        print(f"The log file {log_file_path} already exists. This means you need to check if there is a pending channel to confirm to Amboss. Check the {log_file_path} content")
    elif os.path.exists(log_file_path2):
        print(f"The log file {log_file_path2} already exists. This means you have a problem with the LNCLI command, check first the {log_file_path2} content and if the channel is opened")
