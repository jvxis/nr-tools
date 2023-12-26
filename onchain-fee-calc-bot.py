#Credit to @EMTLL_
import subprocess
import telebot

# Your Telegram bot token
# Attention - If you use this same bot token for other python Bot, please consider creating a new one to avoid conflict.
TELEGRAM_BOT_TOKEN = "YOUR_BOT_TOKEN"

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
print("Bot onchain fee calc started")

def get_utxos():
    command = "bos utxos --confirmed"
    process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, error = process.communicate()
    output = output.decode("utf-8")
    utxos = []

    if output:
        lines = output.split('\n')
        for line in lines:
            if "amount:" in line:
                amount = float(line.split()[1]) * 100000000
                utxos.append(amount)

    return sorted(utxos, reverse=True)

# Calculate transaction size in vBytes
def calculate_transaction_size(utxos_needed):
    inputs_size = utxos_needed * 57.5  # Each UTXO is 57.5 vBytes
    outputs_size = 2 * 43  # Two outputs of 43 vBytes each
    overhead_size = 10.5  # Overhead of 10.5 vBytes
    total_size = inputs_size + outputs_size + overhead_size
    return total_size

def calculate_utxos_required_and_fees(amount_input, fee_per_vbyte):
    utxos = get_utxos()
    total = sum(utxos)
    utxos_needed = 0
    amount_with_fees = amount_input

    if total < amount_input:
        return -1, 0

    for utxo in utxos:
        utxos_needed += 1
        transaction_size = calculate_transaction_size(utxos_needed)
        fee_cost = transaction_size * fee_per_vbyte
        amount_with_fees = amount_input + fee_cost

        if utxo >= amount_with_fees:
            break
        amount_input -= utxo

    return utxos_needed, fee_cost

@bot.message_handler(commands=['onchain-fee'])
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

# Polling loop to keep the bot running
bot.polling(none_stop=True, interval=0, timeout=20)
