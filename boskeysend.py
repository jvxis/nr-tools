#!/usr/bin/env python3

import requests
import subprocess
import logging

def main():
    logging.basicConfig(filename='boskeysend.log', level=logging.INFO,
                        format='%(asctime)s %(levelname)s:%(message)s')
    
    try:
        country_code = input("Enter the country code (ISO Alpha-2, e.g., 'br' for Brazil): ").strip().lower()
        message = input("Enter the message you want to send: ")
        max_peers_input = input("Enter the maximum number of peers to send to: ").strip()
        if not max_peers_input.isdigit():
            print("Invalid maximum number of peers")
            logging.error("Invalid maximum number of peers")
            return
        max_peers = int(max_peers_input)
        
        api_url = f"https://mempool.space/api/v1/lightning/nodes/country/{country_code}"
        try:
            response = requests.get(api_url)
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"Error fetching API data: {e}")
            logging.error(f"Error fetching API data: {e}")
            return
        
        data = response.json()
        nodes = data.get('nodes', [])
        if not nodes:
            print(f"No nodes found for country code '{country_code}'.")
            logging.info(f"No nodes found for country code '{country_code}'.")
            return
        
        pubkeys = [node.get('public_key') for node in nodes if node.get('public_key') and node.get('channels', 0) <= 150]
        
        if not pubkeys:
            print(f"No nodes with less than 150 channels found for country code '{country_code}'.")
            logging.info(f"No nodes with less than 150 channels found for country code '{country_code}'.")
            return

        count = 0
        for pubkey in pubkeys:
            if count >= max_peers:
                break
            command = ['bos', 'send', pubkey, '--amount', '1', '--message', message]
            try:
                result = subprocess.run(command, capture_output=True, text=True)
                logging.info(f"Command: {' '.join(command)}")
                logging.info(f"Return code: {result.returncode}")
                logging.info(f"Standard output: {result.stdout}")
                logging.info(f"Standard error: {result.stderr}")
                if result.returncode != 0:
                    print(f"Error sending to {pubkey}: {result.stderr.strip()}")
                    logging.error(f"Error sending to {pubkey}: {result.stderr.strip()}")
            except Exception as e:
                print(f"Error executing command for pubkey {pubkey}: {e}")
                logging.error(f"Error executing command for pubkey {pubkey}: {e}")
            count += 1

    except Exception as e:
        print(f"An error occurred: {e}")
        logging.error(f"An error occurred: {e}")

if __name__ == "__main__":
    main()
