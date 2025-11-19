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
"""

import subprocess
import time
import pytest
import signal
import main
import ssl
import socket
from modules.stats_data import StatsData
from irc import client_aio
import asyncio

from modules.irc_bridge import IRCBot, IRCListener, IRCPuppet, BotTemplate
import threading

class TestClient(BotTemplate):
    def __init__(self, irc_config):
        super().__init__()
        self.server = irc_config['server']
        self.port = irc_config['port']
        self.nickname = irc_config['nickname']
        self.channel = irc_config['channels'][0]
        self.config = irc_config
        self.done = asyncio.Event()

    async def start(self):

        await self.connect_and_retry(self.config['server'], self.config['port'], self.config['nickname'],
                                     self.config['tls'])
        self.connection.add_global_handler("welcome", self.on_welcome)
        self.connection.add_global_handler("join", self.on_join)
        self.connection.add_global_handler("disconnect", self.on_disconnect)


    def on_welcome(self, connection, event):
        connection.join(self.channel)
        task = asyncio.current_task()
        task.cancel()

    def on_join(self, connection, event):
        print('QUITTING')
        connection.privmsg(self.channel, "hi")
        self.connection.disconnect()
        print('QUIT')


@pytest.fixture(scope="function")
def ssl_proxy():
    """Start a simple SSL forwarder for IRC on port 6697 -> 6667."""

    # Create SSL context
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    context.load_cert_chain(certfile="src/tests/server.crt", keyfile="src/tests/server.key")

    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind(("127.0.0.1", 6697))
    server_sock.listen(5)

    stop_event = threading.Event()

    def handle_client(client_ssl):
        """Forward data in both directions."""
        with socket.create_connection(("127.0.0.1", 6667)) as backend:
            # Two-way forwarding threads
            def forward(src, dst):
                try:
                    while not stop_event.is_set():
                        data = src.recv(4096)
                        if not data:
                            break
                        dst.sendall(data)
                except OSError:
                    pass

            t1 = threading.Thread(target=forward, args=(client_ssl, backend), daemon=True)
            t2 = threading.Thread(target=forward, args=(backend, client_ssl), daemon=True)
            t1.start()
            t2.start()
            t1.join()
            t2.join()

    def accept_loop():
        while not stop_event.is_set():
            try:
                client_sock, _ = server_sock.accept()
                client_ssl = context.wrap_socket(client_sock, server_side=True)
                threading.Thread(target=handle_client, args=(client_ssl,), daemon=True).start()
            except OSError:
                break

    thread = threading.Thread(target=accept_loop, daemon=True)
    thread.start()

    # Yield the proxy info
    yield {"port": 6697}

    # Teardown
    stop_event.set()
    try:
        server_sock.close()
    except Exception:
        pass
    
@pytest.fixture(scope="session", autouse=True)
def irc_server():
    """Start python -m irc.server in the background before tests."""
    # Start the server process
    proc = subprocess.Popen(
        ["python", "-m", "irc.server"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    import re

    for line in proc.stdout:
        if re.search(r"Listening on", line):
            break

    # Yield control back to tests
    yield proc

    # Teardown: terminate the process
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()

@pytest.fixture(scope="session", autouse=True)
def discord_queues():
    return {
        'irc_to_discord_queue': asyncio.Queue(),
        'puppet_queue': asyncio.Queue(),
        'dm_out_queue': asyncio.Queue()
    }

@pytest.fixture(scope="session", autouse=True)
def irc_config():
    return {
        'server': 'localhost',
        'tls': 'no',
        'port': 6667,
        'listener_nickname': '_d2',
        'channels': ['#bots'],
        'puppet_suffix': '_d2'
    }

@pytest.fixture(scope="session", autouse=True)
def irc_config_ssl():
    return {
        'server': 'localhost',
        'tls': 'yes',
        'port': 6697,
        'listener_nickname': '_d2',
        'channels': ['#bots'],
        'puppet_suffix': '_d2'
    }


@pytest.mark.asyncio
async def test_irc_server_connection_plain(discord_queues, irc_config, irc_server):
    data = StatsData()
    await main.run_irclistener(discord_queues['irc_to_discord_queue'],
                                    irc_config, data)
    try:
        output = await asyncio.wait_for(
            asyncio.to_thread(irc_server.stdout.readline),
            timeout=2.0
        )
    except asyncio.TimeoutError:
        output = ''

    assert "Client connected" in output

@pytest.mark.asyncio
async def test_irc_server_connection_ssl(discord_queues, irc_config_ssl, irc_server, ssl_proxy):
    data = StatsData()
    await main.run_irclistener(discord_queues['irc_to_discord_queue'],
                               irc_config_ssl, data)
    try:
        output = await asyncio.wait_for(
            asyncio.to_thread(irc_server.stdout.readline),
            timeout=5.0
        )
    except asyncio.TimeoutError:
        output = ''
        pass

    assert "Client connected" in output

@pytest.mark.asyncio
async def test_irc_listener_recived_message(discord_queues, irc_config):
    data = StatsData()
    await main.run_irclistener(discord_queues['irc_to_discord_queue'],
                               irc_config, data)

    test_config = dict(irc_config)
    test_config['nickname'] = 'tester'
    bot = TestClient(test_config)
    await bot.start()

    ticks = 0
    while discord_queues['irc_to_discord_queue'].qsize() == 0 or ticks == 20:
        ticks = ticks + .1
        await asyncio.sleep(.1)

    assert discord_queues['irc_to_discord_queue'].qsize() == 1
    data = await discord_queues['irc_to_discord_queue'].get()
    assert data['content'] == 'hi'
    assert data['author'] == 'tester'
    assert data['error'] == False
    assert data['channel'] == '#bots'
