
# Monitoramento de fechamento de canais e sweeps pendentes LND
# JVX

set -euo pipefail

# Telegram setup
TOKEN="YOUR TELEGRAM TOKEN"
CHATID="YOUR CHAT ID"

# Bloco atual
BLOCKS_PER_HOUR=6

# Função para enviar mensagem ao Telegram
send_telegram() {
    local message="$1"
    curl -s -X POST "https://api.telegram.org/bot$TOKEN/sendMessage" \
      -d chat_id="$CHATID" \
      -d parse_mode="Markdown" \
      -d text="$message" > /dev/null
}

# Função para pegar o alias do node (com cache simples)
declare -A NODE_ALIASES

get_alias() {
    pubkey="$1"
    if [[ -n "${NODE_ALIASES[$pubkey]:-}" ]]; then
        echo "${NODE_ALIASES[$pubkey]}"
    else
        alias_name=$(lncli getnodeinfo "$pubkey" 2>/dev/null | grep alias | head -n1 | cut -d '"' -f4)
        if [[ -z "$alias_name" ]]; then
            alias_name="$pubkey"
        fi
        NODE_ALIASES[$pubkey]="$alias_name"
        echo "$alias_name"
    fi
}

# Função para capturar o status resumido
capture_status() {
    local pending_count sweeps_count balance
    pending_count=$(lncli pendingchannels | jq '[.pending_force_closing_channels[]] | length')
    sweeps_count=$(lncli wallet pendingsweeps | jq '[.pending_sweeps[]] | length')
    balance=$(lncli walletbalance | jq -r '.confirmed_balance')
    echo "$pending_count;$sweeps_count;$balance"
}

# Função para detalhar no terminal
detailed_status() {
    CURRENT_BLOCK=$(bitcoin-cli getblockcount)

    pending=$(lncli pendingchannels)
    sweeps=$(lncli wallet pendingsweeps)

    declare -A SWEEP_OUTPOINTS
    for outpoint in $(echo "$sweeps" | jq -r '.pending_sweeps[].outpoint'); do
        SWEEP_OUTPOINTS[$outpoint]=1
    done

    clear
    printf "========== ⚡ STATUS DO NODE ⚡ ==========\n\n"

    printf "📦 1. Canais pendentes de fechar:\n\n"
    echo "$pending" | jq -c '.pending_force_closing_channels[]' | while read -r channel; do
        pubkey=$(echo "$channel" | jq -r '.channel.remote_node_pub')
        alias=$(get_alias "$pubkey")
        limbo_balance=$(echo "$channel" | jq -r '.limbo_balance')
        recovered_balance=$(echo "$channel" | jq -r '.recovered_balance')
        closing_txid=$(echo "$channel" | jq -r '.closing_txid')
        pending_htlcs=$(echo "$channel" | jq -c '.pending_htlcs')

        printf "🔗 Peer Alias: %s\n" "$alias"
        printf "💰 Limbo Balance: %s sats\n" "$limbo_balance"

        if [[ "$pending_htlcs" == "[]" ]]; then
            printf "⏳ Pending HTLCs: Nenhum HTLC pendente\n"
        else
            echo "$pending_htlcs" | jq -c '.[]' | while read -r htlc; do
                amount=$(echo "$htlc" | jq -r '.amount')
                maturity_height=$(echo "$htlc" | jq -r '.maturity_height')
                blocks_til=$(($maturity_height - $CURRENT_BLOCK))
                hours_til=$(($blocks_til / $BLOCKS_PER_HOUR))
                printf "⏳ Pending HTLCs: - Amount: %s sats | Matura em ~%s horas\n" "$amount" "$hours_til"
            done
        fi

        sweep_found=false
        for i in {0..5}; do
            key="$closing_txid:$i"
            if [[ -n "${SWEEP_OUTPOINTS[$key]:-}" ]]; then
                sweep_found=true
                printf "🔄 Aguardando sweep do outpoint: %s\n" "$key"
            fi
        done

        if [[ "$sweep_found" == false && "$limbo_balance" == "0" ]]; then
            printf "⚠️ Canal zerado, sem sweeps pendentes. Pode ser stuck no LND.\n"
        fi

        printf "✅ Recovered Balance: %s sats\n\n" "$recovered_balance"
    done

    printf "\n🪹 2. Sweeps pendentes:\n\n"
echo "$sweeps" | jq -c '.pending_sweeps[]' | while read -r sweep; do
    outpoint=$(echo "$sweep" | jq -r '.outpoint')
    amount_sat=$(echo "$sweep" | jq -r '.amount_sat')
    requested_sat_per_vbyte=$(echo "$sweep" | jq -r '.requested_sat_per_vbyte')
    deadline_height=$(echo "$sweep" | jq -r '.deadline_height')

    blocks_til_deadline=$((deadline_height - CURRENT_BLOCK))
    if (( blocks_til_deadline < 0 )); then
        blocks_til_deadline=0
    fi
    hours_til_deadline=$((blocks_til_deadline / BLOCKS_PER_HOUR))

    printf "🪹 Outpoint: %s\n" "$outpoint"
    printf "💰 Amount: %s sats\n" "$amount_sat"
    printf "🚀 Fee Rate: %s sat/vB\n" "$requested_sat_per_vbyte"
    printf "⏳ Sweep Deadline: ~%s horas (estimado)\n\n" "$hours_til_deadline"
done

    printf "\n💰 3. Saldo On-Chain:\n"
    lncli walletbalance | jq '{confirmed_balance, unconfirmed_balance}'

    printf "\n⚡ 4. Saldo Lightning:\n"
    lncli channelbalance | jq '{local_balance, remote_balance, unsettled_local_balance, unsettled_remote_balance}'

    printf "\n========== 🚀 MONITORAMENTO COMPLETO 🚀 ==========\n"
}

# Captura inicial
status_before=$(capture_status)
pending_before=$(echo "$status_before" | cut -d ';' -f1)
sweeps_before=$(echo "$status_before" | cut -d ';' -f2)
balance_before=$(echo "$status_before" | cut -d ';' -f3)

# Envia status inicial
initial_msg="⚡ *Initial Node Status* ⚡

• Pending Channels: *$pending_before*
• Pending Sweeps: *$sweeps_before*
• On-chain Balance: *$balance_before* sats
"
send_telegram "$initial_msg"

# Loop infinito
while true; do
    detailed_status

    sleep 3600

    status_after=$(capture_status)
    pending_after=$(echo "$status_after" | cut -d ';' -f1)
    sweeps_after=$(echo "$status_after" | cut -d ';' -f2)
    balance_after=$(echo "$status_after" | cut -d ';' -f3)

    compare_msg="⚡ *Node Monitoring Update* ⚡

• Pending Channels: *$pending_before* ➔ *$pending_after*
• Pending Sweeps: *$sweeps_before* ➔ *$sweeps_after*
• On-chain Balance: *$balance_before* ➔ *$balance_after* sats
"
    send_telegram "$compare_msg"

    # Atualizar status "antes" para próxima rodada
    pending_before="$pending_after"
    sweeps_before="$sweeps_after"
    balance_before="$balance_after"
done
