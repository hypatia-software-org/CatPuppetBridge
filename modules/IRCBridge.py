import irc.bot
import irc.client
import ssl
import irc.strings
from irc.client import ip_numstr_to_quad, ip_quad_to_numstr
from irc.connection import Factory
import socket
import sys
import threading


class IRCPuppet(irc.client.SimpleIRCClient):
    inQueue = None
    channels = None
    client_name = None
    webirc_hostname = None
    webirc_ip = None
    webirc_password = None
    nickname = None
    server = None
    port = None
    connection = None

    def __init__(self, channels, nickname, server, port, inQueue, discordToIRCLinks, webirc_password, webirc_ip):
        super().__init__()
        ssl_factory = Factory(wrapper=ssl.wrap_socket)
        self.reactor = irc.client.Reactor()
        # TODO: ircname
#        self.connection = self.reactor.server().connect(
#           server, port, nickname, connect_factory=ssl_factory
#        )
        # TODO: ircname

        self.inQueue = inQueue
        self.channels = channels
        self.discordToIRCLinks = discordToIRCLinks

        self.nickname = nickname
        self.server = server
        self.port = port
        self.webirc_ip = webirc_ip
        self.webirc_hostname = 'discord.bridge'
        self.client_name = nickname
        self.webirc_password = webirc_password

        ssl_factory = Factory(wrapper=ssl.wrap_socket)
        self.connection = self.reactor.server().connect(self.server, self.port, self.nickname,
                                                        connect_factory=ssl_factory)
        self.connection.send_raw(
                f"WEBIRC {self.webirc_password} {self.webirc_hostname} {self.webirc_hostname} {self.webirc_ip}"
            )

        self.connection.add_global_handler("welcome", self.on_welcome)

    def process_discord_queue(self):
        if not self.inQueue.empty():
            msg = self.inQueue.get()
            print(msg)
            if msg['command'] == 'send':
                print("Found send, sending...")
                if str(msg['channel']) in self.discordToIRCLinks.keys():
                    self.connection.privmsg(self.discordToIRCLinks[str(msg['channel'])], msg['data'])
            elif msg['command'] == 'afk':
                self.afk()
            elif msg['command'] == 'unafk':
                self.unafk()
            elif msg['command'] == 'die':
                print('IRC Puppet dying, ' + self.nickname)
                self.die('has left discord')
            else:
                print("ERROR: Queue command '" + msg['command'] + "' not found!")

    def on_welcome(self, c, e):
        for channel in self.channels:
            print(f"Puppet Joining {channel}...")
            c.join(self.discordToIRCLinks[str(channel)])
        self.reactor.scheduler.execute_every(1, self.process_discord_queue)
        #self.queue_thread = threading.Thread(target=self.process_discord_queue, daemon=True)
        #self.queue_thread.start()
        c.mode(c.get_nickname(), "+R")

    def start(self):
        print("Starting IRC puppet loop...")
        self.reactor.process_forever()

    def afk(self):
        self.connection.send_raw(
            f"AWAY User is away on discord"
        )

    def unafk(self):
        self.connection.send_raw(
            f"AWAY"
        )

    def die(self, msg):
        self.connection.disconnect(msg)
        sys.exit(0)

class IRCListener(irc.client.SimpleIRCClient):
    out_queue = None
    config = None

    def __init__(self, channel, nickname, server, port, out_queue, config):
        ssl_factory = Factory(wrapper=ssl.wrap_socket)
        self.reactor = irc.client.Reactor()
        # TODO: ircname
        self.connection = self.reactor.server().connect(
            server, port, nickname, connect_factory=ssl_factory
        )
        self.out_queue = out_queue
        self.channel = channel
        self.connection.add_global_handler("welcome", self.on_welcome)
        self.connection.add_global_handler("pubmsg", self.on_pubmsg)
        self.config = config

    def on_welcome(self, c, e):
        print(f"Listener Connected! Joining {self.channel}...")
        c.join(self.channel)

    def on_pubmsg(self, c, event):
        nickname = event.source.split('!', 1)[0]
        if not nickname.endswith(self.config['puppet_suffix']):
            data = {
                'author': nickname,
                'channel': event.target,
                'content': event.arguments[0]
            }
            self.out_queue.put(data)

    def start(self):
        print("Starting IRC client loop...")
        self.reactor.process_forever()

class IRCBot(irc.bot.SingleServerIRCBot):

    def __init__(self, channel, nickname, server, port):
        ssl_factory = Factory(wrapper=ssl.wrap_socket)
        irc.bot.SingleServerIRCBot.__init__(self, [(server, port)], nickname, nickname, connect_factory=ssl_factory)
        self.channel = channel

    def on_nicknameinuse(self, c, e):
        c.nick(c.get_nickname() + "_")

    def on_welcome(self, c, e):
        print(f"Bot Connected! Joining {self.channel}...")
        c.join(self.channel)

    def on_privmsg(self, c, e):
        self.do_command(e, e.arguments[0])

    def on_pubmsg(self, c, e):
        a = e.arguments[0].split(":", 1)
        if len(a) > 1 and irc.strings.lower(a[0]) == irc.strings.lower(
            self.connection.get_nickname()
        ):
            self.do_command(e, a[1].strip())
        return

    def on_dccmsg(self, c, e):
        # non-chat DCC messages are raw bytes; decode as text
        text = e.arguments[0].decode('utf-8')
        c.privmsg("You said: " + text)

    def on_dccchat(self, c, e):
        if len(e.arguments) != 2:
            return
        args = e.arguments[1].split()
        if len(args) == 4:
            try:
                address = ip_numstr_to_quad(args[2])
                port = int(args[3])
            except ValueError:
                return
            self.dcc_connect(address, port)

    def do_command(self, e, cmd):
        nick = e.source.nick
        c = self.connection

        if cmd == "disconnect":
            self.disconnect()
        elif cmd == "die":
            self.die()
        elif cmd == "stats":
            for chname, chobj in self.channels.items():
                c.notice(nick, "--- Channel statistics ---")
                c.notice(nick, "Channel: " + chname)
                users = sorted(chobj.users())
                c.notice(nick, "Users: " + ", ".join(users))
                opers = sorted(chobj.opers())
                c.notice(nick, "Opers: " + ", ".join(opers))
                voiced = sorted(chobj.voiced())
                c.notice(nick, "Voiced: " + ", ".join(voiced))
        elif cmd == "dcc":
            dcc = self.dcc_listen()
            c.ctcp(
                "DCC",
                nick,
                f"CHAT chat {ip_quad_to_numstr(dcc.localaddress)} {dcc.localport}",
            )
        else:
            c.notice(nick, "Not understood: " + cmd)
