import subprocess
import time
import pytest
import signal
import main
import ssl
import socket
from irc import client

from modules.irc_bridge import IRCBot, IRCListener, IRCPuppet
import threading
from queue import Queue

def say_hi_and_quit(server: str = 'localhost', port: int = 6667, nickname: str = 'test', channel: str = "#bots", use_ssl: bool = False):
    """Connect to an IRC server, join a channel, and say hi using the irc library."""
    
    reactor = client.Reactor()

    def on_connect(connection, event):
        if client.is_channel(channel):
            connection.join(channel)

    def on_join(connection, event):
        print(f"Joined {channel}, sending message…")
        connection.privmsg(channel, "hi")
        connection.quit()
        import sys
        sys.exit()


    def on_disconnect(connection, event):
        print("Disconnected from server.")
    
    # Register callbacks
    reactor.add_global_handler("welcome", on_connect)
    reactor.add_global_handler("join", on_join)
    reactor.add_global_handler("disconnect", on_disconnect)

    # Set up connection factory (SSL or plain)
    if use_ssl:
        ssl_factory = client.connection.Factory(wrapper=ssl.wrap_socket)
        conn = reactor.server().connect(server, port, nickname, connect_factory=ssl_factory)
    else:
        conn = reactor.server().connect(server, port, nickname)

    # Run the reactor loop until the connection closes
    reactor.process_forever()

@pytest.fixture(scope="function")
def ssl_proxy():
    """Start a simple SSL forwarder for IRC on port 6697 -> 6667."""

    # Create SSL context
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    context.load_cert_chain(certfile="tests/server.crt", keyfile="tests/server.key")

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
        'irc_to_discord_queue': Queue(),
        'puppet_queue': Queue(),
        'dm_out_queue': Queue()
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

def test_irc_server_connection_plain(discord_queues, irc_config, irc_server):
    thread = threading.Thread(target=main.run_irclistener,
                              args=[discord_queues['irc_to_discord_queue'],
                                    irc_config], daemon=True).start()
    output = irc_server.stdout.readline().strip()
    assert "Client connected" in output
    
def test_irc_server_connection_ssl(discord_queues, irc_config_ssl, irc_server, ssl_proxy):
    thread = threading.Thread(target=main.run_irclistener,
                              args=[discord_queues['irc_to_discord_queue'],
                                    irc_config_ssl], daemon=True).start()
    output = irc_server.stdout.readline().strip()
    assert "Client connected" in output
    
def test_irc_listener_recived_message(discord_queues, irc_config):
    
    thread = threading.Thread(target=main.run_irclistener,
                              args=[discord_queues['irc_to_discord_queue'],
                                    irc_config], daemon=True).start()
    try:
        say_hi_and_quit()
    except SystemExit:
        pass
    import time
    time.sleep(1)
    assert discord_queues['irc_to_discord_queue'].qsize() == 1
