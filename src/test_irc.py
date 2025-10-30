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

import pytest
import sys
import os
from queue import Queue
from unittest.mock import MagicMock, patch
import logging
from irc import server

from modules.irc_bridge import IRCBot, IRCListener, IRCPuppet

irc_server = server

message = {
    'channel': '#test-channel',
    'nickname': 'test_user',
    'data': 'The quick brown fox jumped over the lazy dog'
}

def reset_puppet(puppet):
    puppet.config['nickname'] = 'testPuppet[puppet]_d2'
    puppet.config['webirc_hostname'] = 'localhost'
    puppet.channels = ['1', '2', '3']
    puppet.discord_to_irc_links = {'1': '#test1', '2': "#test2", '3': "#bots",'4': '#new_channel'}
    puppet.connection.reset_mock()
    puppet.queues = {'in_queue' : Queue(), 'out_queue': Queue()}
    puppet.ready = True
    return puppet

@pytest.fixture
def puppet():
    real = IRCPuppet.__new__(IRCPuppet)
    real.connection = MagicMock()
    real.log = logging.getLogger('unittest')
    reset_puppet(real)

    yield real

    # Reset object
    reset_puppet(real)

def test_puppet_afk(puppet):
    puppet.afk()
    puppet.connection.send_raw.assert_called_once_with("AWAY User is away on discord")


def test_puppet_unafk(puppet):
    puppet.unafk()
    puppet.connection.send_raw.assert_called_once_with("AWAY")

    
def test_puppet_split_irc_message_short_message(puppet):
    """Verify split_irc_message() does not split short messages message, should not split the message"""
    msg = message
    result = puppet.split_irc_message(msg)
    assert len(result) == 1

def test_puppet_split_irc_message_long_message(puppet):
    """Verify split_irc_message() split a long message, should be split into 2 smaller messages"""
    msg = message
    msg['data'] = 'The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog.'
    result = puppet.split_irc_message(message)
    assert len(result) == 2

def test_puppet_split_irc_message_very_long_message(puppet):
    """Verify split_irc_message() split very long message, should be split into 6 smaller messages"""
    msg = message
    msg['data'] = 'The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. '
    result = puppet.split_irc_message(message)
    assert len(result) == 6

def test_puppet_split_irc_message_hostname(puppet):
    """Verify split_irc_message() split a long message due to a long hostname, should be split into 2 smaller messages"""
    msg = message
    msg['data'] = 'The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog.'

    # Set the long hostname
    puppet.config['webirc_hostname'] = 'localhostlocalhostlocalhostlocalhost'
    result = puppet.split_irc_message(message)
    assert len(result) == 2

def test_puppet_split_irc_message_username(puppet):
    """Verify split_irc_message() split a long message due to a long username, should be split into 2 smaller messages"""
    msg = message
    msg['data'] = 'The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog. The quick brown fox jumped over the lazy dog.'

    # Set the long hostname
    puppet.config['nickname'] = 'testUsertestUsertestUsertestUser[TestUser]_d2'
    result = puppet.split_irc_message(message)
    assert len(result) == 2

def test_puppet_join_part_part_channel(puppet):
    """Test join_part() parting a channel (#bots)"""
    channels = puppet.channels.copy()
    channels.remove('1')

    puppet.join_part(channels)
    assert puppet.channels == channels
    assert len(puppet.channels) == 2

def test_puppet_join_part_join_channel(puppet):
    """Test join_part() joining a channel (#new_channel)"""
    new_channel = '4'
    channels = puppet.channels.copy()
    channels.append(new_channel)
    puppet.join_part(channels)

    puppet.connection.join.assert_called_once_with(puppet.discord_to_irc_links[str(new_channel)])
    assert puppet.channels == channels
    assert new_channel in channels
    assert len(puppet.channels) == 4

def test_puppet_join_part_no_change(puppet):
    """Test join_part() with no change (no joining or parting)"""

    channels = puppet.channels

    puppet.join_part(channels)

    assert puppet.channels == channels
    assert len(puppet.channels) == 3

