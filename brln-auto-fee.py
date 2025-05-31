# Needs LNDG and BOS installed and configured
import sqlite3
import time
import datetime
import os
from collections import defaultdict
import telebot

# Replace with your Telegram Bot Token
TELEGRAM_TOKEN = "YOUR_TELEGRAM_TOKEN"
# Replace with your Chat ID
CHATID = "YOUR_CHAT_ID"
# Initialize Telebot with your Telegram bot token
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Path to the correct SQLite database !Check if this is the right path for your setup
DB_PATH = '/home/admin/lndg/data/db.sqlite3'

BOS_PATH = "/home/admin/.npm-global/lib/node_modules/balanceofsatoshis/"

# Calculate the date 7 days ago from today
today = datetime.datetime.now(datetime.timezone.utc)
date_7_days_ago = today - datetime.timedelta(days=7)

# Exclusion list of public keys to skip
EXCLUSION_LIST = [
    '03a961ab70c0011eff3b91b6a3afb81967597c1f27325a51dbfee72a692f1bb237',  # lnvoltz.com
    '024700001dd2f801c6489983b528ae4895e0815b34b60729affd68c4e681ab9f4d',  # Bitcoiners
    '0255457f1231750f726caf0ef32cfdfd1066df0012676e28f72cacc9ea96d67646',  # Kriptoeleutheria
    '021c97a90a411ff2b10dc2a8e32de2f29d2fa49d41bfbb52bd416e460db0747d0d',  # LOOP
    '03864ef025fde8fb587d989186ce6a4a186895ee44a926bfc370e2c366597a3f8f',  # ACINQ
    '035e4ff418fc8b5554c5d9eea66396c227bd429a3251c8cbc711002ba215bfc226',  # WalletOfSatoshi.com
    '03271338633d2d37b285dae4df40b413d8c6c791fbee7797bc5dc70812196d7d5c',  # lnmarkets.com
    '02d96eadea3d780104449aca5c93461ce67c1564e2e1d73225fa67dd3b997a6018',  # Boltz|CLN
    '026165850492521f4ac8abd9bd8088123446d126f648ca35e60f88177dc149ceb2',  # Boltz
    '033d8656219478701227199cbd6f670335c8d408a92ae88b962c49d4dc0e83e025',  # bfx-lnd0
    '03cde60a6323f7122d5178255766e38114b4722ede08f7c9e0c5df9b912cc201d6',  # bfx-lnd1
    '0294ac3e099def03c12a37e30fe5364b1223fd60069869142ef96580c8439c2e0a',  # okx
    '02f1a8c87607f415c8f22c00593002775941dea48869ce23096af27b0cfdcc0b69',  # Kraken
    '0324ba2392e25bff76abd0b1f7e4b53b5f82aa53fddc3419b051b6c801db9e2247',  # Kappa
    '033e9ce4e8f0e68f7db49ffb6b9eecc10605f3f3fcb3c630545887749ab515b9c7',  # Lnbig hub2
    '03da1c27ca77872ac5b3e568af30673e599a47a5e4497f85c7b5da42048807b3ed',  # Lnbig edge3
    '026af41af0e3861ba170cc0eef8f45a1015125dac57c28df53752dcaeea793b28f',  # BitcoinVN 22
    '03797da684da0b6de8a813f9d7ebb0412c5d7504619b3fa5255861b991a7f86960',  # BitcoinJungle
    '02f4c77dcf12255ccf705c18b8d6b95e4f884910bf61e8aa21242607193a79da1b',  # WCC-Bouncer
    '02b2ae15001601b74eee8ddbd036315c5fbd415b24f88f24d5266820169dfd13de'   #lndwr3 - strike
]

# SQL Query to fetch payments with non-null 'rebal_chan' and 'chan_out', ordered by 'rebal_chan' and 'creation_date' in descending order
SQL_PAYMENTS_QUERY = """
SELECT payment_hash, creation_date, value, fee, chan_out, rebal_chan, chan_out_alias
FROM gui_payments
WHERE rebal_chan IS NOT NULL AND chan_out IS NOT NULL
AND creation_date BETWEEN ? AND ?
ORDER BY rebal_chan, creation_date DESC;
"""

# SQL Query to fetch forwards with non-null 'chan_id_out', ordered by 'chan_id_out' and 'forward_date' in descending order
SQL_FORWARDS_QUERY = """
SELECT chan_id_out, chan_out_alias, amt_out_msat, fee
FROM gui_forwards
WHERE chan_id_out IS NOT NULL
AND forward_date BETWEEN ? AND ?
ORDER BY chan_id_out, forward_date DESC;
"""

