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

# Minimum local balance threshold
MIN_BALANCE = 1500000  # Set the minimum balance threshold

# Exclusion list of chan_ids
EXCLUSION_LIST = [
    '891080507132936203',
    '891176164675354632',
    '891176164674764808',
    '965520742847741953', #Boltz
    '925400663131684865', #Acinq
    '918015243549736961',
    '914599060772356097', #bfx ln01
    '884138190664040449', #bfx ln00 small
    '947961542113820673', #bfx ln00 big
    '919866821043879944', #strike
    '963360202535862273', #Kraken
    '965040256218497028', #loop
    '946845537857699841', #Boltz CLN
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
            
            # Adjust MIN_LOCAL_BALANCE for channels with capacity below 5,000,000
            if capacity < 5000000:
                adjusted_min_balance = (capacity * MIN_BALANCE) / 5000000
            else:
                adjusted_min_balance = MIN_BALANCE
            
            if local_balance < adjusted_min_balance and local_fee_rate > (remote_fee_rate / (ar_max_cost / 100)):
                auto_rebalance_needed = True
            else:
                auto_rebalance_needed = False

            if auto_rebalance_needed != auto_rebalance_current:
                data = {"auto_rebalance": auto_rebalance_needed}
                await update_channel(session, chan_id, data)
                
                local_balance_str = f"{local_balance:,}"
                print(f"⚖️Channel: {chan_id} with peer alias {alias} - Local Balance {local_balance_str} - Local Fee {local_fee_rate} - Remote Fee {remote_fee_rate} - AR set to {auto_rebalance_needed}")
                message = f"⚖️Channel: {chan_id} with peer alias {alias} - Local Balance {local_balance_str} - Local Fee {local_fee_rate} - Remote Fee {remote_fee_rate} - AR set to {auto_rebalance_needed}\n"
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
