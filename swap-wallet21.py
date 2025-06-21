import os
import time
import subprocess
from subprocess import run
import json
import configparser
import re
import argparse
import sys
import random

# Parse the command line arguments
parser = argparse.ArgumentParser(description='Lightning Swap Wallet')
parser.add_argument('-lb', '--local-balance', type=float, default=60,
                    help='Minimum local balance percentage to consider for transactions (default: 60)')
parser.add_argument('-to', '--timeout', type=int, default=300,
                    help='Timeout in seconds for each payment command (default: 300)')
args = parser.parse_args()

# Path to the config.ini file located in the parent directory
config_file_path = 'config.ini'
config = configparser.ConfigParser()
config.read(config_file_path)

full_path_bos = config['system']['full_path_bos']
full_path_lncli = config['paths']['lncli_path']

# Remote pubkey to ignore. Add pubkey or reference in config.ini if you want to use it.
ignore_remote_pubkeys = config['no-swapout']['swapout_blacklist'].split(',')


def get_channels():
    try:
        command = str(full_path_lncli) + " listchannels"
        # Execute the command and capture the output
        command_output = execute_command(command)
        if command_output is None:
            print("Command execution failed, no output to parse.")
            return []
        else:
            # Attempt to parse the JSON output
            try:
                data = json.loads(command_output)
                return data.get('channels', [])
            except json.JSONDecodeError as json_err:
                print(f"JSON parsing error: {json_err}")
                print("Raw command output that caused JSON parsing error:", command_output)
                return []
    except Exception as e:
        print(f"Error executing lncli command: {str(e)}")
        exit(1)

