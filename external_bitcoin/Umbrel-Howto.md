# How To use an External Bitcoind Server on Umbrel

## First Backup your Files
1. Access Umbrel via SSH
2. Go to `~/umbrel/app-data/bitcoin` and backup the files
   ```
   cp .env .env-bck
   cp exports.sh exports.bck
   cp docker-compose.yml docker-compose.bck
## Edit the Files with the Changes Below
1. `.env`
   ```
   export APP_BITCOIN_NETWORK='mainnet'
   export APP_BITCOIN_RPC_USER='your_rpc_user'
   export APP_BITCOIN_RPC_PASS='your_rpc_pass'
   export APP_BITCOIN_RPC_AUTH='your_rpc_user:your_rcp_pass'

2. `exports.sh`
   Replace the all file for this one

