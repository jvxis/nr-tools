from flask import Flask, render_template
import subprocess
import json
import requests
import psutil
import cpuinfo
import sensors
from collections import defaultdict

# Configuration settings
RUNNING_ENVIRONMENT = 'umbrel'  # Change to 'umbrel' for Umbrel systems or 'minibolt' for minibolt / raspibolt or any standalone
RUNNING_BITCOIN = 'local'  # Change to 'external' if you are running Bitcoin Core on another machine
# Only if your running Bitcoin Core on another machine
BITCOIN_RPC_USER = 'YOUR_BITCOIN_RPCUSER'
BITCOIN_RPC_PASSWORD = 'YOUR_BITCOIN_RPCPASS'
BITCOIN_RPC_HOST = 'YOUR_BITCOIN_MACHINE_IP'  # Use 127.0.0.1 if Bitcoind is running on the same machine of the script installation
BITCOIN_RPC_PORT = '8332'
# for Umbrel Users
UMBREL_PATH = "/path/to/umbrel/scripts/"  # Path to Umbrel app

# message to display
MESSAGE_FILE_PATH = '/home/<user>/nr-tools/nodestatus/templates/message.txt'  # Path to the message file

app = Flask(__name__)

def run_command(command):
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {command}\n{result.stderr}")
    return result.stdout

def get_bitcoin_info():
    if RUNNING_ENVIRONMENT == 'minibolt' and RUNNING_BITCOIN == 'external':
        bitcoin_cli_base_cmd = [
            'bitcoin-cli',
            '-rpcuser={}'.format(BITCOIN_RPC_USER),
            '-rpcpassword={}'.format(BITCOIN_RPC_PASSWORD),
            '-rpcconnect={}'.format(BITCOIN_RPC_HOST),
            '-rpcport={}'.format(BITCOIN_RPC_PORT)
        ]
        blockchain_info_cmd = bitcoin_cli_base_cmd + ['getblockchaininfo']
        peers_info_cmd = bitcoin_cli_base_cmd + ['getpeerinfo']
        network_info_cmd = bitcoin_cli_base_cmd + ['getnetworkinfo']
    elif RUNNING_ENVIRONMENT == 'minibolt' and RUNNING_BITCOIN == 'local':
        bitcoin_cli_base_cmd = ['bitcoin-cli']
        blockchain_info_cmd = bitcoin_cli_base_cmd + ['getblockchaininfo']
        peers_info_cmd = bitcoin_cli_base_cmd + ['getpeerinfo']
        network_info_cmd = bitcoin_cli_base_cmd + ['getnetworkinfo']
    else:  # umbrel
        blockchain_info_cmd = [f"{UMBREL_PATH}app", "compose", "bitcoin", "exec", "bitcoind", "bitcoin-cli", 'getblockchaininfo']
        peers_info_cmd = [f"{UMBREL_PATH}app", "compose", "bitcoin", "exec", "bitcoind", "bitcoin-cli", 'getpeerinfo']
        network_info_cmd = [f"{UMBREL_PATH}app", "compose", "bitcoin", "exec", "bitcoind", "bitcoin-cli", 'getnetworkinfo']

    blockchain_data = json.loads(run_command(blockchain_info_cmd))
    peers_data = json.loads(run_command(peers_info_cmd))
    network_data = json.loads(run_command(network_info_cmd))

    return {
        "sync_percentage": blockchain_data["verificationprogress"] * 100,
        "current_block_height": blockchain_data["blocks"],
        "chain": blockchain_data["chain"],
        "pruned": blockchain_data["pruned"],
        "number_of_peers": len(peers_data),
        "bitcoind": BITCOIN_RPC_HOST,
        "version": network_data["version"],
        "subversion": network_data["subversion"]
    }

