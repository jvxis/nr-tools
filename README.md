![image](https://github.com/jvxis/nr-tools/assets/108929149/fb74f232-2efc-447e-8a2c-f38d7b8ced6e)

# NR-TOOLS
**Essential and Life-Saver Tools for Node Runners.**

All these tools are helping me a lot with my Lightning Node [Friendspool⚡🍻](http://amboss.space/c/friendspool)

![image](https://github.com/jvxis/nr-tools/assets/108929149/cb1f61ad-5acb-4aca-b21c-8b61ae487a10)


## Basic Setup
**How to Setup Telegram Bot:**
1. Create a Telegram Bot:
Open the Telegram app and search for the "BotFather" bot.
Start a chat with BotFather and use the /newbot command to create a new bot.
Follow the instructions to set up your bot and obtain the API token.
2. Get Your Chat ID:
Start a chat with your newly created bot.
Visit the following URL in your web browser, replacing <YOUR_BOT_TOKEN> with the actual token you obtained:
bash
`https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
Look for the "chat" object within the response. The "id" field in that object is your chat ID.
3. Get your TELEGRAM USER ID (This is very important to ensure you are the only user authorized to use the bot
Access https://t.me/userinfobot and this will return your TELEGRAM_USER_ID

**Repository Installation:**
1. Git Clone the Repository: `git clone https://github.com/jvxis/nr-tools.git`

##

## [swap-wallet21.py](https://github.com/jvxis/nr-tools/blob/main/swap-wallet21.py)
This is the best and cheapest tool ever for swaps out (from Lightning to On-chain)
Send SATS from your Lightning node directly to any Lightning Address. 
You can send it out to your strike lightning address and send it back to your node to your on-chain wallet with no FEES.

**Preparation**
1. Get the `config.ini` file https://github.com/jvxis/nr-tools/blob/main/config.ini
2. You need to change the lines to your configuration. `nano config.ini`

        *[paths]*
        # set your paths in case you cron-job it: $ whereis lncli
        # replace pathtoumbrel for your full path for umbrel directory
        lncli_path = /pathtoumbrel/scripts/app compose lightning exec lnd lncli

        *[system]*
        # replace userpath for your full parent path to the .npm-global directory
        full_path_bos = /userpath/.npm-global/lib/node_modules/balanceofsatoshis/bos

3. SAVE `CTRL+O` and Exit `CTRL+X`

**How to Run**
1. You can run the code with the argument --local-balance <percentage>. Ex. `python3 swap-wallet21.py --local-balance 40`
This will first consider the channels where the local liquidity is above 40%
2. When you run the code, you should reply to some questions.
   ![image](https://github.com/jvxis/nr-tools/assets/108929149/c5c8701e-c3ed-4cdc-98f5-b4b96162e4d0)
3. You can choose a specific peer or leave it blank
4. The program will end only after the total amount informed is transferred
5. Tips: Use a wallet service with free withdrawals like Strike, and define a smaller amount per transaction.

## [lntools-bot.py](https://github.com/jvxis/nr-tools/blob/main/lntools-bot.py)
You can control your Lightning Node using Telegram. This tool allows you to pay invoices, generate invoices, send SATs, and much more.
All available commands

        1. `/onchainfee <amount> <fee_per_vbyte> - Calculate on-chain fee`
        2. `/pay <payment_request> - Pay a Lightning invoice`
        3. `/invoice <amount> <message> <expiration_seconds> - Create a Lightning invoice`
        4. `/bckliquidwallet - Backup Liquid wallet`
        5. `/newaddress - Get a new onchain address`
        6. `/sign <message> - Sign a message`
        7. `/connectpeer <peer address> - connect to a peer`
        8. `/openchannel <public key> <size in sats> <fee rate in sats/vB> - open a channel using UTXOS`
        9. `/lndlog <optional all docker logs parameters> and | grep something - Shows LND logs`
        10.`/sendsats <lnaddress> <amount> <memo> <peer> (optional) - send sats to a lnaddress`

**Preparation**
1. Get the `config.py` file https://github.com/jvxis/nr-tools/blob/main/config.py
2. You need to change the lines to your configuration. `nano config.py`

        PATH_TO_UMBREL = "YOUR-FULL-PATH-TO-UMBREL"
        # Path to your elements wallets:
        BCK_SOURCE_PATH = "/home/<user>/app-data/elements/data/liquidv1/wallets"
        # Any external folder, external storage device where you want to place the backup:
        BCK_DEST_PATH = "/mnt/backup/liquid"
        # Chat ID: https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates:
        CHAT_ID="CHAT_ID"
        NODE="NODE NAME"

        # Please check if it is the right path for your BOS Binary:
        FULL_PATH_BOS = "/home/<user>/.npm-global/lib/node_modules/balanceofsatoshis/"
3. SAVE `CTRL+O` and Exit `CTRL+X`
4. Now you need your telegram User ID, please keep it safe for you ONLY.
5. Access https://t.me/userinfobot type `/start` and this will return your TELEGRAM_USER_ID

**How to Setup**
1. Open lntools-bot.py file `nano lntools-bot.py`
2. Change Line 8 sys.path.append('/path/to/nr-tools/') to your path, if you cloned it on your user it should be `/home/user/nr-tools/`
3. Change Lines:
   
        # Insert your Telegram bot token
        TELEGRAM_BOT_TOKEN = "YOUR-TELEGRAM-BOT-TOKEN"
        #Get it on https://t.me/userinfobot
        TELEGRAM_USER_ID = "YOUR-TELEGRAM-USER-ID" 
        BOS_PATH = "path_to_your_BOS_binary"

5. SAVE `CTRL+O` and EXIT `CTRL+X`

Now you can run it `python3 lntools-bot.py`
To run on the background you can use `screen` or setup it as a service: `screen -S lntools-bot python3 lntools-bot.py`

## [htlcScan.sh](https://github.com/jvxis/nr-tools/blob/main/htlcScan.sh)
This script checks for pending stuck htlcs that are near expiration height (< 13 blocks). It collects peers of critical htlc and disconnects / reconnects them to reestablish the htlc. Sometimes htlcs are being resolved before expiration this way and thus costly force closes can be prevented.

**How to Setup:**
1. open the code: `cd nr-tools` and `nano htlcScan.sh`
2. Include your Bot Token and Chat ID to receive telegram messages
3. Replace the line 26 `_CMD_LNCLI="/path_to_umbrel/scripts/app compose lightning exec -T lnd lncli"` with your Umbrel diretory Path
4. Optionally set up the `blocks_til_expiry=13` on line 75 to a higher number
5. Save the Script - CTRL + O
6. Leave the editor - CTRL + X
7. Make the script an executable: `sudo chmod +x htlcScan.sh`
8. Setup CRON to run the script every 30 minutes - `sudo crontab -e`
9. Add the line: `*/30 * * * * /bin/bash /home/<USER>/nr-tools/htlcScan.sh`
10. CTRL + O to save and CTRL + X to leave editor

**Done!**

##

## [check_channelsdb_size.sh](https://github.com/jvxis/nr-tools/blob/main/check_channelsdb_size.sh)
This script checks the LND database size and restarts the lND and other services if it is bigger than 12GB. 

**How to Setup:**
1. open the code: `cd nr-tools` and `nano check_channelsdb_size.sh`
2. Include your Bot Token and Chat ID to receive telegram messages
3. Replace on line 4 /path_to_umbrel with the path for your Umbrel Directory `file_path="/path_to_umbrel/app-data/lightning/data/lnd/data/graph/mainnet/channel.db"`
4. Setup with the size that you usually restart LND on line 7 `threshold_size="12000000000"`
5. Replace lines 41 and 48, where is /path_to_umbrel with path for your Umbrel Directory
6. Save the Script - CTRL + O
7. Leave the editor - CTRL + X
8. Make the script an executable: `sudo chmod +x check_channelsdb_size.sh`
9. Setup CRON to run the script every 1 hour - `sudo crontab -e`
10. Add the line: `0 * * * * /bin/bash /home/<USER>/nr-tools/check_channelsdb_size.sh`
11. CTRL + O to save and CTRL + X to leave editor

**Done!**

##

## [service_on_off.py](https://github.com/jvxis/nr-tools/blob/main/service_on_off.py)
This is a telegram bot to start, stop and restart Umbrel services. You can use /on name_of_service to start some services

**How to Setup:**
1. open the code: `cd nr-tools` and `nano service_on_off.py`
2. Include your Bot Token and your Telegram user Id to receive telegram messages
3. Replace /path_to_umbrel with your path to Umbrel directory`SCRIPT_PATH = "/path_to_umbrel/scripts/app"`
4. Save the Script - CTRL + O
5. Leave the editor - CTRL + X
6. Install Dependencies: `pip3 install pyTelegramBotAPI`
7. Run the code: `python3 service_on_off.py`

You can also run it with a screen command to keep it executing in background: `screen -S service-on-off python3 service_on_off.py`

**Usage:**
On your telegram app inside the BOT, you can type:
- /on lightning - to turn on lnd
- /off lightning - to turn off lnd
- /boot lighting - to restart lnd
The same can be done with any Umbrel Services. Like, bitcoin, circuit-breaker, tailscale, lightning-terminal etc.

**Done!**

##

## [sats4plus.py](https://github.com/jvxis/nr-tools/blob/main/sats4plus.py)
This script sells some info about your node every day, channels, and their capacity, and you get some SATs back as payment for this info

Portuguese Instructions by Redin: https://github.com/jvxis/nr-tools/blob/main/SATS4.txt

**Pre-reqs**
1. You need to set up an account on https://sparkseer.space
2. Then you need to get the API-KEY
3. Click on Node and then Account and click on the button GENERATE APY KEY
![image](https://github.com/jvxis/nr-tools/assets/108929149/6b320d56-7e6a-41f6-a3ca-d404635fe9fa)
4. Open the code: `cd nr-tools` and `nano sats4plus.py`
5. Replace the line 12 with your API KEY: `API_KEY = "SPARKEER_API_KEY"`
6. On line 55 replace /path_to_umbrel with the path to your Umbrel directory: `["/path_to_umbrel/scripts/app", "compose", "lightning", "exec", "lnd", "lncli", "querymc"],`
7. Save the Script - CTRL + O
5. Leave the editor - CTRL + X
6. Install Dependencies: `pip3 install requests`
7. Run the code: `python3 sats4plus.py`

Recommended to execute this code as a Linux Service or with screen: `screen -S sats4 python3 sats4plus.py`

**Done!**

##

## [utxo-consolidator.py](https://github.com/jvxis/nr-tools/blob/main/utxo-consolidator.py)
Generates a BOS Fund command to consolidate your unspent UTXOS.

**Pre-reqs**
You need Balance of Satoshis (BOS) installed

**Usage:**
1. Just run `python3 utxo-consolidator.py`

** This program only generates the command, so you should first check it, copy, paste and then RUN.

**Done!**

##

## [get_node_daily_balance.py](https://github.com/jvxis/nr-tools/blob/main/get_node_daily_balance.py)
This code runs with your crontab every day and saves your node balance, considering Forwards and Rebalances

**Pre-reqs**
You need Balance of Satoshis (BOS) installed

**How to Setup:**
1. open the code: `cd nr-tools` and `get_node_daily_balance.py`
2. Replace `NODE_NAME = "Your-node-name"` with your Node Alias
3. Replace `FULL_PATH_BOS = "/home/<user>/.npm-global/lib/node_modules/balanceofsatoshis/"`This is very important to set up right to run with Crontab
4. Save the Script - CTRL + O
5. Leave the editor - CTRL + X
6. open crontab with the command `crontab -e`
7. Add a line: `0 0 * * * /usr/bin/python3 /home/<user>/get_node_daily_balance.py >> /home/<user>/node-balance.log 2>&1` Please check if it is the right path in your system.
8. Save the Script - CTRL + O
9. Leave the editor - CTRL + X

** This code will save your node daily balance in the file `/home/<user>/node-balance.log`

** If you want to run adhoc for a specific date and month please run the code [get_node_balance.py](https://github.com/jvxis/nr-tools/blob/main/get_node_balance.py)

**Done!**

##

# [Disable and Close any Lightning Channel - Script](https://github.com/jvxis/nr-tools/blob/main/closechannel.py)

This repository contains a Python script designed to disable a specific Lightning Network channel using `charge-lnd` before closing it. The script checks for pending HTLCs, ensures that the channel remains disabled, and uses dynamic fee rates to close the channel efficiently.

## Table of Contents

- [Requirements](#requirements)
- [Installation](#installation)
- [Usage](#usage)
- [Example Screenshot](#example-screenshot)
- [Running With Screen](#running-the-script-automatically-with-screen)

## Requirements

Before running the script, ensure you have the following installed:

- **Python 3.7+**
- **lncli** (part of LND)
- **charge-lnd** ([charge-lnd GitHub repository](https://github.com/accumulator/charge-lnd))
- **LNDg** ([LNDg Github](https://github.com/cryptosharks131/lndg))
- **Requests library** (Python library for HTTP requests)

## Installation

### 1. **Install Python dependencies:**

Ensure you have requests installed:
```
pip install requests
```

### 2. **Install and configure charge-lnd:**

Follow the instructions on the official [charge-lnd GitHub](https://github.com/accumulator/charge-lnd) repository to install and configure charge-lnd on your system.

## Usage

### 1. **Run the Script**

To run the script, execute the following command:

```
python3 closechannel.py
```

### 2. **Follow the On-Screen Instructions**

* Enter the desired max_fee_rate: This is the maximum fee rate in sat/vbyte that you are willing to pay to close the channel.
* Enter the Channel ID: Provide the channel ID (chan_id) of the channel you wish to disable and close.**

### 3. **Watch the Script in Action**

### 4. **The script will:**

* Disable the channel by creating/updating a configuration file in the specified directory.
* Run charge-lnd to apply the configuration and disable the channel.
* Check for pending HTLCs and wait until they are cleared.
* Re-run charge-lnd periodically to ensure the channel remains disabled.
* Close the channel using the specified fee rate or a dynamic fee rate obtained from Mempool.Space.

### 5. **Monitor the Output**

* The script provides detailed output, showing each step of the process, including any errors encountered.

## Example Screenshot

![image](https://github.com/user-attachments/assets/d34e7650-2387-4695-a548-80dcf737261b)

## Running the Script Automatically with `screen`

To avoid manually monitoring the script in the terminal, you can run it in a `screen` session. This allows the script to continue running in the background, even if you disconnect from your session. You can also reattach to the session later to check on the progress.

### Step-by-Step Guide:

### 1. **Install `screen` (if not already installed)**

If `screen` is not already installed, you can install it using your package manager:

- **Debian/Ubuntu:**

```
  sudo apt-get install screen
```

### 2. **Start a new screen session**

Open your terminal and navigate to the directory where the script is located:

``` 
cd /path/to/your-repository
```
Start a new screen session with a name of your choice:

```
screen -S <name_of_your_choice>
```

### 3. **Run the script inside the screen session**

Once inside the screen session, run your Python script:

```
python3 closechannel.py
```

### 4. **Detach from the screen session**

You can now detach from the screen session and leave the script running in the background:

* Detach from the session by pressing Ctrl + A, then D.

Your script will continue running even after you close the terminal.

### 5. **Reattach to the screen session later**

* If you want to check on the progress or logs of the running script, you can reattach to the screen session:

List all running screen sessions to find your session name:

```
screen -ls
```

Reattach to your session:

```
screen -r <your_session_name>
```

Now, you can see the output of your script and interact with it if necessary.

### 6. **Exit the screen session when done**

When your script has finished and you no longer need the session, you can exit the screen session by simply typing:

```
exit
```

This will close the session.
