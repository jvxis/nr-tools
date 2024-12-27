#!/bin/bash

# This script outputs the top 10 channels with the most updates.
# Additionally, it provides the total sum of updates for all channels of the node.
#
# This script aids in pinpointing channels that can be closed/reopened when the overall
# HTLC processing time is sluggish, and the database size has outgrown the capacity
# of the current hardware.
#
# While a sum of around 100 million updates is manageable on a Raspberry Pi (own measures),
# multiples of this value might pose potential issues.
#
#
# usage: bash top10-db-channels.sh
#
# version: 1.0
# date: 2024-12-27

# Define lncli command for different installations
# Bolt/Blitz installation
[ -f ~/.bashrc ] && source ~/.bashrc
[ -z "$_CMD_LNCLI" ] && _CMD_LNCLI=/usr/local/bin/lncli

# Umbrel
UMBREL_CMD="/home/umbrel/umbrel/scripts/app compose lightning exec -T lnd lncli"

# BTC-Pay Server
CONTAINER_NAME="btcpayserver_lnd_bitcoin"
DOCKER_CMD="docker exec $CONTAINER_NAME lncli"

# Determine which lncli command to use
if [ -x "$(command -v lncli)" ]; then
  _CMD_LNCLI=$(command -v lncli)
elif docker ps --format '{{.Names}}' | grep -q "^$CONTAINER_NAME\$"; then
  _CMD_LNCLI=$DOCKER_CMD
else
  _CMD_LNCLI=$UMBREL_CMD
fi

log_file="${0%.sh}.log"
echo "Logging output to ${log_file}"

# Empty the existing log file
truncate -s 0 "$log_file"
date >> "$log_file"
echo "Below are the 10 channels with the most updates" >> "$log_file"

# Initialize sum variable
total_updates=0
count=0

while read -r updates pubkey alias; do
    ((count++))

    # Alias fallback
    [[ -z "$alias" ]] && alias=$($_CMD_LNCLI getnodeinfo --pub_key "$pubkey" | jq -r '.node.alias')
    if [ -z "$alias" ]; then
        echo "Invalid node pubkey: $pubkey"
        exit 1
    fi

    # Apenas para os top 10, escrevemos (e exibimos na tela)
    if [ "$count" -le 10 ]; then
        echo -e "$updates\t$pubkey\t$alias" | tee -a "$log_file"
    else
        # Se quiser logar todos, mas sem imprimir na tela, use somente >> $log_file
        echo -e "$updates\t$pubkey\t$alias" >> "$log_file"
    fi

    total_updates=$((total_updates + updates))
done < <($_CMD_LNCLI listchannels | jq -r '.channels[] | [.num_updates, .remote_pubkey, .peer_alias] | @tsv' | sort -rn)

# Exibimos e logamos o total
echo "Total updates of all channels: $total_updates" | tee -a "$log_file"
