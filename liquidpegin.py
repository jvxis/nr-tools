# This is an experimental code, please use it with caution
# This is the fist part of the Pegin Process, where you get a pegin address and send sats to this address
import requests
import subprocess
import json

user1="elements"
# Your Elements Core RPC password - To get it, just open your Elements App, if you are not using Umbrel, check it on elements.conf file
password1="fc967730052bb3a437e4857....."

rpc_url = f"http://{user1}:{password1}@127.0.0.1:7041"
headers = {'content-type': 'application/json'}

path_to_umbrel = "your_path_to_umbrel" # Ex: /home/Your_User/umbrel/scripts/app

# Prepare JSON-RPC request
payload_getpegin = {
        "method": "getpeginaddress",
        "params": [],
        "jsonrpc": "2.0",
        "id": 0,
    }
print("Starting Onchain->Liquid Peg-in Process\n")
#GetPegInAddress
try:
    
    # Make the HTTP request
    print("Getting Peg-in Address...\n")
    response = requests.post(rpc_url, json=payload_getpegin, headers=headers)

    # Check for HTTP errors
    response.raise_for_status()

    # Parse the JSON response
    result = response.json()
    print(f"Json Result: {result}\n")
    # Access the desired data
    mainchain_address = result["result"]["mainchain_address"]
    claim_script = result["result"]["claim_script"]
    print(f"Mainchain Address: {mainchain_address}\n")
    print(f"Claim Script: {claim_script}\n")

except requests.exceptions.RequestException as request_exception:
    print("A Request Exception occurred: " + str(request_exception))
    exit()
except Exception as general_exception:
    print("An Exception occurred: " + str(general_exception))
    exit()

print("Sending Onchain to Peg-in Address...\n")
#Send BTC Onchain to the Address
# Take user input for amount and satoshis per byte
try:
    sats_amount = int(input("Enter the amount in satoshis: "))
    sat_per_byte = int(input("Enter the fee rate in satoshis per byte: "))
except ValueError:
    print("Invalid input. Please enter valid integers for amount and satoshis per byte.")
    exit()

# Construct the command
command = [
        f"{path_to_umbrel}",
        "compose",
        "lightning",
        "exec",
        "lnd",
        "lncli",
        "sendcoins",
        "--addr",
        mainchain_address,
        "--amt",
        str(sats_amount),
        "--sat_per_byte",
        str(sat_per_byte),
        "--force",
    ]

try:
    # Execute the command and capture the output
    print(f"Sending {str(sats_amount)} sats to address {mainchain_address} with {str(sat_per_byte)} sat/vB\n")
    result = subprocess.run(command, check=True, capture_output=True, text=True)

    # Parse the JSON response from the command output
    try:
        output_json = json.loads(result.stdout)
    except json.JSONDecodeError as json_error:
        print(f"Error decoding JSON from command output: {json_error}")
        exit()

    # Access the txid from the JSON response
    txid = output_json.get("txid")

    if txid:
        print(f"Transaction ID (txid): {txid}")
    else:
        print("Transaction ID not found in the command output.")

except subprocess.CalledProcessError as error:
    print(f"Error executing the command: {error}")
    exit()
except Exception as general_exception:
    print(f"An exception occurred: {general_exception}")
    exit()
