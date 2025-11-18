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

Threads for IRC Bot, Puppet, and Listener
"""


import sys
import threading
import logging
import time
import re
import os
import ssl
from datetime import timedelta
import asyncio

import psutil
import irc.bot
import irc.client_aio
import irc.strings
from irc.connection import Factory

class BotTemplate(irc.client_aio.AioSimpleIRCClient):
    """ Shared IRC Bot functionality """
    log = None
    ready = False

    def __init__(self):
        super().__init__()

        if 'tls' in self.config:
            if self.config['tls'] == 'yes':
                self.config['tls'] = True
            else:
                self.config['tls'] = False

        self.log = logging.getLogger(self.__class__.__name__)

    async def on_disconnect(self, c, e):
        """ When disconnected, try to reconnect """
        self.log.debug("event %s context %s", e, c)
        await self.connect(self.reconnect_data['server'], self.reconnect_data['port'],
                               self.reconnect_data['nickname'], self.reconnect_data['tls'])

# pylint: disable=too-many-instance-attributes
class IRCPuppet(BotTemplate):
    """Main thread for the IRC Puppets"""
    queues = None
    channels = None
    config = {}
    connection = None
    end_thread = False
    queue_thread = None
    discord_id = None

    def __init__(self, queues, discord_to_irc_links, puppet_config,
                 config):
        self.config = dict(config)
        super().__init__()
        print("PUPPET CREATED")
        # TODO: ircname
        self.discord_id = puppet_config['discord_id']
        self.queues = queues
        self.channels = puppet_config['channels']
        self.discord_to_irc_links = discord_to_irc_links

        self.config.update(puppet_config)
        self.config['webirc_hostname'] = 'discord.bridge'
        self.end_thread = False

    async def start(self):
        print("CONNECT AND RETRY RUN")
        await self.connect(self.config['server'], self.config['port'], self.config['nickname'],
                               self.config['tls'])

        await self.connection.send_raw(
                f"WEBIRC {self.config['webirc_password']} {self.config['webirc_hostname']}"
                f" {self.config['webirc_hostname']} {self.config['webirc_ip']}"
            )

        self.connection.add_global_handler("welcome", self.on_welcome)
        self.connection.add_global_handler("privmsg", self.on_privmsg)
        self.connection.add_global_handler("all_raw_messages", self.on_raw)
        asyncio.create_task(self.process_forever())

    def on_raw(self, c, event):
        """ Process special messages such has 401/NOSUCHNICK """
        self.log.debug(event)
        self.log.debug(c)
        data = event.arguments[0]
        split_data = data.split()
        if len(split_data) >= 4:
            if split_data[1] == "401":
                user = split_data[3][1:]
                data = {
                    'author': 'NOSUCHNICK',
                    'channel': self.config['nickname'],
                    'content': "ERROR: User '" + user + "' not found, no such nick exists on irc!",
                    'error': True
                }
                self.queues['out_queue'].put(data)

    def on_privmsg(self, c, event):
        """Process DMs and pass to discord user"""
        self.log.debug("conext %s", c)
        self.log.debug("privmsg, attempting to process")
        nickname = event.source.split('!', 1)[0]
        data = {
            'author': nickname,
            'channel': self.discord_id,
            'content': event.arguments[0],
            'error': False
        }
        self.queues['out_queue'].put(data)

    def do_send(self, msg):
        """ Handle sending messages from discord """
        if msg['data'] is None:
            return
        self.log.debug("Found send, sending from puppet %s", self.config['nickname'])
        messages = self.split_irc_message(msg)
        for message in messages:
            if str(msg['channel']) in self.discord_to_irc_links.keys():
                self.connection.privmsg(
                    self.discord_to_irc_links[str(msg['channel'])], message)

    async def process_discord_queue(self):
        """Main worker thread for handling commands form discord"""
        sentinel = object()
        while True:
            msg = await self.queues['in_queue'].get()
            while not self.ready:
                await asyncio.sleep(0.1)

            self.log.debug("Processing command %s", msg)
            match msg['command']:
                case 'send':
                    self.do_send(msg)
                case 'afk':
                    self.afk()
                case 'unafk':
                    self.unafk()
                case 'nick':
                    self.config['nickname'] = msg['irc_nick']
                    self.connection.nick(msg['irc_nick'])
                case 'join_part':
                    self.join_part(msg['data'])
                case 'send_dm':
                    messages = self.split_irc_message(msg)
                    for message in messages:
                        self.connection.privmsg(msg['channel'], message)
                case 'die':
                    self.end_thread = True
                    self.die('has left discord')
                case _:
                    self.log.error("ERROR: Queue command '%s' not found!", msg['command'])

    def join_part(self, channels):
        """Manage part and join commands from discord"""
        for channel in channels:
            if channel not in self.channels:
                self.log.debug("Puppet Joining %s", self.discord_to_irc_links[str(channel)])
                self.connection.join(self.discord_to_irc_links[str(channel)])
        for channel in self.channels:
            if channel not in channels:
                self.log.debug("Puppet Parting %s", self.discord_to_irc_links[str(channel)])
                self.connection.part(self.discord_to_irc_links[str(channel)])
        self.channels = channels

    def on_welcome(self, c, e):
        """On IRCd welcome, join channels and start worker thread"""
        self.log.debug("event %s", e)

        for channel in self.channels:
            self.log.debug("Puppet Joining %s", self.discord_to_irc_links[str(channel)])
            c.join(self.discord_to_irc_links[str(channel)])
        asyncio.create_task(self.process_discord_queue())
        c.mode(c.get_nickname(), "+R")
        self.ready = True

    def msg_reserved_bytes(self, target):
        """Calculate the amount of bytes reserved for IRC protocol"""
        msg = f":<{self.config['nickname']}>!<{self.config['nickname']}>"\
            f"@<{self.config['webirc_hostname']}> PRIVMSG <{target}> :"
        size = len(msg.encode("utf8"))
        return size + 4 # + CRLF

    def split_irc_message(self, msg):
        """
        Splits a message into IRC-safe chunks.
        """
        max_bytes = 512 - self.msg_reserved_bytes(msg['channel'])
        lines = []
        count = 0
        message = msg['data']
        #TODO: split into multiple messages maybe?
        message = re.sub(r'[\r\n]+', '', message)
        while len(message[:max_bytes]) != 0:
            count = count +1
            chunk = message[:max_bytes]

            # Don't split in the middle of a word if possible
            if len(chunk) + 1 < len(message):
                if not (message[len(chunk)] == ' ' or message[len(chunk)-1] == ' '):
                    chunk = chunk.rsplit(" ", 1)[0]

            lines.append(chunk)
            message = message[len(chunk):].lstrip()
        return lines

    def on_nicknameinuse(self, c, e):
        """Run if neckname is already in use"""
        self.log.debug("event %s", e)
        c.nick(c.get_nickname() + "_")
        self.config['nickname'] = c.get_nickname()

    def afk(self):
        """Mark nickname as afk"""
        self.connection.send_raw(
            "AWAY User is away on discord"
        )

    def unafk(self):
        """Remove AFK marking"""
        self.connection.send_raw(
            "AWAY"
        )

    def die(self, msg):
        """Kill ourself"""
        self.log.debug('IRC Puppet dying, %s', self.config['nickname'])
        self.connection.disconnect(msg)
        sys.exit(0)

class IRCListener(BotTemplate):
    """Listener for irc to discord traffic"""
    out_queue = None
    config = None
    channels = None

    def __init__(self, out_queue, config, data):
        self.config = config
        super().__init__()
        self.data = data
        # TODO: ircname

        self.out_queue = out_queue
        self.channels = config['channels']

    async def start(self):
        await self.connect(self.config['server'], self.config['port'],
                               self.config['listener_nickname'],
                               self.config['tls'])
        self.connection.add_global_handler("welcome", self.on_welcome)
        self.connection.add_global_handler("pubmsg", self.on_pubmsg)
        self.connection.add_global_handler("action", self.on_action)

        asyncio.create_task(self.process_forever())

    def on_welcome(self, c, e):
        print("Conn object:", id(self.connection))
        print("Connection object (event):", id(c))
        print("Connection object (self):", id(self.connection))

        """On IRCd welcome, join channels"""
        for channel in self.channels:
            self.log.debug("Listener joining %s", channel)
            self.log.debug("event %s", e)
            c.join(channel)

    def on_action(self, c, event):
        """Relay /me aka IRC actions"""
        self.log.debug("Irc action found, adding to queue")
        self.log.debug("conext %s", c)
        self.log.debug("event %s", event)
        nickname = event.source.split('!', 1)[0]
        data = {
            'author': nickname,
            'channel': event.target,
            'content': '*' + event.arguments[0] + '*'
        }
        self.out_queue.put(data)

    def on_pubmsg(self, c, event):
        """On public messages, relay to discord"""
        self.log.debug("c %s", c)
        print('i ran')
        nickname = event.source.split('!', 1)[0]
        if not nickname.endswith(self.config['puppet_suffix']):
            self.log.debug("Irc message found, adding to queue")
            data = {
                'author': nickname,
                'channel': event.target,
                'content': event.arguments[0]
            }
            self.out_queue.put(data)
            self.data.increment('irc_messages')

class IRCBot(BotTemplate):
    """Generic bot for running admin commands on the bridge from IRC"""

    channels = None
    stats_data = None
    config = None

    def __init__(self, config, data):
        self.config = config
        super().__init__()
        self.channel = config['bot_channel']
        self.stats_data = data

    async def start(self):
        await self.connect(self.config['server'], self.config['port'], self.config['bot_nickname'],
                               self.config['tls'])
        self.connection.add_global_handler("welcome", self.on_welcome)
        self.connection.add_global_handler("pubmsg", self.on_pubmsg)
        self.connection.add_global_handler("privmsg", self.on_privmsg)

        asyncio.create_task(self.process_forever())

    def on_nicknameinuse(self, c, e):
        """Run if nickname is already in use"""
        self.log.debug("event %s", e)
        c.nick(c.get_nickname() + "_")

    def on_welcome(self, c, e):
        """On welcome join channel"""
        self.log.debug("event %s", e)
        c.join(self.channel)

    def on_privmsg(self, c, e):
        """Check private messages for commands"""
        self.log.debug("conext %s", c)
        self.log.debug("event %s", e)
        self.do_command(e, e.arguments[0])

    def on_pubmsg(self, c, e):
        """Check public messages for commands"""
        self.log.debug("conext %s", c)
        a = e.arguments[0].split(":", 1)
        if len(a) > 1 and irc.strings.lower(a[0]) == irc.strings.lower(
            self.connection.get_nickname()
        ):
            self.do_command(e, a[1].strip())

    def format_uptime(self, start_time):
        """ Create a human readable different in time, from unix time """
        elapsed = time.time() - start_time
        return str(timedelta(seconds=int(elapsed)))

    def do_command(self, e, cmd):
        """Process commands"""
        nick = e.source.nick
        c = self.connection

        if cmd == "stats":
            data = self.stats_data.snapshot()
            total_puppets = 0
            if 'total_puppets' in data:
                total_puppets = data['total_puppets']
            discord_messages = 0
            if 'discord_messages' in data:
                discord_messages = data['discord_messages']
            irc_messages = 0
            if 'irc_messages' in data:
                irc_messages = data['irc_messages']
            p = psutil.Process(os.getpid())
            rss = p.memory_info().rss / 1024**2
            uptime = self.format_uptime(data['uptime'])
            num_threads = psutil.Process().num_threads()

            c.privmsg(nick, "Puppets total: " + str(total_puppets))
            c.privmsg(nick, "Relayed messages from Discord: " + str(discord_messages))
            c.privmsg(nick, "Relayed messages from IRC: " + str(irc_messages))
            c.privmsg(nick, f"Memory usage (rss): {rss:.2f}mb".format(rss))
            c.privmsg(nick, "Threads: " + str(num_threads))
            c.privmsg(nick, "Uptime: " + uptime)
        else:
            c.privmsg(nick, "Not understood: " + cmd)