# SQL Query to fetch the alias, fee data, and remote_pubkey from gui_channels based on rebal_chan
ALIAS_AND_FEES_QUERY = """
SELECT alias, local_fee_rate, remote_fee_rate, ar_max_cost, remote_pubkey FROM gui_channels WHERE chan_id = ? AND is_open = 1;
"""

def connect_to_db(retries=5, delay=2):
    """Try to connect to the SQLite database with a retry mechanism if it's locked."""
    for attempt in range(retries):
        try:
            print(f"Attempting to connect to the database (attempt {attempt + 1})...")
            conn = sqlite3.connect(DB_PATH)
            return conn
        except sqlite3.OperationalError as e:
            if 'database is locked' in str(e):
                print(f"Database is locked. Retrying {attempt + 1}/{retries}...")
                time.sleep(delay)
            else:
                print(f"OperationalError: {str(e)}")
                raise e
        except Exception as e:
            print(f"Error: {str(e)}")
            raise e
    raise Exception("Unable to connect to the database after multiple retries.")

def get_rebal_chan_info(cursor, rebal_chan):
    """Get the alias, local_fee_rate, remote_fee_rate, ar_max_cost, and remote_pubkey for the rebal_chan from the gui_channels table."""
    cursor.execute(ALIAS_AND_FEES_QUERY, (rebal_chan,))
    result = cursor.fetchone()
    if result:
        return result  # alias, local_fee_rate, remote_fee_rate, ar_max_cost, remote_pubkey
    return "Unknown", 0, 0, 0, None  # Return default values if no entry found

def calculate_overall_fee_rate(total_fees, total_values):
    """Calculate the overall fee rate in ppm (parts per million)."""
    if total_values == 0:  # Avoid division by zero
        return 0
    return (total_fees / total_values) * 1_000_000

def issue_bos_command(peer_pubkey, update_fee):
    """Issue the bos fees command to update the fee rate for the peer."""
    command = f"{BOS_PATH}bos fees --set-fee-rate {update_fee} --to {peer_pubkey}"
    print(f"Executing: {command}")
    os.system(command)
    
def send_telegram_messages_in_batches(messages, chat_id, bot, batch_size=4096):
    """Send large Telegram messages in batches to avoid exceeding the character limit."""
    full_message = "\n".join(messages)
    
    if len(full_message) <= batch_size:
        bot.send_message(chat_id, full_message)
    else:
        # Split the message into multiple parts if it exceeds the limit
        while len(full_message) > 0:
            chunk = full_message[:batch_size]
            bot.send_message(chat_id, chunk)
            full_message = full_message[batch_size:]

def fetch_payments(conn):
    """Fetch and filter payments from the gui_payments table."""
    cursor = conn.cursor()
    
    # Execute the SQL query with the date range as parameters
    cursor.execute(SQL_PAYMENTS_QUERY, (date_7_days_ago, today))
    
    # Fetch all results
    results = cursor.fetchall()

    payment_summary_data = defaultdict(lambda: {"total_fees": 0, "total_values": 0, "payment_count": 0, "alias": "", "remote_pubkey": ""})

    if results:
        print(f"Found {len(results)} payments with 'rebal_chan' and 'chan_out' not null:")
        for payment in results:
            payment_hash, creation_date, value, fee, chan_out, rebal_chan, chan_out_alias = payment
            
            # Get the alias, fee rates, and remote_pubkey for the rebal_chan from the gui_channels table
            rebal_chan_alias, local_fee_rate, remote_fee_rate, ar_max_cost, remote_pubkey = get_rebal_chan_info(cursor, rebal_chan)
            
            # Collect total fees and values for each rebal_chan alias
            payment_summary_data[rebal_chan]["total_fees"] += fee
            payment_summary_data[rebal_chan]["total_values"] += value
            payment_summary_data[rebal_chan]["payment_count"] += 1
            payment_summary_data[rebal_chan]["alias"] = rebal_chan_alias
            payment_summary_data[rebal_chan]["local_fee_rate"] = local_fee_rate
            payment_summary_data[rebal_chan]["remote_fee_rate"] = remote_fee_rate
            payment_summary_data[rebal_chan]["ar_max_cost"] = ar_max_cost
            payment_summary_data[rebal_chan]["remote_pubkey"] = remote_pubkey

    return payment_summary_data

