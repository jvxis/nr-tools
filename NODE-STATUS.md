# Node Status Install Instructions
![image](https://github.com/jvxis/minibolt/assets/108929149/a520ff0c-7de4-4489-9657-413312cb995f)

`First, be sure that you can execute the commands bitcoin-cli and lncli with your user. If you don't, you need to check GO Path.`

File in folder: https://github.com/jvxis/nr-tools/tree/main/nodestatus

## Initial Setup
1. Dependencies:
   Flask Library
   ```bash
   pip3 install flask
   ```
   Requests Library
   ```bash
   pip3 install requests
   ```
3. Get the files node-status.py, status.html, and message.txt
4. Place node-status.py in your user directory `/home/user/`
5. Make a directory `templates`
   ```bash
   sudo mkdir templates
   ```
6. Move the files `status.html` and `message.txt` to the directory `/home/user/templates`

7. Edit the file `message.txt` and write anything you want

8. Open the file `node-status.py` and fill out with your Bitcoind credentials

   BITCOIN_RPC_USER = 'YOUR_BITCOIN_RPCUSER'

   BITCOIN_RPC_PASSWORD = 'YOUR_BITCOIN_RPCPASS'

   BITCOIN_RPC_HOST = 'YOUR_BITCOIN_MACHINE_IP'

   BITCOIN_RPC_PORT = '8332'

9. Save and Exit

10. Execute:
   ```bash
   python3 node-status.py
   ```
11. Now you can access `HTTP://your_machine_ip:5000/status`
   
