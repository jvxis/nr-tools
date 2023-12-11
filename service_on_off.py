#!/usr/bin/env python3
import telebot
import subprocess

#replace with your bot token
TELEGRAM_TOKEN = "BOT_TOKEN"
#replace with your path to app
SCRIPT_PATH = "/path_to_umbrel/scripts/app"

bot = telebot.TeleBot(TELEGRAM_TOKEN)
print("Umbrel Service on-off started")

@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(message.chat.id, 'Bot is running. Send /on to turn on the service or /off to turn it off.')

@bot.message_handler(commands=['on'])
def turn_on(message):
    chat_id = message.chat.id
    command = message.text.split(' ', 1)
    
    if len(command) == 2:
        service_name = command[1]
        bot.send_message(chat_id, f'Turning on {service_name}...')
        try:
            subprocess.run([SCRIPT_PATH, 'start', service_name], check=True)
            bot.send_message(chat_id, f'🆙 Service {service_name} has been turned on.')
        except subprocess.CalledProcessError:
            bot.send_message(chat_id, f'❌ Failed to turn on {service_name}.')
    else:
        bot.send_message(chat_id, 'Usage: /on <SERVICE_NAME>')

@bot.message_handler(commands=['off'])
def turn_off(message):
    chat_id = message.chat.id
    command = message.text.split(' ', 1)
    
    if len(command) == 2:
        service_name = command[1]
        bot.send_message(chat_id, f'Turning off {service_name}...')
        try:
            subprocess.run([SCRIPT_PATH, 'stop', service_name], check=True)
            bot.send_message(chat_id, f'⛔ Service {service_name} has been turned off.')
        except subprocess.CalledProcessError:
            bot.send_message(chat_id, f'❌ Failed to turn off {service_name}.')
    else:
        bot.send_message(chat_id, 'Usage: /off <SERVICE_NAME>')

if __name__ == '__main__':
    bot.polling(none_stop=True)
