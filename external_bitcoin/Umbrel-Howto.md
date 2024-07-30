# How To use an External Bitcoind Server on Umbrel

## Bitcoin
## First Backup your Files
1. Access Umbrel via SSH
2. Go to `~/umbrel/app-data/bitcoin` and backup the files
   ```
   cp .env .env-bck
   cp exports.sh exports.bck
   cp docker-compose.yml docker-compose.bck
   ```
## Edit the Files with the Changes Below
1. `.env`
   ```
   export APP_BITCOIN_NETWORK='mainnet'
   export APP_BITCOIN_RPC_USER='your_rpc_user'
   export APP_BITCOIN_RPC_PASS='your_rpc_pass'
   export APP_BITCOIN_RPC_AUTH='your_rpc_user:your_rcp_pass'
   ```

2. `exports.sh`
   Replace the file for this one
   [exports.sh](https://github.com/jvxis/nr-tools/blob/main/external_bitcoin/exports.sh)

3. `docker-compose.yml`
   Replace the file for this one
   [docker-compose.yml](https://github.com/jvxis/nr-tools/blob/main/external_bitcoin/docker-compose.yml)
   And replace the lines 20 to 23 with your rpc credentials
   ```
   RPC_USER: your_rpc_user
   BITCOIN_RPC_USER: your_rpc_user
   RPC_PASSWORD: your_rpc_pass
   BITCOIN_RPC_PASSWORD: your_rpc_pass
   ```

## Finishing and Restarting
1 . Stop your Umbrel Bitcoin APP
2 . Remove settings.json and peers.dat inside `~/umbrel/app-data/bitcoin/data/bitcoin/` folder
3 . Star your Umbrel Bitcoin APP

Extra:
To check the connection between your Umbrel and the external Bitcoin Node (Replace RPC data by your own credentials):
   ```
   curl -u your_rpc_user:your_rpc_test --data-binary '{"jsonrpc":"1.0","id":"curltest","method":"getblockchaininfo","params":[]}' -H 'content-type:text/plain;' http://bitcoin.friendspool.club:8085/
   ```
# LND
1. You need to add info or create a lnd.conf file if you don't have one, and it should be placed in `~/<user>/umbrel/app-data/lightning/data/lnd/` folder
2. Include the following lines and replace RPC data by your credentials
   ```
   bitcoind.rpchost=bitcoin.friendspool.club:8085
   bitcoind.rpcuser=your_rpc_user
   bitcoind.rpcpass=your_rpc_pass
   bitcoind.zmqpubrawblock=tcp://bitcoin.friendspool.club:28332
   bitcoind.zmqpubrawtx=tcp://bitcoin.friendspool.club:28333
   ```
3. Restart LND