def get_lnd_info():
    if RUNNING_ENVIRONMENT == 'minibolt':
        lncli_cmd = ['lncli']
    else:  # umbrel
        lncli_cmd = [f"{UMBREL_PATH}app", "compose", "lightning", "exec", "lnd", "lncli"]

    wallet_balance_data = json.loads(run_command(lncli_cmd + ['walletbalance']))
    channel_balance_data = json.loads(run_command(lncli_cmd + ['channelbalance']))
    payments_data = json.loads(run_command(lncli_cmd + ['listpayments']))
    channels_data = json.loads(run_command(lncli_cmd + ['listchannels']))
    peers_data = json.loads(run_command(lncli_cmd + ['listpeers']))
    node_data = json.loads(run_command(lncli_cmd + ['getinfo']))

    return {
        "wallet_balance": int(wallet_balance_data["total_balance"]),  # Ensure this is an integer
        "channel_balance": int(channel_balance_data["balance"]),
        "total_balance": int(wallet_balance_data["total_balance"]) + int(channel_balance_data["balance"]),
        "last_10_payments": payments_data["payments"][-10:],
        "number_of_channels": len(channels_data["channels"]),
        "number_of_peers": len(peers_data["peers"]),
        "node_alias": node_data["alias"],
        "node_lnd_version": node_data["version"],
        "pub_key": node_data["identity_pubkey"],
        "num_pending_channels": node_data["num_pending_channels"],
        "num_active_channels": node_data["num_active_channels"],
        "num_inactive_channels": node_data["num_inactive_channels"],
        "synced_to_chain": node_data["synced_to_chain"],
        "synced_to_graph": node_data["synced_to_graph"]
    }

def read_message_from_file():
    try:
        with open(MESSAGE_FILE_PATH, 'r') as file:
            message = file.read().strip()
        return message
    except FileNotFoundError:
        return "No message found."

def get_fee_info():
    response = requests.get("https://mempool.space/api/v1/fees/recommended")
    return response.json()

def get_cpu_usage():
    return psutil.cpu_percent(interval=1)

def get_memory_usage():
    return psutil.virtual_memory().percent

def get_cpu_info():
    return cpuinfo.get_cpu_info()

def get_physical_disks_usage():
    disk_usage = defaultdict(lambda: {'total': 0, 'used': 0, 'free': 0})
    for partition in psutil.disk_partitions(all=False):
        if 'loop' not in partition.device and 'ram' not in partition.device:
            usage = psutil.disk_usage(partition.mountpoint)
            device = partition.device.split('p')[0]  # Get the base device name, e.g., /dev/nvme0n1
            disk_usage[device]['total'] += usage.total
            disk_usage[device]['used'] += usage.used
            disk_usage[device]['free'] += usage.free

    for device, usage in disk_usage.items():
        usage['percent'] = (usage['used'] / usage['total']) * 100

    return disk_usage

def get_temperatures():
    temperatures = []
    try:
        sensors_temperatures = psutil.sensors_temperatures()
        for name, entries in sensors_temperatures.items():
            for entry in entries:
                if "composite" in entry.label.lower():
                    temperatures.append((name, entry.label, entry.current))
    except AttributeError:
        temperatures.append(("N/A", "N/A", "N/A"))
    return temperatures

def get_sensor_temperatures():
    sensors.init()
    sensor_temps = []
    try:
        for chip in sensors.iter_detected_chips():
            try:
                chip_name = str(chip)
            except sensors.SensorsError as e:
                chip_name = f"Unknown chip ({e})"
            for feature in chip:
                if "composite" in feature.label.lower():
                    try:
                        feature_label = feature.label
                        feature_value = feature.get_value()
                        sensor_temps.append((chip_name, feature_label, feature_value))
                    except sensors.SensorsError as e:
                        sensor_temps.append((chip_name, "Unknown feature", f"Error reading feature: {e}"))
    finally:
        sensors.cleanup()
    return sensor_temps

@app.route('/status')
def status():
    system_info = {
        "cpu_usage": get_cpu_usage(),
        "memory_usage": get_memory_usage(),
        "cpu_info": get_cpu_info(),
        "physical_disks_usage": get_physical_disks_usage(),
        "temperatures": get_temperatures(),
        "sensor_temperatures": get_sensor_temperatures()
    }
    bitcoin_info = get_bitcoin_info()
    lnd_info = get_lnd_info()
    message = read_message_from_file()
    fee_info = get_fee_info()
    return render_template('status.html', system_info=system_info, bitcoind=bitcoin_info, lnd=lnd_info, node_alias=lnd_info["node_alias"], message=message, fee_info=fee_info)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
