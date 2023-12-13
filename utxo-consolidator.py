#Utxo Consolidator
#Generates a BOS Fund command to consolidate your UTXOS
#ATTENTION - You need to generate a NEW On-chain Address in your WALLET

#Dependencies Box of Satoshis (BOS)

import subprocess

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

def display_utxos_info(user_amount, new_address):
    utxos_data = get_utxos()

    # Filter UTXOs based on user's amount
    filtered_utxos = [(outpoint, amount) for outpoint, amount in zip(utxos_data['outpoints'], utxos_data['amounts']) if amount <= user_amount]

    # Calculate the sum of amounts for filtered UTXOs
    total_filtered_amount = sum(amount for _, amount in filtered_utxos)

    # Display the sum of amounts for filtered UTXOs
    print(f"Total amount of UTXOs with amounts less than or equal to {user_amount:.0f} satoshis: {total_filtered_amount:.0f} satoshis")

    # Display the list of outpoints and their respective amounts for filtered UTXOs
    print("\nList of UTXOs:")
    for outpoint, amount in filtered_utxos:
        print(f"Outpoint: {outpoint}, Amount: {amount:.0f} satoshis")

    # Display the bos fund command line
    utxo_arguments = ' '.join([f'--utxo {outpoint}' for outpoint, _ in filtered_utxos])
    bos_fund_command = f"bos fund {new_address} {int(total_filtered_amount)} {utxo_arguments}"
    print(f"\nBOS Fund Command:")
    print(bos_fund_command)

# Example usage:
user_amount = float(input("Enter the desired amount in satoshis: "))
new_address = input("Enter the new address for funding: ")
display_utxos_info(user_amount, new_address)
