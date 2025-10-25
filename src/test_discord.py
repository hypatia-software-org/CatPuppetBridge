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
import asyncio
from queue import Queue, Empty
from unittest.mock import MagicMock, patch, AsyncMock
from irc import server
import discord

from modules.discord_bridge import DiscordBot


def create_fake_user(
        id=12345,
        name="TestUser",
        discriminator="0001",
        display_name=None,
        bot=False,
        avatar_url="https://example.invalid/avatar.png",
        status=discord.Status.online
):
    u = MagicMock()
    u.id = id
    u.name = name
    u.discriminator = discriminator
    u.display_name = display_name or name
    u.bot = bot
    u.mention = f"<@{id}>"
    # emulate str(user) -> "name#discriminator"
    u.__str__.return_value = f"{name}#{discriminator}"

    u.send = AsyncMock()
    # display_avatar.url used by many libs
    display_avatar = MagicMock()
    display_avatar.url = avatar_url
    u.avatar = display_avatar
    u.status = status
    return u

def reset_bot(bot):
    bot.queues['puppet_queue'] = Queue()


@pytest.fixture
def bot():
    real = DiscordBot.__new__(DiscordBot);
    real._connection = AsyncMock()
    real.http = None
    real.irc_to_discord_links = {'#test1': '1', "#test2": '2', "#bots": '3','#new_channel': '4'}
    real.channel = AsyncMock()
    real.message = AsyncMock()
    real.loop = AsyncMock()

    real.listener_config = {}
    real.listener_config['puppet_suffix'] = '_d2'
    real.listener_config['puppet_min_size'] = 6
    real.queues = {}
    real.queues['puppet_queue'] = Queue()
    real.queues['in_queue'] = Queue()

    real.guilds[0].chunk = AsyncMock()
    real.guilds[0].members = [create_fake_user()]

    channel = AsyncMock()
    message = AsyncMock()
    bot.queues = {'puppet_queue': Queue(), 'in_queue': Queue()}

    yield real
    reset_bot(bot)

def test_on_irc_safe_nickname(bot):
    nickname = bot.irc_safe_nickname('This is a really long name with spaces 😍')
    assert nickname == 'Thisisareallylongnamewithspaces'

@pytest.mark.filterwarnings("ignore:coroutine 'AsyncMockMixin._execute_mock_call' was never awaited:RuntimeWarning")
@pytest.mark.asyncio
async def test_activate_puppet(bot):
    user = create_fake_user()

    with patch.object(bot.loop, "create_task", lambda coro: None):
        with patch.object(bot, "process_queue", AsyncMock()):
            await bot.on_ready()
    await bot.activate_puppet(user)

    assert bot.queues['puppet_queue'].qsize() == 1

@pytest.mark.filterwarnings("ignore:coroutine 'AsyncMockMixin._execute_mock_call' was never awaited:RuntimeWarning")
@pytest.mark.asyncio
async def test_on_member_update(bot):
    user_before = create_fake_user()
    user_after = create_fake_user()

    with patch.object(bot.loop, "create_task", lambda coro: None):
        with patch.object(bot, "process_queue", AsyncMock()):
            await bot.on_ready()
    user_before.display_name = 'name_a'
    user_after.display_name = 'name_b'

    await bot.activate_puppet(user_before)

    # "Fake process" the activation, removing it from queue
    data = bot.queues['puppet_queue'].get(False)

    await bot.on_member_update(user_before, user_after)
    assert bot.queues['puppet_queue'].qsize() == 1


    data = bot.queues['puppet_queue'].get(False)
    assert data['display_name'] == 'name_b'
    assert data['irc_nick'] == 'name_b[TestUser]'
    assert data['name'] == 'TestUser'


