import configparser
import sys
import os.path
import threading

from modules.IRCBridge import IRCBot
from modules.DiscordBridge import DiscordBot

def run_discord(discordToken):
    # Start Discord Bot
    discordbot = DiscordBot()
    discordbot.run(discordToken)


def main():
    config_filename = 'catbridge.ini'
    if os.path.isfile(config_filename):
        config_path = os.getcwd() + '/' + config_filename
    elif os.path.isfile('/etc/' + config_filename):
        config_path = '/etc/' + config_filename
    else:
        print("Error: catbridge.ini missing.")
        sys.exit(1)

    config = configparser.ConfigParser()
    try:
        config.read(config_path)
    except configparser.ParsingError as e:
        raise(e)

    if 'IRC' not in config:
        print("Error: IRC block missing in " + config_path)
        sys.exit(1)

    ircConfig = config['IRC']
    channel = ircConfig['Channel']
    nickname = ircConfig['BridgeNickname']
    server = ircConfig['Server']
    port = int(ircConfig['Port'])

    if 'Discord' not in config:
        print("Error: Discord block missing in " + config_path)
        sys.exit(1)

    discordConfig = config['Discord']
    discordToken = discordConfig['Token']

    discordbot_thread = threading.Thread(target=run_discord, args=[discordToken], daemon=True)
    discordbot_thread.start()
    
    # Start IRC Bot
    ircbot = IRCBot(channel, nickname, server, port)
    ircbot.start()


if __name__ == "__main__":
    main()
