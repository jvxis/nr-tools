# Node Status Install Instructions
![image](https://github.com/jvxis/minibolt/assets/108929149/a520ff0c-7de4-4489-9657-413312cb995f)

`First, be sure that you can execute the commands bitcoin-cli and lncli with your user. If you don't, you need to check GO Path.`

File in folder: https://github.com/jvxis/nr-tools/tree/main/nodestatus

## Initial Setup
1. Dependencies:
   Python Libraries
   ```bash
   pip3 install flask
   pip3 install requests
   pip3 install psutil py-cpuinfo
   sudo apt-get update
   sudo apt-get install lm-sensors libsensors4-dev
   pip3 install pysensors
   ```
##Below is for a manual installation without `git clone`

2. Get the files node-status.py, status.html, and message.txt

3. Place node-status.py in your user directory `/home/user/nr-tools/nodestatus`
   
4. Make a directory `templates`
   ```bash
   sudo mkdir templates
   ```
5. Move the files `status.html` and `message.txt` to the directory `/home/user/nr-tools/nodestatus/templates`

6. Edit the file `message.txt` and write anything you want
7. Open the file `node-status.py` and fill out your configurations
   
   RUNNING_ENVIRONMENT = 'umbrel'  - Change to 'umbrel' for Umbrel systems or 'minibolt' for minibolt / raspibolt or any standalone
   
   RUNNING_BITCOIN = 'local'  - Change to 'external' if you are running Bitcoin Core on another machine

   UMBREL_PATH = "/path/to/umbrel/scripts/"  - Path to Umbrel app for Umbrel users only

## Only for Bitcoin Core Running on Another machine
7. Open the file `node-status.py` and fill out with your Bitcoind credentials

   BITCOIN_RPC_USER = 'YOUR_BITCOIN_RPCUSER'

   BITCOIN_RPC_PASSWORD = 'YOUR_BITCOIN_RPCPASS'

   BITCOIN_RPC_HOST = 'YOUR_BITCOIN_MACHINE_IP'

   BITCOIN_RPC_PORT = '8332'

## Last Steps
8. Save and Exit

9. Execute:
   ```bash
   python3 node-status.py
   ```
10. Now you can access `HTTP://your_machine_ip:5000/status`
   
