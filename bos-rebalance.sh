
      if [ $attempts -ge $max_attempts ]; then
        echo "Reached $max_attempts failed attempts. Please enter a new maximum fee rate:"
        read -p "Enter the new maximum fee rate: " max_fee_rate
        attempts=0
      fi
    else
      attempts=0
      current_amount=$((current_amount + step))
    fi
  done

  echo "Successfully rebalanced $amount sats."
}

# Ask user for input values
read -p "Enter the total amount to rebalance (in sats): " total_amount
read -p "Enter the incoming peer ID: " incoming_peer
read -p "Enter the outgoing peer ID: " outgoing_peer
read -p "Enter the maximum fee rate: " max_fee_rate
read -p "Enter the maximum number of attempts before changing the fee rate: " max_attempts
read -p "Enter the size of each rebalance attempt (in sats): " step_size

# Call the function to rebalance the channel
rebalance_channel $total_amount $incoming_peer $outgoing_peer $max_fee_rate $max_attempts $step_size
