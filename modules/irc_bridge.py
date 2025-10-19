"""Threads for IRC Bot, Puppet, and Listener"""


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


# pylint: disable=too-many-instance-attributes
class IRCPuppet(irc.client.SimpleIRCClient):
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
        if config['tls'] == "yes":
            ssl_factory = Factory(wrapper=ssl.wrap_socket)
            self.connection = self.reactor.server().connect(
                self.config['server'], self.config['port'], self.config['nickname'],
                connect_factory=ssl_factory)
        else:
            self.connection = self.reactor.server().connect(
                self.config['server'], self.config['port'], self.config['nickname'])
        self.connection.send_raw(
                f"WEBIRC {self.config['webirc_password']} {self.config['webirc_hostname']}"
                f" {self.config['webirc_hostname']} {self.config['webirc_ip']}"
            )

        self.connection.add_global_handler("welcome", self.on_welcome)
        self.connection.add_global_handler("on_privmsg", self.on_privmsg)

    def on_privmsg(self, c, event):
        """Process DMs and pass to discord user"""
        logging.debug("conext %s", c)
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
                logging.info("Found send, sending from puppet %s", self.config['nickname'])
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
                logging.error("ERROR: Queue command '%s' not found!", msg['command'])

    def join_part(self, channels):
        """Manage part and join commands from discord"""
        for channel in channels:
            if channel not in self.channels:
                logging.info("Puppet Joining %s", self.discord_to_irc_links[str(channel)])
                self.connection.join(self.discord_to_irc_links[str(channel)])
        for channel in self.channels:
            if channel not in channels:
                logging.info("Puppet Parting %s", self.discord_to_irc_links[str(channel)])
                self.connection.part(self.discord_to_irc_links[str(channel)])
        self.channels = channels

    def on_welcome(self, c, e):
        """On IRCd welcome, join channels and start worker thread"""
        logging.debug("event %s", e)

        for channel in self.channels:
            logging.info("Puppet Joining %s", self.discord_to_irc_links[str(channel)])
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
        logging.debug("event %s", e)
        c.nick(c.get_nickname() + "_")
        self.config['nickname'] = c.get_nickname()

    def start(self):
        """Start the IRC Puppet loop"""
        logging.info("Starting IRC puppet loop for puppet %s", self.config['nickname'])
        while not self.end_thread:
            self.reactor.process_once(timeout=0.2)
        logging.info('IRC Puppet killing main thread, %s', self.config['nickname'])
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
        logging.info('IRC Puppet dying, %s', self.config['nickname'])
        self.connection.disconnect(msg)
        sys.exit(0)

class IRCListener(irc.client.SimpleIRCClient):
    """Listener for irc to discord traffic"""
    out_queue = None
    config = None
    channels = None

    def __init__(self, out_queue, config):
        super().__init__()
        self.reactor = irc.client.Reactor()
        # TODO: ircname
        if config['tls'] == "yes":
            ssl_factory = Factory(wrapper=ssl.wrap_socket)
            self.connection = self.reactor.server().connect(
                config['server'], config['port'], config['listener_nickname'],
                connect_factory=ssl_factory
            )
        else:
            self.connection = self.reactor.server().connect(
                config['server'], config['port'], config['listener_nickname']
            )
        self.out_queue = out_queue
        self.connection.add_global_handler("welcome", self.on_welcome)
        self.connection.add_global_handler("pubmsg", self.on_pubmsg)
        self.connection.add_global_handler("action", self.on_action)

        self.config = config
        self.channels = config['channels']

    def on_welcome(self, c, e):
        """On IRCd welcome, join channels"""
        for channel in self.channels:
            logging.info("Listener joining %s", channel)
            logging.debug("event %s", e)
            c.join(channel)

    def on_action(self, c, event):
        """Relay /me aka IRC actions"""
        logging.info("Irc action found, adding to queue")
        logging.debug("conext %s", c)
        logging.debug("event %s", event)
        nickname = event.source.split('!', 1)[0]
        data = {
            'author': nickname,
            'channel': event.target,
            'content': '*' + event.arguments[0] + '*'
        }
        self.out_queue.put(data)

    def on_pubmsg(self, c, event):
        """On public messages, relay to discord"""
        logging.debug("c %s", c)
        nickname = event.source.split('!', 1)[0]
        if not nickname.endswith(self.config['puppet_suffix']):
            logging.info("Irc message found, adding to queue")
            data = {
                'author': nickname,
                'channel': event.target,
                'content': event.arguments[0]
            }
            self.out_queue.put(data)

    def start(self):
        """Start the irc loop, forever"""
        logging.info("Starting IRC client loop...")
        self.reactor.process_forever()

class IRCBot(irc.bot.SingleServerIRCBot):
    """Generic bot for running admin commands on the bridge from IRC"""
    def __init__(self, config):
        if config['tls'] == "yes":
            ssl_factory = Factory(wrapper=ssl.wrap_socket)
            irc.bot.SingleServerIRCBot.__init__(
                self, [(config['server'], config['port'])],
                config['bot_nickname'], config['bot_nickname'], connect_factory=ssl_factory)
        else:
            irc.bot.SingleServerIRCBot.__init__(
                self, [(config['server'], config['port'])], config['bot_nickname'],
                config['bot_nickname'])
        self.channel = config['bot_channel']

    def on_nicknameinuse(self, c, e):
        """Run if nickname is already in use"""
        logging.debug("event %s", e)
        c.nick(c.get_nickname() + "_")

    def on_welcome(self, c, e):
        """On welcome join channel"""
        logging.debug("event %s", e)
        c.join(self.channel)

    def on_privmsg(self, c, e):
        """Check private messages for commands"""
        logging.debug("conext %s", c)
        logging.debug("event %s", e)
        self.do_command(e, e.arguments[0])

    def on_pubmsg(self, c, e):
        """Check public messages for commands"""
        logging.debug("conext %s", c)
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
            for chname, chobj in self.channels.items():
                c.notice(nick, "--- Channel statistics ---")
                c.notice(nick, "Channel: " + chname)
                users = sorted(chobj.users())
                c.notice(nick, "Users: " + ", ".join(users))
                opers = sorted(chobj.opers())
                c.notice(nick, "Opers: " + ", ".join(opers))
                voiced = sorted(chobj.voiced())
                c.notice(nick, "Voiced: " + ", ".join(voiced))
        else:
            c.notice(nick, "Not understood: " + cmd)
