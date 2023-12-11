# nr-tools
Essential and Life-Saver Tools for Node Runners.

All these tools are helping me a lot with my Lightning Node [Friendspool⚡🍻](http://amboss.space/c/friendspool)
![image](https://github.com/jvxis/nr-tools/assets/108929149/c11e6d29-72ab-44ef-a9cb-bb8af8c5365a)

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

**Repository Installation:**
1. Git Clone the Repository: `git clone https://github.com/jvxis/nr-tools.git`

## htlcScan.sh
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

## check_channelsdb_size.sh
This script checks the LND database size and restarts the lND and other services if it is bigger than 12GB. 

**How to Setup:**
1. open the code: `cd nr-tools` and `nano check_channelsdb_size.sh`
2. Include your Bot Token and Chat ID to receive telegram messages
3. Replace on line 4 /path_to_umbrel with the path for your Umbrel Directory `file_path="/path_to_umbrel/app-data/lightning/data/lnd/data/graph/mainnet/channel.db"`
4. Setup with the size that you usually restart LND on line 7 `threshold_size="12000000000"`
5. Replace lines 41 and 48, where is /path_to_umbrel with path for your Umbrel Directory
6. Save the Script - CTRL + O
6. Leave the editor - CTRL + X
7. Make the script an executable: `sudo chmod +x check_channelsdb_size.sh`
8. Setup CRON to run the script every 1 hour - `sudo crontab -e`
9. Add the line: `0 * * * * /bin/bash /home/<USER>/nr-tools/check_channelsdb_size.sh`
10. CTRL + O to save and CTRL + X to leave editor

**Done!**