def execute_command(command):
    result = subprocess.run(command, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.stderr:
        print("Error:", result.stderr.decode())
    return result.stdout.decode('utf-8')


def filter_channels(channels):
    filtered_channels = []
    for channel in channels:
        local_balance = int(channel.get('local_balance', 0))
        capacity = int(channel.get('capacity', 1))
        remote_pubkey = channel.get('remote_pubkey', '')
        peer_alias = channel.get('peer_alias', 'Unknown')

        # Check if the remote pubkey is in the ignore list
        if remote_pubkey in ignore_remote_pubkeys:
            continue

        if local_balance >= (args.local_balance / 100) * capacity:
            filtered_channels.append({
                'remote_pubkey': remote_pubkey,
                'peer_alias': peer_alias,
                'local_balance': local_balance,
                'capacity': capacity
            })
    # Sort channels by local_balance in descending order
    filtered_channels.sort(key=lambda x: x['local_balance'], reverse=True)
    return filtered_channels


channel = 0

def send_payments(ln_address, amount, total_amount, interval_seconds, fee_rate, message, peer, filtered_channels):
    channel_index = 0
    success_counter = 0
    total_fee = 0  # Variable to store the total fee
    amount_to_transfer = total_amount

    while total_amount > 0:
        if peer:
            command_to_execute = build_command(ln_address, amount, message, fee_rate, peer)
        else:
            if channel_index < len(filtered_channels):
                peer_alias = filtered_channels[channel_index]['peer_alias']
                remote_pubkey = filtered_channels[channel_index]['remote_pubkey']
                print(f"Total peers: {len(filtered_channels)}")
                print(f"Peer:{channel_index} - {peer_alias}")
                command_to_execute = build_command(ln_address, amount, message, fee_rate, remote_pubkey)
            else:
                print("All peers attempted, shuffling peers and starting over...")
                random.shuffle(filtered_channels)
                channel_index = 0
                continue

        output = execute_payment_command(command_to_execute, timeout=args.timeout)
        if "success" in output.stdout:
            # Extract the fee from the output using a regex
            fee_match = re.search(r'fee:\s+(\d+)', output.stdout.split('paying:')[-1])
            if fee_match:
                fee_amount = int(fee_match.group(1))
                total_fee += fee_amount  # Add the fee to the total fee

            total_amount -= amount
            print(f"✅ Transaction successful with Fee: {fee_amount} sats.\n{output.stdout}\nRemaining amount: {total_amount}\n")
            # Prévia dos sats gastos e PPM acumulado
            spent = total_fee
            ppm = (total_fee / (amount_to_transfer - total_amount)) * 1_000_000 if (amount_to_transfer - total_amount) > 0 else 0
            print(f"📊 Parcial: Sats gastos: {spent} | PPM: {ppm:.2f}\n")
            if total_amount > 0:
                success_counter += amount
                if should_retry_transaction(channel_index, success_counter, filtered_channels):
                    peer_alias = filtered_channels[channel_index]['peer_alias']
                    print(f"Trying again as remaining local balance is higher than {args.local_balance}%: {peer_alias}")
                else:
                    channel_index += 1
                    success_counter = 0  # Reset success counter for the next peer
            else:
                print("Execution finished 🎉")
        else:
            print(f"❌ Transaction failed {output.stderr}. Moving to next peer...\n")
            # Prévia dos sats gastos e PPM acumulado mesmo em caso de erro
            spent = total_fee
            ppm = (total_fee / (amount_to_transfer - total_amount)) * 1_000_000 if (amount_to_transfer - total_amount) > 0 else 0
            print(f"📊 Parcial: Sats gastos: {spent} | PPM: {ppm:.2f}\n")
            channel_index += 1
            success_counter = 0  # Reset success counter on failure

        time.sleep(interval_seconds if "success" in output.stdout else 5)

    print("-" * 80)
    print(" " * 25 + f"Total fee amount: {total_fee} sats")
    print(" " * 25 + f"Total PPM:{(total_fee/amount_to_transfer)*1000000}")
    print("-" * 80)

def build_command(ln_address, amount, message, fee_rate, peer):
    return f"{full_path_bos} send {ln_address} --amount {amount} --message \"{message}\" --max-fee-rate {fee_rate} --out {peer}"


def execute_payment_command(command, timeout=None):
    if timeout is None:
        timeout = args.timeout
    print(f"Executing command: {command}\n")
    try:
        return subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        print(f"⏰ Timeout: Command took longer than {timeout} seconds. Skipping to next peer.\n")
        class TimeoutResult:
            def __init__(self):
                self.stdout = ""
                self.stderr = f"Timeout after {timeout} seconds"
        return TimeoutResult()


def should_retry_transaction(channel_index, success_counter, filtered_channels):
    if channel_index >= len(filtered_channels):
        return False
    remain_capacity_tx = (int(filtered_channels[channel_index]['local_balance']) - success_counter) / int(filtered_channels[channel_index]['capacity'])
    return remain_capacity_tx >= (args.local_balance / 100)


print("-" * 80)
print(" " * 30 + f"Lightning Swap Wallet")
print("-" * 80)

try:
    # Get user input for LN address, amount, and total amount
    while True:
        ln_address = input("📧 Enter LN address: ")
        if not ln_address:
            print("🛑 Invalid LN address. Please enter a valid LN address.")
            continue
        elif not re.match(r'^[a-zA-Z0-9_.-]+@[a-zA-Z0-9_.-]+\.[a-zA-Z0-9_.-]+$', ln_address):
            print("🛑 Invalid LN address. Please enter a valid LN address.")
            continue
        break


    while True:
        total_amount_to_transfer = input("💰 Enter total amount to transfer: ")
        try:
            total_amount = int(total_amount_to_transfer)
        except ValueError:
            print("🛑 Invalid amount. Please enter a valid number.")
            continue
        break

    while True:
        amount = input("💸 Enter amount per transaction: ")
        try:
            amount = int(amount)
        except ValueError:
            print("🛑 Invalid amount. Please enter a valid number.")
            continue
        break

    while True:
        interval = input("⌛ Enter the interval in seconds between transactions: ")
        try:
            interval_seconds = int(interval)
        except ValueError:
            print("🛑 Invalid interval. Please enter a valid number.")
            continue
        break

    while True:
        fee_rate = input("🫰 Enter the max fee rate in ppm: ")
        try:
            fee_rate = int(fee_rate)
        except ValueError:
            print("🛑 Invalid fee rate. Please enter a valid number.")
            continue
        break

    message = input("🗯️ Payment Message: ")

    peer = input("🫗 Out Peer Alias or Pubkey: ")
    if not peer:
        peer = None
        print("\n📢 No peer specified, trying first with heavy outbound peers...")
        print(f"\n📋Getting peers with local balance >= {args.local_balance}%...")
        channels = get_channels()
        filtered_channels = filter_channels(channels)
    else:
        # Define filtered_channels as an empty list when a peer is specified
        filtered_channels = []

except KeyboardInterrupt:
    print("\nExiting...")
    sys.exit(0)

# Send payments
send_payments(ln_address, amount, total_amount, interval_seconds, fee_rate, message, peer, filtered_channels)
