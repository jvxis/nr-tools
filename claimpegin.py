# This is an experimental code, please use it with caution
# This is second part of the Pegin Process, when you can claim your funds.
import requests
import subprocess
import json

user1 = "elements"

#Elements RPC Password from Element Umbrel App - Just Open it and Get the pass
password1 = "fc967730052bb3a437e4857daf...."

rpc_url = f"http://{user1}:{password1}@127.0.0.1:7041"
headers = {'content-type': 'application/json'}

path_to_umbrel = "your_path_to_umbrel"


def get_tx_id_hex(tx_id):
    try:
        url = f"https://mempool.space/api/tx/{tx_id}/hex"
        response = requests.get(url)

        # Check for HTTP errors
        response.raise_for_status()

        # Parse the JSON response
        result = response.json()

        # Access the tx_id_hex from the JSON response
        tx_id_hex = result.get("hex")

        if tx_id_hex:
            return tx_id_hex
        else:
            print("Transaction hex not found in the API response.")
            return None

    except requests.exceptions.RequestException as request_exception:
        print("A Request Exception occurred: " + str(request_exception))
        return None
    except Exception as general_exception:
        print("An Exception occurred: " + str(general_exception))
        return None

print("Peg-in Claiming Process\n")
# Get user input for tx_id and claim_id
tx_id = input("Enter the transaction ID: ")
claim_id = input("Enter the claim ID: ")

# Construct the command
command = [
    f"{path_to_umbrel}/scripts/app",
    "compose",
    "bitcoin",
    "exec",
    "bitcoind",
    "bitcoin-cli",
    "gettxoutproof",
    f'["{tx_id}"]'
]

try:
    # Execute the command and capture the output
    result = subprocess.run(command, check=True, capture_output=True, text=True)

    # Access the output
    txoutproof = result.stdout.strip()

    print(f"Txoutproof: {txoutproof}\n")

except subprocess.CalledProcessError as error:
    print(f"Error executing the command: {error}")
    exit()
except Exception as general_exception:
    print(f"An exception occurred: {general_exception}")
    exit()

# Claim
# Getting the tx_id_hex
print(f"Getting the HEX for the {tx_id}\n")
tx_id_hex = get_tx_id_hex(tx_id)

if tx_id_hex:
    print(f"Transaction ID Hex for {tx_id}: {tx_id_hex}\n")
else:
    print(f"Failed to retrieve Transaction ID Hex for {tx_id}\n")
    exit()

payload_claimpegin = {
    "method": "claimpegin",
    "params": [tx_id_hex, txoutproof, claim_id],
    "jsonrpc": "2.0",
    "id": 0,
}

print("Starting Claim Peg-in Process\n")

print("Claiming ...\n")
try:

    # Make the HTTP request
    response = requests.post(rpc_url, json=payload_claimpegin, headers=headers)

    # Check for HTTP errors
    response.raise_for_status()

    # Parse the JSON response
    result = response.json()
    print(f"Json Result: {result}\n")

except requests.exceptions.RequestException as request_exception:
    print("A Request Exception occurred: " + str(request_exception))
    exit()
except Exception as general_exception:
    print("An Exception occurred: " + str(general_exception))
    exit()