@pytest.mark.filterwarnings("ignore:coroutine 'AsyncMockMixin._execute_mock_call' was never awaited:RuntimeWarning")
@pytest.mark.asyncio
async def test_on_presence_update_online_to_offline(bot):
    user_before = create_fake_user()
    user_after = create_fake_user(status=discord.Status.offline)

    with patch.object(bot.loop, "create_task", lambda coro: None):
        with patch.object(bot, "process_queue", AsyncMock()):
            await bot.on_ready()

    await bot.activate_puppet(user_before)

    # "Fake process" the activation, removing it from queue
    data = bot.queues['puppet_queue'].get(False)

    await bot.on_presence_update(user_before, user_after)
    
    assert bot.queues['puppet_queue'].qsize() == 1

    data = bot.queues['puppet_queue'].get(False)
    assert data['command'] == 'afk'

@pytest.mark.filterwarnings("ignore:coroutine 'AsyncMockMixin._execute_mock_call' was never awaited:RuntimeWarning")
@pytest.mark.asyncio
async def test_on_presence_update_online_to_dnd(bot):
    user_before = create_fake_user()
    user_after = create_fake_user(status=discord.Status.dnd)

    with patch.object(bot.loop, "create_task", lambda coro: None):
        with patch.object(bot, "process_queue", AsyncMock()):
            await bot.on_ready()

    await bot.activate_puppet(user_before)

    # "Fake process" the activation, removing it from queue
    data = bot.queues['puppet_queue'].get(False)

    await bot.on_presence_update(user_before, user_after)
    
    assert bot.queues['puppet_queue'].qsize() == 1

    data = bot.queues['puppet_queue'].get(False)
    assert data['command'] == 'afk'

@pytest.mark.filterwarnings("ignore:coroutine 'AsyncMockMixin._execute_mock_call' was never awaited:RuntimeWarning")
@pytest.mark.asyncio
async def test_on_presence_update_offline_to_idle(bot):
    user_before = create_fake_user(status=discord.Status.offline)
    user_after = create_fake_user(status=discord.Status.idle)

    with patch.object(bot.loop, "create_task", lambda coro: None):
        with patch.object(bot, "process_queue", AsyncMock()):
            await bot.on_ready()

    await bot.activate_puppet(user_before)

    # "Fake process" the activation, removing it from queue
    data = bot.queues['puppet_queue'].get(False)

    await bot.on_presence_update(user_before, user_after)
    
    assert bot.queues['puppet_queue'].qsize() == 1

    data = bot.queues['puppet_queue'].get(False)
    assert data['command'] == 'unafk'

@pytest.mark.filterwarnings("ignore:coroutine 'AsyncMockMixin._execute_mock_call' was never awaited:RuntimeWarning")
@pytest.mark.asyncio
async def test_on_presence_update_offline_to_online(bot):
    user_before = create_fake_user(status=discord.Status.offline)
    user_after = create_fake_user()

    with patch.object(bot.loop, "create_task", lambda coro: None):
        with patch.object(bot, "process_queue", AsyncMock()):
            await bot.on_ready()

    await bot.activate_puppet(user_before)

    # "Fake process" the activation, removing it from queue
    data = bot.queues['puppet_queue'].get(False)

    await bot.on_presence_update(user_before, user_after)
    
    assert bot.queues['puppet_queue'].qsize() == 1

    data = bot.queues['puppet_queue'].get(False)
    assert data['command'] == 'unafk'

@pytest.mark.filterwarnings("ignore:coroutine 'AsyncMockMixin._execute_mock_call' was never awaited:RuntimeWarning")
@pytest.mark.asyncio
async def test_on_presence_update_dnd_to_online(bot):
    user_before = create_fake_user(status=discord.Status.dnd)
    user_after = create_fake_user()

    with patch.object(bot.loop, "create_task", lambda coro: None):
        with patch.object(bot, "process_queue", AsyncMock()):
            await bot.on_ready()

    await bot.activate_puppet(user_before)

    # "Fake process" the activation, removing it from queue
    data = bot.queues['puppet_queue'].get(False)

    await bot.on_presence_update(user_before, user_after)
    
    assert bot.queues['puppet_queue'].qsize() == 1

    data = bot.queues['puppet_queue'].get(False)
    assert data['command'] == 'unafk'

