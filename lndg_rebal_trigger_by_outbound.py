import aiohttp
import asyncio
import datetime
import telebot

# Replace with your Telegram Bot Token
TELEGRAM_TOKEN = "YOUR_BOT_TOKEN"
# Replace with your Chat ID
CHATID = "YOUR_CHATID"
# Initialize Telebot with your Telegram bot token
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# LNDG Username and Password
username = "lndg-admin"
password = "lndgpassword"

# API URLs
# Replace with your LNDG IP
CHANNELS_API_URL = 'http://lndg-ip:8889/api/channels/?is_open=true&private=&is_active=true'
CHANNEL_UPDATE_API_URL = 'http://lndg-ip:8889/api/channels/{chan_id}/'

# Exclusion list of chan_ids, this is an example. Please configure your list.
EXCLUSION_LIST = [
    '891080507132936203', #LNBig Edge3
    '891176164674764808', #LNBIG Hub2
    '965520742847741953', #Boltz
    '982701711585312770', #Acinq
    '975284406145187841', #Kappa
    '947785620256129025'  #lndwr3 - Strike
]

class LNDGAPIError(Exception):
    """Represents an error when interacting with the LNDg API."""
    def __init__(self, message, status_code=None, response_data=None):
        super().__init__(message)
        self.status_code = status_code
        self.response_data = response_data

def get_current_timestamp():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def send_telegram_message(message):
    bot.send_message(CHATID, message)

async def get_channels(session):
    try:
        async with session.get(CHANNELS_API_URL, auth=aiohttp.BasicAuth(username, password)) as response:
            if response.status == 200:
                return await response.json()
            else:
                raise LNDGAPIError(f"Failed to get channels: Status Code {response.status}", response.status, await response.json())
    except aiohttp.ClientError as e:
        raise LNDGAPIError("LNDg API unavailable") from e

async def update_channel(session, chan_id, data):
    try:
        url = CHANNEL_UPDATE_API_URL.format(chan_id=chan_id)
        async with session.put(url, json=data, auth=aiohttp.BasicAuth(username, password)) as response:
            if response.status == 200:
                return await response.json()
            else:
                raise LNDGAPIError(f"Failed to update channel {chan_id}: Status Code {response.status}", response.status, await response.json())
    except aiohttp.ClientError as e:
        raise LNDGAPIError(f"LNDg API request failed for channel {chan_id}") from e

async def process_channels():
    async with aiohttp.ClientSession() as session:
        channels_data = await get_channels(session)
        channels = channels_data.get('results', [])

        # Calcular a proporção global de local_balance/capacity
        total_capacity = sum(channel['capacity'] for channel in channels)
        total_local_balance = sum(channel['local_balance'] for channel in channels)
        # Evitar divisão por zero
        local_balance_prop = (total_local_balance / total_capacity) if total_capacity else 0

        messages = []
        message_block = ""

        for channel in channels:
            chan_id = channel['chan_id']
            
            # Skip channels in the exclusion list
            if chan_id in EXCLUSION_LIST:
                continue
            
            alias = channel['alias']
            local_balance = channel['local_balance']
            remote_fee_rate = channel['remote_fee_rate']
            local_fee_rate = channel['local_fee_rate']
            ar_max_cost = channel['ar_max_cost']
            auto_rebalance_current = channel['auto_rebalance']
            capacity = channel['capacity']

            # Definir o `adjusted_min_balance` baseado na proporção calculada
            if capacity > 10000000:
                adjusted_min_balance = 10000000 * local_balance_prop
            else:
                adjusted_min_balance = capacity * local_balance_prop
            
            if local_balance < adjusted_min_balance and local_fee_rate > (remote_fee_rate / (ar_max_cost / 100)):
                auto_rebalance_needed = True
            else:
                auto_rebalance_needed = False

            # Calcular channel_prop usando adjusted_min_balance e capacidade
            channel_prop = adjusted_min_balance / capacity if capacity else 0

            # Ajustar targets com base em channel_prop (Ex.: 0.25 => out:25, in:75)
            new_ar_out_target = int(round(channel_prop * 100))
            new_ar_in_target = 100 - new_ar_out_target

            # Verificar se existe alteração necessária em auto_rebalance, ar_out_target ou ar_in_target
            update_fields = {}
            if auto_rebalance_needed != auto_rebalance_current:
                update_fields["auto_rebalance"] = auto_rebalance_needed

            if channel.get("ar_out_target") != new_ar_out_target:
                update_fields["ar_out_target"] = new_ar_out_target

            if channel.get("ar_in_target") != new_ar_in_target:
                update_fields["ar_in_target"] = new_ar_in_target

            if update_fields:
                await update_channel(session, chan_id, update_fields)
                
                local_balance_str = f"{local_balance:,}"
                adjusted_min_balance_str = f"{int(adjusted_min_balance):,}"
                print(f"🔍 Canal: {chan_id} | {alias}\n💰 Local Balance: {local_balance_str}\n📊 Adjusted Min Balance: {adjusted_min_balance_str}\n💸 Local Fee: {local_fee_rate} | Remote Fee: {remote_fee_rate}\n🤖 AR set to: {auto_rebalance_needed}\n🔀 AR Targets: Out: {new_ar_out_target} | In: {new_ar_in_target}")
                message = (
                    f"🔍 Canal: {chan_id} | {alias}\n"
                    f"💰 Local Balance: {local_balance_str}\n"
                    f"📊 Adjusted Min Balance: {adjusted_min_balance_str}\n"
                    f"💸 Local Fee: {local_fee_rate} | Remote Fee: {remote_fee_rate}\n"
                    f"🤖 AR set to: {auto_rebalance_needed}\n"
                    f"🔀 AR Targets: Out: {new_ar_out_target} | In: {new_ar_in_target}\n"
                )
                messages.append(message)
        
        for msg in messages:
            if len(message_block) + len(msg) + 1 < 4096:
                message_block += msg + "\n"
            else:
                send_telegram_message(message_block)
                message_block = msg + "\n"
        
        if message_block:
            send_telegram_message(message_block)

if __name__ == "__main__":
    print("⚡️LNDG Auto-Rebalancer Trigger By Channel⚡️")
    send_telegram_message("⚡️LNDG Auto-Rebalancer Trigger By Channel⚡️")

    asyncio.run(process_channels())
