import configparser
import sys
import os.path
import threading
from queue import Queue

from modules.IRCBridge import IRCBot, IRCListener, IRCPuppet
from modules.DiscordBridge import DiscordBot
from modules.AddressGenerator import ula_address_from_string

def run_discord(discordToken, in_queue, out_queue, puppet_queue, irc_to_discord_links, guild_id):
    # Start Discord Bot
    discordbot = DiscordBot(in_queue, out_queue, puppet_queue, irc_to_discord_links, guild_id)
    discordbot.run(discordToken)

def run_ircbot(channel, nickname, server, port):
    # Start IRC Bot
    ircbot = IRCBot(channel, nickname, server, port)
    ircbot.start()

def run_irclistener(channel, nickname, server, port, out_queue, config):
    # Start IRC Listenr
    ircbot = IRCListener(channel, nickname, server, port, out_queue, config)
    ircbot.start()

def run_ircpuppet(channels, nickname, server, port, in_queue, discord_to_irc_links, webirc_password, webirc_ip):
    # Start IRC Puppet
    ircbot = IRCPuppet(channels, nickname, server, port, in_queue, discord_to_irc_links, webirc_password, webirc_ip)
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
    puppet_suffix = ircConfig['PuppetSuffix']
    webirc_password = ircConfig['WebIRCPassword']
    server = ircConfig['Server']
    port = int(ircConfig['Port'])

    if 'Discord' not in config:
        print("Error: Discord block missing in " + config_path)
        sys.exit(1)

    discordConfig = config['Discord']
    discordToken = discordConfig['Token']
    guild_id = discordConfig['GuildId']
    discord_to_irc_links = {}
    irc_to_discord_links = {}
    for entry in config['Links']:
        discord_to_irc_links[entry] = config['Links'][entry]
        irc_to_discord_links[config['Links'][entry]] = entry

    discordToIRCQueue = Queue()
    ircToDiscordQueue = Queue()
    IrcPuppetQueue = Queue()

    listener_config = {'puppet_suffix': puppet_suffix}

    discordbot_thread = threading.Thread(target=run_discord, args=[discordToken, ircToDiscordQueue, discordToIRCQueue, IrcPuppetQueue, irc_to_discord_links, guild_id], daemon=True)
    discordbot_thread.start()

    ircbot_thread = threading.Thread(target=run_ircbot, args=[channel, bridge_nickname, server, port], daemon=True)
    ircbot_thread.start()

    irclistener_thread = threading.Thread(target=run_irclistener, args=[channel, listener_nickname, server, port, ircToDiscordQueue, listener_config], daemon=True)
    irclistener_thread.start()

    threads = [discordbot_thread, ircbot_thread, irclistener_thread]

    PuppetDict = {}
    puppet_main_queues = {}

    sentinel = object()
    for user in iter(IrcPuppetQueue.get, sentinel):
        if user['command'] == 'active':
            # Does the puppet already exist? Start it! Otherwise do nothing
            if user['id'] not in PuppetDict.keys():
                print("Starting IRC Puppet: " + user['nick'])
                puppet_main_queues[user['id']] = Queue()
                puppet_nickname = user['nick'] + puppet_suffix
                ircpuppet_thread = threading.Thread(
                    target=run_ircpuppet,
                    args=[user['data'], puppet_nickname, server, port,
                          puppet_main_queues[user['id']], discord_to_irc_links,
                          webirc_password, ula_address_from_string(puppet_nickname)],
                    daemon=True)
                ircpuppet_thread.start()

                PuppetDict[user['id']] = ircpuppet_thread
        if user['command'] == 'die':
            print("Stopping IRC Puppet: " + user['nick'])
            puppet_main_queues[user['id']].put(user)
            PuppetDict[user['id']].join()
            del PuppetDict[user['id']]
        if user['command'] == 'send':
            print("Send found")
            puppet_main_queues[user['id']].put(user)
    for t in threads:
        t.join()

if __name__ == "__main__":
    main()
