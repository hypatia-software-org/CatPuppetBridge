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
import ssl

import irc.bot
import irc.client
import irc.strings
from irc.connection import Factory

class BotTemplate(irc.client.SimpleIRCClient):
    """ Shared IRC Bot functionality """
    log = None
    reconnect_data = None
    def __init__(self):
        super().__init__()
        self.log = logging.getLogger(self.__class__.__name__)

    def connect_and_retry(self, server: str, port: int, nickname: str, tls: bool = False):
        """ Manage connection and retry rate """
        retry_count = 1
        self.reconnect_data = {'server': server, 'port': port, 'nickname': nickname, 'tls': tls}
        while True:
            if tls == "yes":
                context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                context.minimum_version = ssl.TLSVersion.TLSv1_2
                ssl_factory = Factory(
                    wrapper=lambda sock: context.wrap_socket(sock,server_hostname=server))

                try:
                    self.connection = self.reactor.server().connect(
                        server, port, nickname,
                        connect_factory=ssl_factory)
                    self.log.info('connected with TLS sucessfully to %s:%i',
                                 server, port)
                    self.log.debug('connected sucessfully to %s:%i as %s',
                                  server, port, nickname)
                    break
                except (irc.client.ServerConnectionError, TimeoutError):
                    delay = min(10 * retry_count, 300)
                    self.log.warning('connection failed %i times on %s:%i, retrying in %i',
                                 retry_count, server, port, delay)
                    retry_count = retry_count + 1
                    time.sleep(delay)
            else:
                try:
                    self.connection = self.reactor.server().connect(
                        server, port, nickname)
                    self.log.info('connected sucessfully to %s:%i',
                                 server, port)
                    self.log.debug('connected sucessfully to %s:%i as %s',
                                  server, port, nickname)
                    break
                except (irc.client.ServerConnectionError, TimeoutError):
                    delay = min(10 * retry_count, 300)
                    self.log.warning('connection failed %i times on %s:%i, retrying in %i',
                                 retry_count, server, port, delay)
                    retry_count = retry_count + 1
                    time.sleep(delay)

        self.connection.add_global_handler("disconnect", self.on_disconnect)

    def on_disconnect(self, c, e):
        """ When disconnected, try to reconnect """
        self.log.debug("event %s context %s", e, c)
        self.connect_and_retry(self.reconnect_data['server'], self.reconnect_data['port'],
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
    ready = False

    def __init__(self, queues, discord_to_irc_links, puppet_config,
                 config):
        super().__init__()
        self.reactor = irc.client.Reactor()

        # TODO: ircname
        self.queues = queues
        self.channels = puppet_config['channels']
        self.discord_to_irc_links = discord_to_irc_links

        self.config = config
        self.config.update(puppet_config)
        self.config['webirc_hostname'] = 'discord.bridge'
        self.end_thread = False

        self.connect_and_retry(self.config['server'], self.config['port'], self.config['nickname'],
                               self.config['tls'])

        self.connection.send_raw(
                f"WEBIRC {self.config['webirc_password']} {self.config['webirc_hostname']}"
                f" {self.config['webirc_hostname']} {self.config['webirc_ip']}"
            )

        self.connection.add_global_handler("welcome", self.on_welcome)
        self.connection.add_global_handler("on_privmsg", self.on_privmsg)

    def on_privmsg(self, c, event):
        """Process DMs and pass to discord user"""
        self.log.debug("conext %s", c)
        nickname = event.source.split('!', 1)[0]
        data = {
            'author': nickname,
            'channel': self.config['nickname'],
            'content': event.arguments[0]
        }
        self.queues['out_queue'].put(data)

    def process_discord_queue(self):
        """Main worker thread for handling commands form discord"""
        while not self.ready:
            time.sleep(1)
        sentinel = object()
        for msg in iter(self.queues['in_queue'].get, sentinel):
            if msg['command'] == 'send':
                if msg['data'] is None:
                    continue
                self.log.debug("Found send, sending from puppet %s", self.config['nickname'])
                messages = self.split_irc_message(msg)
                for message in messages:
                    if str(msg['channel']) in self.discord_to_irc_links.keys():
                        self.connection.privmsg(
                            self.discord_to_irc_links[str(msg['channel'])], message)
            elif msg['command'] == 'afk':
                self.afk()
            elif msg['command'] == 'unafk':
                self.unafk()
            elif msg['command'] == 'nick':
                self.config['nickname'] = msg['irc_nick']
                self.connection.nick(msg['irc_nick'])
            elif msg['command'] == 'join_part':
                self.join_part(msg['data'])
            elif msg['command'] == 'die':
                self.end_thread = True
                self.die('has left discord')
            else:
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
        #self.reactor.scheduler.execute_every(1, self.process_discord_queue)
        self.queue_thread = threading.Thread(target=self.process_discord_queue, daemon=True)
        self.queue_thread.start()
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

    def start(self):
        """Start the IRC Puppet loop"""
        self.log.debug("Starting IRC puppet loop for puppet %s", self.config['nickname'])
        while not self.end_thread:
            self.reactor.process_once(timeout=0.2)
        self.log.debug('IRC Puppet killing main thread, %s', self.config['nickname'])
        sys.exit(0)
        #self.reactor.process_forever()

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

    def __init__(self, out_queue, config):
        super().__init__()
        self.reactor = irc.client.Reactor()
        self.config = config
        # TODO: ircname
        self.connect_and_retry(self.config['server'], self.config['port'],
                               self.config['listener_nickname'],
                               self.config['tls'])

        self.out_queue = out_queue
        self.connection.add_global_handler("welcome", self.on_welcome)
        self.connection.add_global_handler("pubmsg", self.on_pubmsg)
        self.connection.add_global_handler("action", self.on_action)

        self.channels = config['channels']

    def on_welcome(self, c, e):
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
        nickname = event.source.split('!', 1)[0]
        if not nickname.endswith(self.config['puppet_suffix']):
            self.log.debug("Irc message found, adding to queue")
            data = {
                'author': nickname,
                'channel': event.target,
                'content': event.arguments[0]
            }
            self.out_queue.put(data)

    def start(self):
        """Start the irc loop, forever"""
        self.log.debug("Starting IRC client loop...")
        self.reactor.process_forever()

class IRCBot(BotTemplate):
    """Generic bot for running admin commands on the bridge from IRC"""

    channels = None

    def __init__(self, config):
        super().__init__()
        self.reactor = irc.client.Reactor()
        self.connect_and_retry(config['server'], config['port'], config['bot_nickname'],
                               config['tls'])
        self.channel = config['bot_channel']

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

    def do_command(self, e, cmd):
        """Process commands"""
        nick = e.source.nick
        c = self.connection

        if cmd == "stats":
            c.notice(nick, "Stats placeholder")
        else:
            c.notice(nick, "Not understood: " + cmd)
