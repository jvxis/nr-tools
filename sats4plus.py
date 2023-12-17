#This script sells some info about your node every day, channels, and their capacity, and you get some SATs back as payment for this info.

import subprocess
import requests
from datetime import datetime, timedelta
import time

#Dependencies
#You need to create an account for your node on https://sparkeer.space

#Replace with your API_KEY - you can get it on https://sparkseer.space/account
API_KEY = "SPARKEER_API_KEY"
PAYMENTS_API_URL = "https://api.sparkseer.space/v1/sats4stats/payouts"

def get_last_payment_time():
    headers = {"api-key": API_KEY}
    response = requests.get(PAYMENTS_API_URL, headers=headers)

    try:
        payouts = response.json().get("payouts", [])
        last_three_payouts = payouts[-3:]
        print("Last 3 payouts:")
        for payout in last_three_payouts:
            date_submitted = payout.get("date_submitted")
            amount = payout["details"][0].get("amount")
            hash_value = payout["details"][0].get("hash")
            print(f"Date: {date_submitted}, Amount: {amount}, Hash: {hash_value}")

        if payouts:
            # Assuming payouts are sorted by time, get the date and time of the latest payout
            latest_payout_time_str = payouts[-1].get("date_submitted")
            latest_payout_time = datetime.strptime(latest_payout_time_str, "%Y-%m-%d %H:%M:%S")
            return latest_payout_time
        else:
            # Assuming is the first time
            return datetime.now().strftime("%d-%m-%Y %H:%M:%S")
    except ValueError:
        print("Error: Unable to parse payouts API response as JSON")
    return None

while True:
    # Get the date and time of the last payment
    last_payment_time = get_last_payment_time()

    if last_payment_time:
        # Calculate the time difference between current time and last payment time
        time_difference = datetime.now() - (last_payment_time - timedelta(hours=3))

        # If the time difference is greater than or equal to 24 hours, execute the main logic
        if time_difference >= timedelta(hours=24):
            # Print date and time
            current_datetime = datetime.now().strftime("%d-%m-%Y %H:%M:%S")
            print(f"Current date and time: {current_datetime}")

            # Execute the command and print the output
            # Replace path_to_umbrel with the path to your Umbrel diretory
            command_output = subprocess.run(
                ["/path_to_umbrel/scripts/app", "compose", "lightning", "exec", "lnd", "lncli", "querymc"],
                capture_output=True,
                text=True
            )

            api_url = "https://api.sparkseer.space/v1/sats4stats/probes"
            headers = {
                "Content-Type": "application/json",
                "api-key": API_KEY
            }

            response = requests.post(api_url, headers=headers, data=command_output.stdout)
            # Extract and print the value of the "error" key or success message
            
            try:
                response_json = response.json()
                if "error" in response_json:
                    error_value = response_json.get("error")
                    print(f"Error value: {error_value}")
                elif "receipt" in response_json:
                    receipt = response_json.get("receipt")
                    settlement_time = receipt.get("settlement_time")
                    amount = receipt.get("amount")
                    hash_value = receipt.get("hash")
                    print(f"Your bid was sent successfully at {settlement_time}. You received {amount} sats, and the hash is {hash_value}")
            except ValueError:
                print("Error: Unable to parse API response as JSON")
            

            # Sleep for one hour
            time.sleep(3600)
        else:
            # If the time difference is less than 24 hours, sleep for the remaining time
            remaining_sleep_time = timedelta(hours=24) - time_difference
            print(f"Waiting for {remaining_sleep_time} hours before checking again.")
            time.sleep(remaining_sleep_time.total_seconds())
    else:
        # If there is an issue getting the last payment time, sleep for an hour and try again
        print("Error: Unable to retrieve last payment time. Retrying in one hour.")
        time.sleep(3600)