@pytest.mark.filterwarnings("ignore:coroutine 'AsyncMockMixin._execute_mock_call' was never awaited:RuntimeWarning")
@pytest.mark.asyncio
async def test_on_presence_update_offline_to_dnd(bot):
    user_before = create_fake_user(status=discord.Status.offline)
    user_after = create_fake_user(status=discord.Status.dnd)

    with patch.object(bot.loop, "create_task", lambda coro: None):
        with patch.object(bot, "process_queue", AsyncMock()):
            await bot.on_ready()

    await bot.activate_puppet(user_before)

    # "Fake process" the activation, removing it from queue
    data = bot.queues['puppet_queue'].get(False)

    await bot.on_presence_update(user_before, user_after)
    
    assert bot.queues['puppet_queue'].qsize() == 0

@pytest.mark.filterwarnings("ignore:coroutine 'AsyncMockMixin._execute_mock_call' was never awaited:RuntimeWarning")
@pytest.mark.asyncio
async def test_on_presence_update_online_to_idle(bot):
    user_before = create_fake_user(status=discord.Status.online)
    user_after = create_fake_user(status=discord.Status.idle)

    with patch.object(bot.loop, "create_task", lambda coro: None):
        with patch.object(bot, "process_queue", AsyncMock()):
            await bot.on_ready()

    await bot.activate_puppet(user_before)

    # "Fake process" the activation, removing it from queue
    data = bot.queues['puppet_queue'].get(False)

    await bot.on_presence_update(user_before, user_after)
    
    assert bot.queues['puppet_queue'].qsize() == 0

@pytest.mark.filterwarnings("ignore:coroutine 'AsyncMockMixin._execute_mock_call' was never awaited:RuntimeWarning")
@pytest.mark.asyncio
async def test_on_member_remove(bot):
    user = create_fake_user()

    with patch.object(bot.loop, "create_task", lambda coro: None):
        with patch.object(bot, "process_queue", AsyncMock()):
            await bot.on_ready()

    await bot.activate_puppet(user)

    # "Fake process" the activation, removing it from queue
    data = bot.queues['puppet_queue'].get(False)

    await bot.on_member_remove(user)
    
    assert bot.queues['puppet_queue'].qsize() == 1

    data = bot.queues['puppet_queue'].get(False)
    assert data['command'] == 'die'

@pytest.mark.asyncio
async def test_find_avatar(bot):
    user = create_fake_user()
    avatar = await bot.find_avatar(user.display_name)
    assert avatar == 'https://example.invalid/avatar.png'

@pytest.mark.asyncio
async def test_dont_find_avatar(bot):
    nickname = 'Bob'
    avatar = await bot.find_avatar(nickname)
    assert avatar == None

@pytest.mark.asyncio
async def test_covert_discord_time_default(bot):
    time = '<t:1761385165>'
    human_time = bot.replace_time(time)

    assert human_time == 'October 25, 2025 09:39'

@pytest.mark.asyncio
async def test_covert_discord_time_default_with_text(bot):
    time = 'Lets meet at <t:1761385165> for the meeting!'
    human_time = bot.replace_time(time)

    assert human_time == 'Lets meet at October 25, 2025 09:39 for the meeting!'

@pytest.mark.asyncio
async def test_covert_discord_time_relative(bot):
    import time
    ts = int(time.time()) - 60*60*5
    time = f'<t:{ts}:R>'.format(ts)
    human_time = bot.replace_time(time)

    assert human_time == '5 hours ago'

@pytest.mark.asyncio
async def test_covert_discord_time_secs(bot):
    ts = '1761385165'
    time = f'<t:{ts}:T>'.format(ts)
    human_time = bot.replace_time(time)

    assert human_time == '09:39:25'

@pytest.mark.asyncio
async def test_covert_discord_time(bot):
    ts = '1761385165'
    time = f'<t:{ts}:t>'.format(ts)
    human_time = bot.replace_time(time)

    assert human_time == '09:39'
