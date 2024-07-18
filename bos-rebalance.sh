#!/bin/bash

# Function to rebalance with smaller amounts
rebalance_channel() {
  local amount=$1
  local in_peer=$2
  local out_peer=$3
  local max_fee_rate=$4
  local max_attempts=$5
  local step=$6

  local current_amount=0
  local attempts=0

  while [ $current_amount -lt $amount ]; do
    # Calculate remaining amount to rebalance
    local remaining_amount=$((amount - current_amount))
    
    # If remaining amount is less than step, rebalance with remaining amount
    if [ $remaining_amount -lt $step ]; then
      step=$remaining_amount
    fi

    # Run the rebalance command
    bos rebalance --amount $step --in $in_peer --out $out_peer --max-fee-rate $max_fee_rate
    
    # Check if the previous command was successful
    if [ $? -ne 0 ]; then
      attempts=$((attempts + 1))
      echo "Rebalance attempt $attempts failed."

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
