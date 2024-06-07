from flask import Flask, render_template
import subprocess
import json
import requests

BITCOIN_RPC_USER = 'YOUR_BITCOIN_RPCUSER'
BITCOIN_RPC_PASSWORD = 'YOUR_BITCOIN_RPCPASS'
BITCOIN_RPC_HOST = 'YOUR_BITCOIN_MACHINE_IP' # Use 127.0.0.1 if Bitcoind is running on the same machine of the script installation
BITCOIN_RPC_PORT = '8332'
MESSAGE_FILE_PATH = '/home/admin/templates/message.txt'  # Path to the message file


app = Flask(__name__)

def get_bitcoin_info():
    # Construct the bitcoin-cli command with RPC details
    bitcoin_cli_base_cmd = [
        'bitcoin-cli',
        '-rpcuser={}'.format(BITCOIN_RPC_USER),
        '-rpcpassword={}'.format(BITCOIN_RPC_PASSWORD),
        '-rpcconnect={}'.format(BITCOIN_RPC_HOST),
        '-rpcport={}'.format(BITCOIN_RPC_PORT)
    ]
    blockchain_info_cmd = bitcoin_cli_base_cmd + ['getblockchaininfo']
    blockchain_info = subprocess.run(blockchain_info_cmd, capture_output=True, text=True)
    blockchain_data = json.loads(blockchain_info.stdout)
    peers_info_cmd = bitcoin_cli_base_cmd + ['getpeerinfo']
    peers_info = subprocess.run(peers_info_cmd, capture_output=True, text=True)
    peers_data = json.loads(peers_info.stdout)
    network_info_cmd = bitcoin_cli_base_cmd + ['getnetworkinfo']
    network_info = subprocess.run(network_info_cmd, capture_output=True, text=True)
    network_data = json.loads(network_info.stdout)
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
    wallet_balance_info = subprocess.run(['lncli', 'walletbalance'], capture_output=True, text=True)
    wallet_balance_data = json.loads(wallet_balance_info.stdout)
    channel_balance_info = subprocess.run(['lncli', 'channelbalance'], capture_output=True, text=True)
    channel_balance_data = json.loads(channel_balance_info.stdout)
    payments_info = subprocess.run(['lncli', 'listpayments'], capture_output=True, text=True)
    payments_data = json.loads(payments_info.stdout)
    channels_info = subprocess.run(['lncli', 'listchannels'], capture_output=True, text=True)
    channels_data = json.loads(channels_info.stdout)
    peers_info = subprocess.run(['lncli', 'listpeers'], capture_output=True, text=True)
    peers_data = json.loads(peers_info.stdout)
    node_info = subprocess.run(['lncli', 'getinfo'], capture_output=True, text=True)
    node_data = json.loads(node_info.stdout)
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

@app.route('/status')
def status():
    bitcoin_info = get_bitcoin_info()
    lnd_info = get_lnd_info()
    message = read_message_from_file()
    fee_info = get_fee_info()
    return render_template('status.html', bitcoind=bitcoin_info, lnd=lnd_info, node_alias=lnd_info["node_alias"], message=message, fee_info=fee_info)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
