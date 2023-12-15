# Include User input of a Month and Day of the current year

import subprocess
import csv
from datetime import datetime

NODE_NAME = "Your-node-name"

FULL_PATH_BOS = "/home/<user>/.npm-global/lib/node_modules/balanceofsatoshis/"

def execute_command(command):
    # Execute the command and capture the output
    output = subprocess.check_output(command, shell=True, text=True)
    return output

def process_csv(csv_data, notes_filter=None):
    # Initialize sum of Amount
    total_amount = 0

    # Read CSV data
    csv_reader = csv.DictReader(csv_data.splitlines())
    for row in csv_reader:
        # Check if a filter on Notes is specified and apply it
        if notes_filter is None or row['Notes'] == notes_filter:
            # Sum the Amount column
            total_amount += float(row['Amount'])

    return total_amount

def process_invoice_csv(csv_data):
    # Filter and print relevant information
    print("Others Income:")
    csv_reader = csv.DictReader(csv_data.splitlines())
    for row in csv_reader:
        if row['Notes'] != "":
            print(f"  Type:{row['Notes']} - {float(row['Amount']):.2f} SATS")

if __name__ == "__main__":
    # Get the desired day and month from the user
    user_input = input("Enter the day and month (format: month/day): ")
    month, day = map(int, user_input.split('/'))

    # Build commands
    rebalance_command = f"{FULL_PATH_BOS}bos accounting 'payments' --date {day} --month {month} --disable-fiat --csv"
    forwards_command = f"{FULL_PATH_BOS}bos accounting 'forwards' --date {day} --month {month} --disable-fiat --csv"
    invoices_command = f"{FULL_PATH_BOS}bos accounting 'invoices' --date {day} --month {month} --disable-fiat --csv"

    # Execute the commands
    rebalance_output = execute_command(rebalance_command)
    forwards_output = execute_command(forwards_command)
    invoices_output = execute_command(invoices_command)

    # Process CSV data and calculate sums
    total_rebalance_costs = process_csv(rebalance_output, notes_filter='Circular payment routing fee')
    total_forwards_income = process_csv(forwards_output)

    # Print the results with user-provided month and day
    print(f'\nNode: {NODE_NAME} - Date: {month}/{day}')
    print(f'Forwards Income: {total_forwards_income:.2f} SATS')
    print(f'Rebalance Costs: {total_rebalance_costs:.2f} SATS')
    print(f'Daily Profit: {total_forwards_income + total_rebalance_costs:.2f} SATS')

    # Process and print invoice data
    process_invoice_csv(invoices_output)


    # Process and print invoice data
    process_invoice_csv(invoices_output)
