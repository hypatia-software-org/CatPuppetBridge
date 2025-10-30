#!/usr/bin/env python3
"""
This file is part of CatPuppetBridge.

CatPuppetBridge is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

CatPuppetBridge is distributed in the hope that it will be useful, but WITHOUT
ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with
CatPuppetBridge. If not, see <https://www.gnu.org/licenses/>.

Copyright (C) 2025 Lisa Marie Maginnis

Main loop for Cat Puppet Bridge
"""

import configparser
import sys
import os.path
import threading
import logging
from queue import Queue

from modules.irc_bridge import IRCBot, IRCListener, IRCPuppet
from modules.discord_bridge import DiscordBot
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

def run_ircpuppet(queues, discord_to_irc_links, puppet_config, config):
    """Start a IRC Puppet thread"""
    # Start IRC Puppet
    ircbot = IRCPuppet(queues, discord_to_irc_links, puppet_config, config)
    ircbot.start()

def init_config(config_filename='catbridge.ini'):
    """Init our configs, make sure config file can be found"""
    if os.path.isfile(config_filename):
        config_path = os.getcwd() + '/' + config_filename
    elif os.path.isfile('/etc/' + config_filename):
        config_path = '/etc/' + config_filename
    else:
        logging.error("catbridge.ini missing")
        sys.exit(1)

    config = configparser.ConfigParser()
    try:
        config.read(config_path)
    except configparser.ParsingError as e:
        raise e

    config_data = {'config': config, 'config_path': config_path}
    return config_data

def check_required(required: list, config: dict, block: str):
    """Ensure required fields exist"""
    for req in required:
        if req not in config:
            logging.error("required config in `%s` block `%s` is missing", block, req)
            sys.exit(1)

def read_config(irc_required: list, discord_required: list, config, config_path: str):
    """Read the config file"""

    logging.info("opening configuration file `%s`", config_path)

    if 'IRC' not in config:
        logging.error("IRC block missing in `%s`", config_path)
        sys.exit(1)

    irc_config = config['IRC']
    check_required(irc_required, irc_config, 'IRC')

    if 'Discord' not in config:
        logging.error("Discord block missing in %s", config_path)
        sys.exit(1)

    discord_config = config['Discord']
    check_required(discord_required, discord_config, 'Discord')

    if 'Links' not in config:
        logging.error("Links block missing in %s", config_path)
        sys.exit(1)

    channels_to_join = []
    discord_to_irc_links = {}
    irc_to_discord_links = {}

    for entry in config['Links']:
        channels_to_join.append(config['Links'][entry])
        discord_to_irc_links[entry] = config['Links'][entry]
        irc_to_discord_links[config['Links'][entry]] = entry

    global_config = {}
    if 'Global' not in config:
        logging.warning("Global block missing in %s", config_path)
    else:
        for entry in config['Global']:
            global_config[entry] = config['Global'][entry]
    if 'log_level' not in global_config:
        global_config['log_level'] = 'warn'

    return {'irc_config': irc_config,
            'discord_config': discord_config,
            'irc_to_discord_links': irc_to_discord_links,
            'discord_to_irc_links': discord_to_irc_links,
            'channels_to_join': channels_to_join,
            'global_config': global_config}

def main():
    """Main loop for Cat Puppet Bridge"""

    # Init logging
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(module)s %(message)s",
        level=logging.INFO)

    config_info = init_config()

    configs = read_config(['server',
                           'BotChannel',
                           'TLS',
                           'Port',
                           'BridgeNickName',
                           'ListenerNickname',
                           'PuppetSuffix',
                           'PuppetDisplayNameMinSize',
                           'WebIRCPassword'],
                          ['Token'],
                          config_info['config'],
                          config_info['config_path'])

    match configs['global_config']['log_level']:
        case "warn":
            log_level = logging.WARNING
        case "info":
            log_level = logging.INFO
        case "error":
            log_level = logging.ERROR
        case "debug":
            log_level = logging.DEBUG

    logging.getLogger().setLevel(log_level)

    discord_config = {'puppet_suffix': configs['irc_config']['PuppetSuffix'],
                      'puppet_min_size': int(configs['irc_config']['PuppetDisplayNameMinSize']),
                      'log_level': log_level}
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
        'irc_to_discord_queue': Queue(),
        'puppet_queue': Queue(),
        'dm_out_queue': Queue()
    }

    threads = []

    logging.info("starting discord thread")
    threads.append(threading.Thread(target=run_discord,
                                    args=[configs['discord_config']['Token'],
                                          discord_queues,
                                          configs['irc_to_discord_links'],
                                          discord_config],
                                    daemon=True).start())

    logging.info("starting IRC bot thread")
    threads.append(threading.Thread(target=run_ircbot,
                                    args=[irc_config], daemon=True).start())

    logging.info("starting IRC listener thread")
    threads.append(threading.Thread(target=run_irclistener,
                                    args=[discord_queues['irc_to_discord_queue'],
                                          irc_config], daemon=True).start())

    puppet_dict = {}
    puppet_main_queues = {}

    for user in iter(discord_queues['puppet_queue'].get, object()):
        if user['command'] == 'active':
            # Does the puppet already exist? Start it! Otherwise do nothing
            if user['id'] not in puppet_dict:
                logging.debug("Starting IRC Puppet: %s", user['irc_nick'])
                logging.info("starting IRC Puppet")
                puppet_main_queues[user['id']] = Queue()
                puppet_nickname = user['irc_nick'] + configs['irc_config']['PuppetSuffix']
                puppet_config = {
                    'channels': user['data'],
                    'nickname': puppet_nickname,
                    'webirc_ip': ula_address_from_string(puppet_nickname)
                    }
                ircpuppet_thread = threading.Thread(
                    target=run_ircpuppet,
                    args=[{
                        'in_queue': puppet_main_queues[user['id']],
                        'out_queue': discord_queues['dm_out_queue']
                        }, configs['discord_to_irc_links'],
                          puppet_config, irc_config],
                    daemon=True)
                ircpuppet_thread.start()

                puppet_dict[user['id']] = ircpuppet_thread
        if user['command'] == 'die':
            logging.debug("stopping IRC Puppet: %s", user['irc_nick'])
            logging.info("stopping IRC Puppet")
            puppet_main_queues[user['id']].put(user)
            puppet_dict[user['id']].join()
            del puppet_dict[user['id']]
        if user['command'] == 'send' or user['command'] == 'afk' or user['command'] == 'unafk' \
           or user['command'] == 'nick' or user['command'] == 'join_part':
            if user['command'] == 'nick':
                user['irc_nick'] += configs['irc_config']['PuppetSuffix']
            try:
                puppet_main_queues[user['id']].put(user)
            except KeyError as e:
                logging.error("Failed to add irc command to queue, missing %i", user['id'])
                logging.error(e)
    for t in threads:
        t.join()

if __name__ == "__main__":
    main()
