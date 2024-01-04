# I am just starting - now it is just checking if there are swap requests
# You need to check path, bot token and chat id

import telebot
import subprocess
import json
import time

BOT_TOKEN= 'BOT_TOKEN'
CHAT_ID = YOUR_CHAT_ID
PATH_COMMAND = "PATH_TO_PSCLI" #Ex. /home/<user>/go/bin

# Replace 'YOUR_BOT_TOKEN' with your actual bot token
bot = telebot.TeleBot(BOT_TOKEN)
print("PeerSwapBot Started...")
def execute_command(command):
    try:
        output = subprocess.check_output(command, text=True)
        return output
    except Exception as e:
        return f"Error executing command: {str(e)}"

def send_formatted_output(chat_id, formatted_text):
    bot.send_message(chat_id, formatted_text)
    
@bot.message_handler(commands=['listpeers'])
def list_peers(message):
        # Execute the command and capture the output
    output = subprocess.check_output([f'{PATH_COMMAND}/pscli', 'listpeers'], text=True)
    if not output.startswith("Error"):
        # Parse the JSON output
        data = json.loads(output)

        # Iterate through peers and send information in a readable way
        for peer in data['peers']:
            peer_info = f"Node ID: {peer['node_id']}\n"
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
    print(output)
    send_formatted_output(message.chat.id, output)

def scheduled_check():
    while True:
        send_formatted_output(CHAT_ID, "Checking PeerSwap Requests...")
        output = execute_command([f'{PATH_COMMAND}/pscli', 'listswaprequests'])
        print(output)
        send_formatted_output(CHAT_ID, output)  # Replace YOUR_USER_CHAT_ID with the actual user chat ID
        time.sleep(600)  # Sleep for 10 minutes (600 seconds)

# Start the scheduled check in a separate thread
import threading
threading.Thread(target=scheduled_check).start()

# Polling to keep the bot running
bot.polling()
