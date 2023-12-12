# onchain-fee-calc.py
# This code calcs how much on fees you will spend to send a onchain transaction.
# Credit to @EMTLL_
# Dependencies: Box of Satoshis (BOS)

import subprocess

def get_utxos():
    command = "bos utxos"
    process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, error = process.communicate()
    output = output.decode("utf-8")
    utxos = []

    if output:
        lines = output.split('\n')
        for line in lines:
            if "amount:" in line:
                amount = float(line.split()[1]) * 100000000
                utxos.append(amount)

    return sorted(utxos, reverse=True)

# Calcula o tamanho da transação em vBytes
def calculate_transaction_size(utxos_needed):
    inputs_size = utxos_needed * 57.5  # Cada UTXO é de 57.5 vBytes
    outputs_size = 2 * 43  # Dois outputs de 43 vBytes cada
    overhead_size = 10.5  # Overhead de 10.5 vBytes
    total_size = inputs_size + outputs_size + overhead_size
    return total_size

def calculate_utxos_required_and_fees(amount_input, fee_per_vbyte):
    utxos = get_utxos()
    total = sum(utxos)
    utxos_needed = 0
    amount_with_fees = amount_input

    if total < amount_input:
        print("Não há UTXOs suficientes para transferir o valor desejado.")
        return -1, 0

    for utxo in utxos:
        utxos_needed += 1
        transaction_size = calculate_transaction_size(utxos_needed)
        fee_cost = transaction_size * fee_per_vbyte
        amount_with_fees = amount_input + fee_cost

        if utxo >= amount_with_fees:
            break
        amount_input -= utxo

    return utxos_needed, fee_cost

# Exemplo de utilização:
input_amount = float(input("Digite o valor desejado para transacionar em satoshis: "))
fee_per_vbyte = float(input("\nInsira a fee on-chain em sat/vByte: "))

utxos_needed, onchain_fee_cost = calculate_utxos_required_and_fees(input_amount, fee_per_vbyte)

if utxos_needed >= 0:
    formatted_input_amount = f"{input_amount:,.0f}".replace(",", ".")
    formatted_onchain_fee_cost = f"{onchain_fee_cost:,.0f}".replace(",", ".")
    print(f"\nSão necessárias {utxos_needed} UTXOs para transferir {formatted_input_amount} satoshis.")
    print(f"A fee on-chain necessária para a transação é: {formatted_onchain_fee_cost} satoshis")
else:
    print("Não há UTXOs suficientes.")
