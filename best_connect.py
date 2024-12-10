import json
import subprocess

# Function to get socket information for a given public key
def get_socket_info(public_key):
    url = f"https://mempool.space/api/v1/lightning/nodes/{public_key}"
    response = subprocess.check_output(["curl", "-sSL", url])
    node_data = json.loads(response)

    # Extract the first socket value (assuming sockets can have multiple values separated by commas)
    sockets = node_data.get("sockets", "").split(",")[0].strip()
    return sockets

# Function to execute the connection command
def execute_connection_command(public_key, sockets):
    command = f"lncli connect {public_key}@{sockets}"
    print(f"Connecting: Node {public_key}")
    print("Command:", command)
    subprocess.run(command, shell=True)

# API call to get public keys based on connectivity rankings
url_connectivity = "https://mempool.space/api/v1/lightning/nodes/rankings/connectivity"
response_connectivity = subprocess.check_output(["curl", "-sSL", url_connectivity])
data_connectivity = json.loads(response_connectivity)

# Process each node in the connectivity data
for node in data_connectivity:
    public_key = node["publicKey"]
    alias = node["alias"]
    print(f"Connecting to Node {alias}\n")
    # Get socket information
    sockets = get_socket_info(public_key)

    # Execute connection command
    execute_connection_command(public_key, sockets)
