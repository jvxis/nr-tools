import subprocess
import time
import sqlite3
import json
import os
import requests

user_path = os.path.expanduser("~")
db_path = os.path.join(user_path, "lndg/data/db.sqlite3")
charge_lnd_bin = "charge-lnd"
charge_lnd_config_dir = os.path.join(user_path, "charge-lnd/")
mempool_api_url = "https://mempool.space/api/v1/fees/recommended"
charge_lnd_interval = 300

def create_or_update_config(chan_id):
    config_path = os.path.join(charge_lnd_config_dir, f"{chan_id}.conf")
    config_lines = []

    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            config_lines = f.readlines()

    start_idx = None
    end_idx = None
    for i, line in enumerate(config_lines):
        if line.strip().lower() == '[disable-channels]':
            start_idx = i
            for j in range(i + 1, len(config_lines)):
                if config_lines[j].startswith('['):
                    end_idx = j
                    break
            break
    
    if start_idx is not None:
        config_lines[start_idx + 1:end_idx] = [
            f"chan.id = {chan_id}\n",
            "strategy = disable\n"
        ]
    else:
        config_lines.append("\n[disable-channels]\n")
        config_lines.append(f"chan.id = {chan_id}\n")
        config_lines.append("strategy = disable\n")

    with open(config_path, 'w') as f:
        f.writelines(config_lines)

    return config_path

def execute_charge_lnd(config_path):
    result = subprocess.run(
        [charge_lnd_bin, "-c", config_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    print("charge-lnd output:\n", result.stdout)
    if result.stderr:
        print("charge-lnd errors:\n", result.stderr)

def get_channel_info(chan_id):
    command = ["lncli", "getchaninfo", chan_id]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode == 0:
        return json.loads(result.stdout)
    else:
        print(f"Error fetching channel info: {result.stderr}")
        return None

def close_channel(funding_txid, output_index, sat_per_vbyte):
    command = [
        "lncli", "closechannel", 
        "--funding_txid", funding_txid, 
        "--output_index", str(output_index), 
        "--sat_per_vbyte", str(sat_per_vbyte)
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"Channel closed successfully: {result.stdout}")
        return True
    else:
        print(f"Error closing channel: {result.stderr}")
        return False

def check_pending_htlcs(chan_id, db_path):
    print(f"Trying to open database at: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM gui_pendinghtlcs WHERE chan_id = ?", (chan_id,))
    pending_htlcs = cursor.fetchall()
    conn.close()
    if pending_htlcs:
        print(f"Pending HTLC found for channel {chan_id}. Total pending HTLCs: {len(pending_htlcs)}. Retrying in 1 minute...")
        return True
    return False

def get_high_priority_fee():
    response = requests.get(mempool_api_url)
    if response.status_code == 200:
        fees = response.json()
        return fees.get("fastestFee", None)
    else:
        print(f"Error accessing Mempool.Space API: {response.status_code}")
        return None

def main():
    max_fee_rate = int(input("Enter the desired max_fee_rate (sat/vbyte): "))
    
    chan_id = input("Enter the Channel ID (chan_id): ")
    config_path = create_or_update_config(chan_id)
    execute_charge_lnd(config_path)
    
    channel_info = get_channel_info(chan_id)
    
    if channel_info:
        if "chan_point" in channel_info:
            channel_point = channel_info["chan_point"]
            funding_txid, output_index = channel_point.split(':')
        else:
            print("Error: 'chan_point' not found in the channel info.")
            return

        last_charge_lnd_time = time.time()
        
        while True:
            if time.time() - last_charge_lnd_time >= charge_lnd_interval:
                execute_charge_lnd(config_path)
                last_charge_lnd_time = time.time()

            pending_htlcs_exist = check_pending_htlcs(chan_id, db_path)
            if not pending_htlcs_exist:
                high_priority_fee = get_high_priority_fee()
                
                if high_priority_fee is not None:
                    print(f"High priority fee obtained: {high_priority_fee} sat/vbyte.")
                    if high_priority_fee <= max_fee_rate:
                        print(f"Using high priority fee of {high_priority_fee} sat/vbyte to close the channel.")
                        if close_channel(funding_txid, output_index, high_priority_fee):
                            break
                    else:
                        print(f"The high priority fee ({high_priority_fee} sat/vbyte) is greater than the max_fee_rate ({max_fee_rate} sat/vbyte).")
                        print(f"Using max_fee_rate of {max_fee_rate} sat/vbyte to close the channel.")
                        if close_channel(funding_txid, output_index, max_fee_rate):
                            break
                else:
                    print("Failed to retrieve high priority fee. Retrying in 1 minute...")
            time.sleep(60)
    else:
        print("Failed to retrieve channel info.")

if __name__ == "__main__":
    main()