def test_puppet_on_privmsg(puppet):
    """Test queuing out to discord queue from an IRC private message"""
    # Assert queue is empty
    assert puppet.queues['out_queue'].qsize() == 0

    c = MagicMock()
    event = MagicMock()
    event.source = "TestUser!ident@host"
    event.arguments = ["So what's up gang?"]

    puppet.on_privmsg(c, event)

    # Assert message has been added to queue
    assert puppet.queues['out_queue'].qsize() == 1

    # Assert data is correct
    data = puppet.queues['out_queue'].get()
    assert data['author'] == 'TestUser'
    assert data['channel'] == puppet.config['nickname']
    assert data['content'] == event.arguments[0]

def test_puppet_process_discord_queue_afk(puppet): 
    """Test if inbound queue receives "AFK" and processes it"""
    msg = {}
    msg['command'] = 'afk'
    puppet.queues['in_queue'].put(msg)

    # needed to break the loop
    msg2 = {}
    msg2['command'] = 'die'
    puppet.queues['in_queue'].put(msg2)

    with pytest.raises(SystemExit):
        puppet.process_discord_queue()

    puppet.connection.send_raw.assert_called_once_with("AWAY User is away on discord")

def test_puppet_process_discord_queue_unafk(puppet): 
    """Test if inbound queue receives "UNAFK" and processes it"""
    msg = {}
    msg['command'] = 'unafk'
    puppet.queues['in_queue'].put(msg)

    # needed to break the loop
    msg2 = {}
    msg2['command'] = 'die'
    puppet.queues['in_queue'].put(msg2)

    with pytest.raises(SystemExit):
        puppet.process_discord_queue()

    puppet.connection.send_raw.assert_called_once_with("AWAY")

def test_puppet_process_discord_queue_nick(puppet): 
    """Test if inbound queue receives "nick" and processes it"""
    msg = {}
    msg['command'] = 'nick'
    msg['irc_nick'] = 'newNick[newUsername]_d2'
    puppet.queues['in_queue'].put(msg)

    # needed to break the loop
    msg2 = {}
    msg2['command'] = 'die'
    puppet.queues['in_queue'].put(msg2)

    with pytest.raises(SystemExit):
        puppet.process_discord_queue()

    puppet.connection.nick.assert_called_once_with(msg['irc_nick'])

def test_puppet_process_discord_queue_join(puppet): 
    """Test if inbound queue receives "join_part" and processes it to join a channel"""
    msg = {}
    msg['command'] = 'join_part'
    new_channel = '4'
    channels = puppet.channels.copy()
    channels.append(new_channel)
    msg['data'] = channels
    puppet.queues['in_queue'].put(msg)

    # needed to break the loop
    msg2 = {}
    msg2['command'] = 'die'
    puppet.queues['in_queue'].put(msg2)

    with pytest.raises(SystemExit):
        puppet.process_discord_queue()

    puppet.connection.join.assert_called_once_with(puppet.discord_to_irc_links[str(new_channel)])
    assert puppet.channels == channels
    assert new_channel in channels
    assert len(puppet.channels) == 4
    
def test_puppet_process_discord_queue_part(puppet): 
    """Test if inbound queue receives "join_part" and processes it to part a channel"""
    msg = {}
    msg['command'] = 'join_part'
    channels = puppet.channels.copy()
    channels.remove('2')
    msg['data'] = channels
    puppet.queues['in_queue'].put(msg)

    # needed to break the loop
    msg2 = {}
    msg2['command'] = 'die'
    puppet.queues['in_queue'].put(msg2)

    with pytest.raises(SystemExit):
        puppet.process_discord_queue()

    puppet.connection.part.assert_called_once_with(puppet.discord_to_irc_links['2'])
    assert puppet.channels == channels
    assert len(puppet.channels) == 2

def test_puppet_process_discord_queue_send(puppet): 
    """Test if inbound queue receives "nick" and processes it"""
    msg = {}
    msg['command'] = 'send'
    msg['channel'] = '3'
    msg['data'] = 'The quick brown fox jumped over the lazy dog.'

    puppet.queues['in_queue'].put(msg)

    # needed to break the loop
    msg2 = {}
    msg2['command'] = 'die'
    puppet.queues['in_queue'].put(msg2)

    with pytest.raises(SystemExit):
        puppet.process_discord_queue()

    puppet.connection.privmsg.assert_called_once_with(puppet.discord_to_irc_links[msg['channel']], msg['data'])
