import configparser
import sys
import os.path
import threading
from queue import Queue

from modules.IRCBridge import IRCBot, IRCListener
from modules.DiscordBridge import DiscordBot

def run_discord(discordToken, inQueue, outQueue, ircToDiscordLinks):
    # Start Discord Bot
    discordbot = DiscordBot(inQueue, outQueue, ircToDiscordLinks)
    discordbot.run(discordToken)

def run_ircbot(channel, nickname, server, port):
    # Start IRC Bot
    ircbot = IRCBot(channel, nickname, server, port)
    ircbot.start()

def run_irclistener(channel, nickname, server, port, outQueue):
    # Start IRC Listenr
    ircbot = IRCListener(channel, nickname, server, port, outQueue)
    ircbot.start()

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
    bridge_nickname = ircConfig['BridgeNickname']
    listener_nickname = ircConfig['ListenerNickname']
    server = ircConfig['Server']
    port = int(ircConfig['Port'])

    if 'Discord' not in config:
        print("Error: Discord block missing in " + config_path)
        sys.exit(1)

    discordConfig = config['Discord']
    discordToken = discordConfig['Token']
    discordToIRCLinks = {}
    ircToDiscordLinks = {}
    for entry in config['Links']:
        discordToIRCLinks[entry] = config['Links'][entry]
        ircToDiscordLinks[config['Links'][entry]] = entry

    discordToIRCQueue = Queue()
    ircToDiscordQueue = Queue()
    discordbot_thread = threading.Thread(target=run_discord, args=[discordToken, ircToDiscordQueue, discordToIRCQueue, ircToDiscordLinks], daemon=True)
    discordbot_thread.start()

    ircbot_thread = threading.Thread(target=run_ircbot, args=[channel, bridge_nickname, server, port], daemon=True)
    ircbot_thread.start()

    irclistener_thread = threading.Thread(target=run_irclistener, args=[channel, listener_nickname, server, port, ircToDiscordQueue], daemon=True)
    irclistener_thread.start()

    threads = [discordbot_thread, ircbot_thread, irclistener_thread]
    for t in threads:
        t.join()

if __name__ == "__main__":
    main()
