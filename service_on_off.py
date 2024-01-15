#!/usr/bin/env python3
#This is a telegram bot to start and stop Umbrel services. You can use /on name_of_service to start some services.
#Ex: /on lightning-terminal (this will execute the LIT)

#Dependencies
#You need to install the telegram library using the command: pip3 install pyTelegramBotAPI

import telebot
import subprocess

#replace with your bot token
TELEGRAM_TOKEN = "BOT_TOKEN"
TELEGRAM_USER_ID = "YOUR-TELEGRAM-USER-ID"
#replace with your path to app
SCRIPT_PATH = "/path_to_umbrel/scripts/app"
#replace with your path to other bash script
OTHER_SCRIPT_PATH = "path/to/other/script"

bot = telebot.TeleBot(TELEGRAM_TOKEN)
print("Umbrel Service on-off started")

# Function to check if the user is authorized
def is_authorized_user(user_id):
    return str(user_id) == TELEGRAM_USER_ID

# Decorator function for authorization check
def authorized_only(func):
    def wrapper(message):
        if is_authorized_user(message.from_user.id):
            func(message)
        else:
        bot.reply_to(message, "⛔️ You are not authorized to execute this command.")

    return wrapper

@bot.message_handler(commands=['start'])
@authorized_only
def start(message):
    bot.send_message(message.chat.id, 'Bot is running. Send /help for available commands.')

@bot.message_handler(commands=['help'])
@authorized_only
def help_command(message):
    help_text = (
        "Available commands:\n"
        "/start - Get started with PeerSwapBot\n"
        "/help - Display this help message\n"
        "/on - Activates a specific service. Usage: /on <service_name>\n"
        "/off - Disables a specific service. Usage: /off <service_name>\n"
        "/startscript - Runs a specific script. Usage: /startscript <script_name.sh>\n"
        "/boot - Restarts a specific service. Usage: /boot <service_name>\n"
    )
    send_formatted_output(message.chat.id, help_text)


@bot.message_handler(commands=['on'])
@authorized_only
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
@authorized_only
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
        
@bot.message_handler(commands=['boot'])
@authorized_only
def turn_off(message):
    chat_id = message.chat.id
    command = message.text.split(' ', 1)
    
    if len(command) == 2:
        service_name = command[1]
        bot.send_message(chat_id, f'Restarting {service_name}...')
        try:
            subprocess.run([SCRIPT_PATH, 'restart', service_name], check=True)
            bot.send_message(chat_id, f'🔄 Service {service_name} has been restarted.')
        except subprocess.CalledProcessError:
            bot.send_message(chat_id, f'❌ Failed to restart {service_name}.')
    else:
        bot.send_message(chat_id, 'Usage: /boot <SERVICE_NAME>')       

@bot.message_handler(commands=['startscript'])
@authorized_only
def start_script(message):
    chat_id = message.chat.id
    command = message.text.split(' ', 1)

    if len(command) == 2:
        script_name = command[1]
        bot.send_message(chat_id, f'Executing script {script_name}...')
        try:
            subprocess.run(["bash", f'{OTHER_SCRIPT_PATH}/{script_name}'], check=True)
            bot.send_message(chat_id, f'✅ Script {script_name} executed successfully.')
        except subprocess.CalledProcessError as e:
            bot.send_message(chat_id, f'❌ Failed to execute script {script_name}. Error: {e}')
    else:
        bot.send_message(chat_id, 'Usage: /startscript <script_name.sh>')


if __name__ == '__main__':
    bot.polling(none_stop=True)
