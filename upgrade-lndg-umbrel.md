# Upgrading Umbrel LNDg Without Waiting for Umbrel (to version 1.9.0)
```bash
cd ~/umbrel/app-data/lndg
cp docker-compose.yml cp docker-compose.bck
nano docker-compose.yml
```
Replace the content of the docker-compose.yml file by the content below:
```bash
version: "3.7"

services:
  app_proxy:
    environment:
      APP_HOST: $APP_LNDG_IP
      APP_PORT: $APP_LNDG_PORT

  web:
    image: ghcr.io/cryptosharks131/lndg:latest@sha256:e91307c2ff42a8618aebcab9a85f99793b52da9100c2f4710dff3fd0d34e8732
    restart: on-failure
    stop_grace_period: 1m
    init: true
    volumes:
      - ${APP_LIGHTNING_NODE_DATA_DIR}:/root/.lnd:ro
      - ${APP_DATA_DIR}:/app/data
      - ${APP_DATA_DIR}/lndg-controller.log:/var/log/lndg-controller.log
    command:
      - sh
      - -c
      - python initialize.py -net '${APP_BITCOIN_NETWORK}' -rpc '${APP_LIGHTNING_NODE_IP}:${APP_LIGHTNING_NODE_GRPC_PORT}' -pw '${APP_PASSWORD}' -wn && python controller.py runserver 0.0.0.0:${APP_LNDG_PORT} > /var/log/lndg-controller.log 2>&1
    networks:
      default:
        ipv4_address: ${APP_LNDG_IP}
```
Restart LNDg
```bash
cd ~/umbrel/scripts
./app restart lndg
```
