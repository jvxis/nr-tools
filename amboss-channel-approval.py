# This an ALPHA code, please use at your own RISK
# Usage: BOT Mode: command /check-orders or Crontab with option --cron

import telebot
import json
from telebot import types

TOKEN = 'BOT TOKEN'
# Replace with your Amboss API Token
AMBOSS_TOKEN = 'AMBOSS API TOKEN'
EXPIRE = 180000

bot = telebot.TeleBot(TOKEN)
print("Amboss Order Approval Bot Started")

# Function to generate an invoice - Use your LNBITS invoice Key
def invoice(amount_to_pay,order_id):
    url = "http://your-server.local:3007/api/v1/payments"
    headers = {
        "X-Api-Key": "LNBITS-INVOICE-KEY",
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
        return f"An error occurred while processing the request: {str(e)}"

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

        # Print the entire orders list for debugging
        print("All Offers:", offer_orders)

        # Find the first offer with status "WAITING_FOR_SELLER_APPROVAL"
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

@bot.message_handler(commands=['check-orders'])
def send_telegram_message(message):
    if message is None:
        # If message is not provided, create a dummy message for default behavior
        class DummyMessage:
            def __init__(self):
                self.chat = DummyChat()

        class DummyChat:
            def __init__(self):
                self.id = "YOUR_CHAT_ID"  # Provide your chat ID

        message = DummyMessage()
    bot.send_message(message.chat.id, text="Checking new Orders...")
    valid_channel_opening_offer = check_offers()

    if not valid_channel_opening_offer:
        bot.send_message(message.chat.id, text="No orders with status 'WAITING_FOR_SELLER_APPROVAL' waiting for your approval.")
        return

    # Display the details of the valid channel opening offer
    bot.send_message(message.chat.id, text="New Order:")
    formatted_offer = f"ID: {valid_channel_opening_offer['id']}\n"
    formatted_offer += f"Amount: {valid_channel_opening_offer['seller_invoice_amount']}\n"
    formatted_offer += f"Status: {valid_channel_opening_offer['status']}\n"

    bot.send_message(message.chat.id, text=formatted_offer)

    # Call the invoice function
    bot.send_message(message.chat.id, text=f"Generating Invoice of {valid_channel_opening_offer['seller_invoice_amount']} sats...")
    invoice_result = invoice(valid_channel_opening_offer['seller_invoice_amount'],valid_channel_opening_offer['id'])
    if 'error' in invoice_result:
        bot.send_message(message.chat.id, text=f"Error generating invoice: {invoice_result['error']}")
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

    else:
        error_message = "Unexpected format in the order acceptance result. Check the accept_result for details."
        bot.send_message(message.chat.id, text=error_message)
        print(error_message)
        print("Unexpected Order Acceptance Result Format:", accept_result)

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
