import subprocess
import requests
from datetime import datetime, timedelta, timezone
import time

#This script sells some info about your node every day, channels, and their capacity, and you get some SATs back as payment for this info.

#Dependencies

#You need to create an account for your node on https://sparkseer.space
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
            latest_payout_time_str = payouts[-1].get("date_submitted")
            latest_payout_time = datetime.strptime(latest_payout_time_str, "%Y-%m-%d %H:%M:%S")
            latest_payout_time = latest_payout_time.replace(tzinfo=timezone.utc)
            return latest_payout_time
        else:
            return datetime.now(timezone.utc) - timedelta(hours=24)
    except ValueError:
        print("Error: Unable to parse payouts API response as JSON")
    return None

def main():
    while True:
        last_payment_time = get_last_payment_time()

        if last_payment_time:
            now = datetime.now(timezone.utc)
            time_since_last_payment = now - last_payment_time

            if time_since_last_payment >= timedelta(hours=24):
                current_datetime = now.strftime("%d-%m-%Y %H:%M:%S")
                print(f"Current date and time: {current_datetime}")

                command_output = subprocess.run(
                    ["lncli", "querymc"],
                    capture_output=True,
                    text=True
                )

                api_url = "https://api.sparkseer.space/v1/sats4stats/probes"
                headers = {
                    "Content-Type": "application/json",
                    "api-key": API_KEY
                }

                response = requests.post(api_url, headers=headers, data=command_output.stdout)
                
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

                next_run_time = last_payment_time + timedelta(days=1)
                sleep_duration = (next_run_time - now).total_seconds()
                if sleep_duration < 0:
                    sleep_duration = 0
                print(f"Waiting {sleep_duration} seconds until the next check.")
                time.sleep(sleep_duration)
            else:
                remaining_time = timedelta(hours=24) - time_since_last_payment
                sleep_duration = remaining_time.total_seconds()
                print(f"Waiting {sleep_duration} seconds before checking again.")
                time.sleep(sleep_duration)
        else:
            print("Error: Unable to retrieve last payment time. Retrying in one hour.")
            time.sleep(3600)

if __name__ == "__main__":
    main()