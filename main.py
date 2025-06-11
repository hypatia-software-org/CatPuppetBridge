""" Main loop for Cat Puppet Bridge """

import configparser
import sys
import os.path
import threading
import logging
from queue import Queue

from modules.IRCBridge import IRCBot, IRCListener, IRCPuppet
from modules.DiscordBridge import DiscordBot
from modules.address_generator import ula_address_from_string

def run_discord(discord_token, queues, irc_to_discord_links, listener_config):
    """Start the discord thread and login to the Discord API"""
    # Start Discord Bot
    discordbot = DiscordBot(queues, irc_to_discord_links, listener_config)
    discordbot.run(discord_token)

def run_ircbot(config):
    """Start the IRCBOT thread"""
    # Start IRC Bot
    ircbot = IRCBot(config)
    ircbot.start()

def run_irclistener(out_queue, config):
    """Start the IRC Listener thread"""
    # Start IRC Listenr
    ircbot = IRCListener(out_queue, config)
    ircbot.start()

def run_ircpuppet(in_queue, discord_to_irc_links, webirc_ip, puppet_config,
                  config):
    """Start a IRC Puppet thread"""
    # Start IRC Puppet
    ircbot = IRCPuppet(in_queue, discord_to_irc_links,
                       webirc_ip, puppet_config, config)
    ircbot.start()

def init_config(config_filename='catbridge.ini'):
    """Init our configs, make sure config file can be found"""
    if os.path.isfile(config_filename):
        config_path = os.getcwd() + '/' + config_filename
    elif os.path.isfile('/etc/' + config_filename):
        config_path = '/etc/' + config_filename
    else:
        logging.error("Error: catbridge.ini missing.")
        sys.exit(1)

    config = configparser.ConfigParser()
    try:
        config.read(config_path)
    except configparser.ParsingError as e:
        raise e

    return config, config_path

def check_required(required: list, config: dict, block: str):
    """Ensure required fields exist"""
    for req in required:
        if req not in config:
            logging.error("Error: Required config in %s block %s is missing", block, required)
            sys.exit(1)

def read_config(irc_required: list, discord_required: list, config, config_path: str):
    """Read the config file"""
    if 'IRC' not in config:
        logging.error("Error: IRC block missing in %s", config_path)
        sys.exit(1)

    irc_config = config['IRC']
    check_required(irc_required, irc_config, 'IRC')

    if 'Discord' not in config:
        logging.error("Error: Discord block missing in %s", config_path)
        sys.exit(1)

    discord_config = config['Discord']
    check_required(discord_required, discord_config, 'Discord')

    if 'Links' not in config:
        logging.error("Error: Discord block missing in %s", config_path)
        sys.exit(1)

    channels_to_join = []
    discord_to_irc_links = {}
    irc_to_discord_links = {}

    for entry in config['Links']:
        channels_to_join.append(config['Links'][entry])
        discord_to_irc_links[entry] = config['Links'][entry]
        irc_to_discord_links[config['Links'][entry]] = entry


    return {'irc_config': irc_config,
            'discord_config': discord_config,
            'irc_to_discord_links': irc_to_discord_links,
            'discord_to_irc_links': discord_to_irc_links,
            'channels_to_join': channels_to_join}

def main():
    """Main loop for Cat Puppet Bridge"""

    # Init logging
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(module)s %(message)s",
        level=logging.INFO)

    # Init config
    config, config_path = init_config()

    configs = read_config(['server',
                           'BotChannel',
                           'TLS',
                           'Port',
                           'BridgeNickName',
                           'ListenerNickname',
                           'PuppetSuffix',
                           'WebIRCPassword'],
                          ['ClientID',
                           'Token'],
                          config,
                          config_path)

    discord_config = {'puppet_suffix': configs['irc_config']['PuppetSuffix']}
    irc_config = {
        'puppet_suffix': configs['irc_config']['PuppetSuffix'],
        'tls': configs['irc_config']['TLS'],
        'channels': configs['channels_to_join'],
        'bot_channel': configs['irc_config']['BotChannel'],
        'bot_nickname': configs['irc_config']['BridgeNickname'],
        'listener_nickname': configs['irc_config']['ListenerNickname'],
        'server': configs['irc_config']['Server'],
        'port': int(configs['irc_config']['Port']),
        'webirc_password': configs['irc_config']['WebIRCPassword']
    }

    discord_queues = {
        'in_queue': Queue(),
        'out_queue': Queue(),
        'puppet_queue': Queue()
    }

    threads = []

    threads.append(threading.Thread(target=run_discord,
                                    args=[configs['discord_config']['Token'],
                                          discord_queues,
                                          configs['irc_to_discord_links'],
                                          discord_config],
                                    daemon=True).start())

    threads.append(threading.Thread(target=run_ircbot,
                                    args=[irc_config], daemon=True).start())

    threads.append(threading.Thread(target=run_irclistener,
                                    args=[discord_queues['irc_to_discord_queue'],
                                          irc_config], daemon=True).start())

    puppet_dict = {}
    puppet_main_queues = {}

    for user in iter(discord_queues['puppet_queue'].get, object()):
        if user['command'] == 'active':
            # Does the puppet already exist? Start it! Otherwise do nothing
            if user['id'] not in puppet_dict:
                logging.info("Starting IRC Puppet: %s", user['irc_nick'])
                puppet_main_queues[user['id']] = Queue()
                puppet_nickname = user['irc_nick'] + configs['irc_config']['PuppetSuffix']
                puppet_config = {
                    'channels': user['data'],
                    'nickname': puppet_nickname
                    }
                ircpuppet_thread = threading.Thread(
                    target=run_ircpuppet,
                    args=[puppet_main_queues[user['id']], configs['discord_to_irc_links'],
                          ula_address_from_string(puppet_nickname),
                          puppet_config, irc_config],
                    daemon=True)
                ircpuppet_thread.start()

                puppet_dict[user['id']] = ircpuppet_thread
        if user['command'] == 'die':
            logging.info("Stopping IRC Puppet: %s", user['irc_nick'])
            puppet_main_queues[user['id']].put(user)
            puppet_dict[user['id']].join()
            del puppet_dict[user['id']]
        if user['command'] == 'send' or user['command'] == 'afk' or user['command'] == 'unafk' \
           or user['command'] == 'nick' or user['command'] == 'join_part':
            puppet_main_queues[user['id']].put(user)
    for t in threads:
        t.join()

if __name__ == "__main__":
    main()
