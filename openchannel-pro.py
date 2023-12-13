#Dependencies: Box of Satoshis
import subprocess

#Replace with your full path to Umbrel directory.
path_to_umbrel = "Your_Path_TO_Umbrel"

def connect_to_node(node_key_address):
    command = f"{path_to_umbrel}/scripts/app compose lightning exec lnd lncli connect {node_key_address}"
    process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, error = process.communicate()
    output = output.decode("utf-8")

    if process.returncode == 0:
        print(f"Successfully connected to node {node_key_address}")
    else:
        print(f"Error connecting to node {node_key_address}: {error}")


def get_utxos():
    command = "bos utxos"
    process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, error = process.communicate()
    output = output.decode("utf-8")
    utxos = {'amounts': [], 'outpoints': []}

    if output:
        lines = output.split('\n')
        for line in lines:
            if "amount:" in line:
                amount = float(line.split()[1]) * 100000000
                utxos['amounts'].append(amount)
            if "outpoint:" in line:
                outpoint = str(line.split()[1])
                utxos['outpoints'].append(outpoint)

    return utxos

# Calcula o tamanho da transação em vBytes
def calculate_transaction_size(utxos_needed):
    inputs_size = utxos_needed * 57.5  # Cada UTXO é de 57.5 vBytes
    outputs_size = 2 * 43  # Dois outputs de 43 vBytes cada
    overhead_size = 10.5  # Overhead de 10.5 vBytes
    total_size = inputs_size + outputs_size + overhead_size
    return total_size

def calculate_utxos_required_and_fees(amount_input, fee_per_vbyte):
    utxos_data = get_utxos()
    total = sum(utxos_data['amounts'])
    utxos_needed = 0
    amount_with_fees = amount_input
    related_outpoints = []

    if total < amount_input:
        print("Não há UTXOs suficientes para transferir o valor desejado.")
        return -1, 0, None

    for utxo_amount, utxo_outpoint in zip(utxos_data['amounts'], utxos_data['outpoints']):
        utxos_needed += 1
        transaction_size = calculate_transaction_size(utxos_needed)
        fee_cost = transaction_size * fee_per_vbyte
        amount_with_fees = amount_input + fee_cost

        related_outpoints.append(utxo_outpoint)

        if utxo_amount >= amount_with_fees:
            break
        amount_input -= utxo_amount

    return utxos_needed, fee_cost, related_outpoints if related_outpoints else None

# Example usage:
node_key_address= input("Informe o public key e host do Node (formato pubkey@host):")
input_amount = float(input("Digite o valor desejado para transacionar em satoshis: "))
fee_per_vbyte = float(input("\nInsira a fee on-chain em sat/vByte: "))

node_pub_key, node_host = node_key_address.split('@', 1)

utxos_needed, onchain_fee_cost, all_outpoints = calculate_utxos_required_and_fees(input_amount, fee_per_vbyte)

if utxos_needed >= 0:
    formatted_input_amount = f"{input_amount:,.0f}".replace(",", ".")
    formatted_onchain_fee_cost = f"{onchain_fee_cost:,.0f}".replace(",", ".")
    print(f"\nSão necessárias {utxos_needed} UTXOs para transferir {formatted_input_amount} satoshis.")
    print(f"A fee on-chain necessária para a transação é: {formatted_onchain_fee_cost} satoshis")
    print(f"All outpoints related to the utxos considered: {all_outpoints}")
    print(f"Connecting with peer: {node_pub_key}")
    connect_to_node(node_key_address)
    formatted_outpoints = ' '.join([f'--utxo {outpoint}' for outpoint in all_outpoints])
    print(f"\nComando de abertura do canal:\n{path_to_umbrel}/scripts/app compose lightning exec lnd lncli openchannel --node_key {node_pub_key} --sat_per_vbyte={int(fee_per_vbyte)} {formatted_outpoints} --local_amt={int(input_amount)}")

else:
    print("Não há UTXOs suficientes.")
