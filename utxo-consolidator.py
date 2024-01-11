#Utxo Consolidator
#Generates a BOS Fund command to consolidate your UTXOS
#ATTENTION - You need to generate a NEW On-chain Address in your WALLET

#Dependencies Balance of Satoshis (BOS)

import subprocess

def get_utxos():
    command = "bos utxos --confirmed"
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

def calculate_transaction_size(num_utxos):
    input_size_per_utxo = 57.5
    output_size = 43
    overhead_size = 10.5
    
    total_input_size = num_utxos * input_size_per_utxo
    total_size = total_input_size + output_size + overhead_size
    
    return total_size

def display_utxos_info(user_amount, new_address):
    utxos_data = get_utxos()

    filtered_utxos = [(outpoint, amount) for outpoint, amount in zip(utxos_data['outpoints'], utxos_data['amounts']) if amount <= user_amount]

    total_filtered_amount = sum(amount for _, amount in filtered_utxos)
    num_filtered_utxos = len(filtered_utxos)

    # Transaction size
    utxos_needed = num_filtered_utxos
    transaction_size = calculate_transaction_size(utxos_needed)

    # Total onchain fee
    fee_cost = transaction_size * fee_per_vbyte

    print(f"\nTotal number of UTXOs with amounts less than or equal to {user_amount:.0f} satoshis: {num_filtered_utxos} utxos")
    print(f"\nTotal amount of UTXOs with amounts less than or equal to {user_amount:.0f} satoshis: {total_filtered_amount:.0f} satoshis")
    print(f"\nTransaction Size for {utxos_needed} UTXOs: {transaction_size:.2f} vBytes")
    print(f"\nTransaction Fee at {fee_per_vbyte} sat/vByte: {fee_cost:.0f} satoshis")

    print("\nList of UTXOs:")
    for outpoint, amount in filtered_utxos:
        print(f"Outpoint: {outpoint}, Amount: {amount:.0f} satoshis")

    utxo_arguments = ' '.join([f'--utxo {outpoint}' for outpoint, _ in filtered_utxos])
    bos_fund_command = f"bos fund {new_address} {int(total_filtered_amount)} {utxo_arguments}"
    print("\nBOS Fund Command:")
    print(bos_fund_command)

# Example usage:
user_amount = float(input("\nEnter the desired amount in satoshis: "))
fee_per_vbyte = float(input("\nEnter the fee rate in sat/vByte: "))
new_address = input("\nEnter the onchain address for funding: ")
display_utxos_info(user_amount, new_address)