def fetch_forwards(conn):
    """Fetch and filter forwards from the gui_forwards table."""
    cursor = conn.cursor()

    # Execute the SQL query with the date range as parameters
    cursor.execute(SQL_FORWARDS_QUERY, (date_7_days_ago, today))

    # Fetch all results
    results = cursor.fetchall()

    forward_summary_data = defaultdict(lambda: {"total_fees": 0, "total_amt_out": 0, "forward_count": 0})

    if results:
        print(f"Found {len(results)} forwards with 'chan_id_out' not null:")
        for forward in results:
            chan_id_out, chan_out_alias, amt_out_msat, fee = forward

            # Collect total fees and values for each chan_out alias
            forward_summary_data[chan_id_out]["total_fees"] += fee
            forward_summary_data[chan_id_out]["total_amt_out"] += amt_out_msat
            forward_summary_data[chan_id_out]["forward_count"] += 1
            forward_summary_data[chan_id_out]["alias"] = chan_out_alias

    return forward_summary_data

def main():
    try:
        # Attempt to connect to the database
        conn = connect_to_db()

        # Fetch and display the filtered payments
        payment_summary_data = fetch_payments(conn)

        # Fetch and display the forwards data
        forward_summary_data = fetch_forwards(conn)
        
        # Summary: Collect all messages to send at once
        telegram_messages = []
        telegram_messages.append("🏃 Updating Local Fees...")

        # Summary: Calculate the overall fee rate by rebal_chan and provide recommendations
        print("\nSummary by Channel Alias:")
        for rebal_chan, data in payment_summary_data.items():
            total_fees = data["total_fees"]
            total_values = data["total_values"]
            payment_count = data["payment_count"]
            rebal_chan_alias = data["alias"]
            local_fee_rate = data["local_fee_rate"]
            remote_fee_rate = data["remote_fee_rate"]
            ar_max_cost = data["ar_max_cost"]
            remote_pubkey = data["remote_pubkey"]

            # Calculate the overall fee rate for payments
            overall_fee_rate = calculate_overall_fee_rate(total_fees, total_values)

            # Calculate the new local fee rate based on the ar_max_cost
            if ar_max_cost > 0:  # Avoid division by zero
                new_local_fee_rate = overall_fee_rate / (ar_max_cost / 100)

            # Match forward data for the same `rebal_chan`
            if rebal_chan in forward_summary_data:
                forward_data = forward_summary_data[rebal_chan]
                total_forward_fees = forward_data["total_fees"]
                total_amt_out = forward_data["total_amt_out"]
                forward_count = forward_data["forward_count"]
                forward_chan_alias = forward_data["alias"]

                # Calculate the overall out fee rate for forwards
                overall_out_fee_rate = calculate_overall_fee_rate(total_forward_fees, total_amt_out / 1000)  # Convert msat to sat
                message=""
                # Final recommendation
                if new_local_fee_rate > remote_fee_rate and forward_count == 0:
                    # Reduzindo a fee em 30%
                    update_fee = int(local_fee_rate*(1-0.3))
                    print(f"\nRebalance Channel Alias: {rebal_chan_alias} | Payments: {payment_count} | Overall Rebal Fee Rate: {overall_fee_rate:.2f} ppm")
                    print(f"Out Channel Alias: {forward_chan_alias} | Forwards: {forward_count} | Overall Out Fee Rate: {overall_out_fee_rate:.2f} ppm")
                    print(f"Channel {rebal_chan_alias} current fee rate {local_fee_rate} ppm recommends changing it to Rebal Rate Adjusted {new_local_fee_rate:.2f} ppm, consider that the Out Rate is {overall_out_fee_rate:.2f} ppm")
                    print(f"Local Fee Recommendation: {update_fee} ppm")
                    # Skip excluded pubkeys and when local fee = suggested fee
                    if remote_pubkey in EXCLUSION_LIST:
                        print(f"Skipping update for excluded pubkey {remote_pubkey} ({rebal_chan_alias})")
                        message += f"\n🛑 Channel {rebal_chan_alias} - Out Rate: {int(overall_out_fee_rate)} ppm | Rebal Rate {int(overall_fee_rate)} ppm | Skipped Exclusion List"
                    elif int(local_fee_rate) == int(new_local_fee_rate):
                        print(f"Skipping update for {remote_pubkey} ({rebal_chan_alias}) as Local Fee is already the suggested one")
                        message += f"\n🫤 Channel {rebal_chan_alias} - Out Rate: {int(overall_out_fee_rate)} ppm | Rebal Rate {int(overall_fee_rate)} ppm | Nothing to do: Local Fee = Suggested" 
                    else:
                        issue_bos_command(remote_pubkey, update_fee)
                        message += f"\n🤷‍♂️ Channel {rebal_chan_alias} - Out Rate: {int(overall_out_fee_rate)} ppm | Rebal Rate {int(overall_fee_rate)} ppm | Local Fee Updated: From {int(local_fee_rate)} to {update_fee} ppm"    
                
                if new_local_fee_rate > remote_fee_rate and new_local_fee_rate < overall_out_fee_rate:
                    update_fee = int(new_local_fee_rate + (overall_out_fee_rate - new_local_fee_rate) / 2)
                    print(f"\nRebalance Channel Alias: {rebal_chan_alias} | Payments: {payment_count} | Overall Rebal Fee Rate: {overall_fee_rate:.2f} ppm")
                    print(f"Out Channel Alias: {forward_chan_alias} | Forwards: {forward_count} | Overall Out Fee Rate: {overall_out_fee_rate:.2f} ppm")
                    print(f"Channel {rebal_chan_alias} current fee rate {local_fee_rate} ppm recommends changing it to Rebal Rate Adjusted {new_local_fee_rate:.2f} ppm, consider that the Out Rate is {overall_out_fee_rate:.2f} ppm")
                    print(f"Local Fee Recommendation: {update_fee} ppm")

                    # Skip excluded pubkeys and when local fee = suggested fee
                    if remote_pubkey in EXCLUSION_LIST:
                        print(f"Skipping update for excluded pubkey {remote_pubkey} ({rebal_chan_alias})")
                        message += f"\n🛑 Channel {rebal_chan_alias} - Out Rate: {int(overall_out_fee_rate)} ppm | Rebal Rate {int(overall_fee_rate)} ppm | Skipped Exclusion List"
                    elif int(local_fee_rate) == update_fee:
                        print(f"Skipping update for {remote_pubkey} ({rebal_chan_alias}) as Local Fee is already the suggested one")
                        message += f"\n🫤 Channel {rebal_chan_alias} - Out Rate: {int(overall_out_fee_rate)} ppm | Rebal Rate {int(overall_fee_rate)} ppm | Nothing to do: Local Fee = Suggested"
                    else:
                        # Issue the bos command to update the fee rate
                        issue_bos_command(remote_pubkey, update_fee)
                        message += f"\n💵 Channel {rebal_chan_alias} - Out Rate: {int(overall_out_fee_rate)} ppm | Rebal Rate {int(overall_fee_rate)} ppm | Local Fee Updated: From {int(local_fee_rate)} to {update_fee} ppm"
 
                if new_local_fee_rate > remote_fee_rate and int(overall_fee_rate) > overall_out_fee_rate and overall_out_fee_rate != 0:
                    update_fee = int(overall_fee_rate - (overall_fee_rate - overall_out_fee_rate) / 2)
                    print(f"\nRebalance Channel Alias: {rebal_chan_alias} | Payments: {payment_count} | Overall Rebal Fee Rate: {overall_fee_rate:.2f} ppm")
                    print(f"Out Channel Alias: {forward_chan_alias} | Forwards: {forward_count} | Overall Out Fee Rate: {overall_out_fee_rate:.2f} ppm")
                    print(f"Channel {rebal_chan_alias} current fee rate {local_fee_rate} ppm recommends changing it to Rebal Rate Adjusted {new_local_fee_rate:.2f} ppm, consider that the Out Rate is {overall_out_fee_rate:.2f} ppm")
                    print(f"Local Fee Recommendation: {update_fee} ppm")
                    # Skip excluded pubkeys and when local fee = suggested fee
                    if remote_pubkey in EXCLUSION_LIST:
                        print(f"Skipping update for excluded pubkey {remote_pubkey} ({rebal_chan_alias})")
                        message += f"\n🛑 Channel {rebal_chan_alias} - Out Rate: {int(overall_out_fee_rate)} ppm | Rebal Rate {int(overall_fee_rate)} ppm | Skipped Exclusion List"
                    elif int(local_fee_rate) == int(new_local_fee_rate):
                        print(f"Skipping update for {remote_pubkey} ({rebal_chan_alias}) as Local Fee is already the suggested one")
                        message += f"\n🫤 Channel {rebal_chan_alias} - Out Rate: {int(overall_out_fee_rate)} ppm | Rebal Rate {int(overall_fee_rate)} ppm | Nothing to do: Local Fee = Suggested" 
                    else:
                        issue_bos_command(remote_pubkey, update_fee)
                        message += f"\n💸 Channel {rebal_chan_alias} - Out Rate: {int(overall_out_fee_rate)} ppm | Rebal Rate {int(overall_fee_rate)} ppm | Local Fee Updated: From {int(local_fee_rate)} to {update_fee} ppm"
                
                
                
                telegram_messages.append(message)
        # Send all collected messages at once or in batches
        send_telegram_messages_in_batches(telegram_messages, CHATID, bot)

    except Exception as e:
        print(f"An error occurred: {str(e)}")

    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    main()
