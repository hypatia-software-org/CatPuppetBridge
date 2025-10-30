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

Main thread for the DiscordBot part of the bridge
"""

import re
import logging
import time
import queue
import asyncio
import emoji
import discord

from modules.discord_filters import DiscordFilters


class DiscordBot(discord.Client):
    """Instance of discord.Client to run our bridge"""
    queues = None
    irc_to_discord_links = None
    discord_channel_mapping = None
    active_puppets = []
    listener_config = None
    ready = False
    max_puppet_username = 30
    filters = None

    def __init__(self, queues, irc_to_discord_links, discord_config, data):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True
        intents.presences = True

        self.data = data
        self.filters = DiscordFilters(self)

        self.queues = queues
        self.irc_to_discord_links = irc_to_discord_links
        self.listener_config = discord_config
        logging.getLogger('discord.gateway').setLevel(discord_config['log_level'])
        logging.getLogger('discord.client').setLevel(discord_config['log_level'])

        super().__init__(intents=intents, chunk_guilds_at_startup=True)

    async def on_ready(self):
        """Init discord bot when ready, set the self.ready value"""
        logging.debug('We have logged in as %s', self.user)
        self.discord_channel_mapping = {}
        for channel in self.irc_to_discord_links:
            self.discord_channel_mapping[channel] = self.get_channel(
                self.irc_to_discord_links[channel]) or \
                await self.fetch_channel(self.irc_to_discord_links[channel])

        #asyncio.create_task(self.process_queue())
        self.loop.create_task(self.process_queue())
        self.loop.create_task(self.process_dm_queue())
        self.ready = True

    def irc_safe_nickname(self, nickname: str) -> str:
        """Strip non-irc safe characters for nicknames"""
        allowed_special = r"\[\]\\`_^{|}"
        nickname = nickname.strip()

        first_char = nickname[0]
        if not re.match(r"[A-Za-z" + allowed_special + "]", first_char):
            nickname = "_" + nickname[1:]

        valid_nick = re.sub(r"[^A-Za-z0-9" + allowed_special + "]", "", nickname)
        return valid_nick

    async def generate_irc_nickname(self, user):
        """Generate an irc nickname"""
        username = self.irc_safe_nickname(user.name)
        display_name = self.irc_safe_nickname(user.display_name)

        # 2 for [] around username + suffix
        reserved_size = 2 + len(self.listener_config['puppet_suffix'])
        min_size = self.listener_config['puppet_min_size']

        if len(display_name) + len(username) + reserved_size > self.max_puppet_username:
            remove_len = (len(display_name) + len(username) + reserved_size) \
                - self.max_puppet_username
            if remove_len > len(display_name):
                remove_len = len(display_name) - min_size
            username = username[:len(username)-remove_len]
        #still too big? shorten the display name too (sheesh)
        if len(display_name) + len(username) + reserved_size > self.max_puppet_username:
            remove_len = (len(display_name) + len(username) + reserved_size) \
                - self.max_puppet_username
            display_name = display_name[:len(display_name)-remove_len]

        return f"{display_name}[{username}]".format(display_name=display_name, username=username)

    async def activate_puppet(self, user):
        """Push to the puppet queue to activate an irc puppet"""
        if not self.ready:
            logging.debug("Discord not ready yet")
        channels =  await self.accessible_channels(user.id)
        await self.send_irc_command(user, 'active', channels)

        self.active_puppets.append(user.id)

        await self.filters.compile_mention_lookup_re(user)
        logging.debug("%s is now active! (status: %s)", user.display_name, user.status)

    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Run on updates to members, check for display_name and role changes"""
        # Check for displayname Change
        if before.display_name != after.display_name:
            self.active_puppets.remove(before.id)
            self.active_puppets.append(after.id)
            await self.filters.compile_mention_lookup_re(after)
            await self.send_irc_command(after, 'nick', None)
            logging.debug("%s changed display name from"
                         "'%s' to '%s'",
                         before.name, before.display_name, after.display_name)

        # Check for role change:
        before_roles = set(before.roles)
        after_roles = set(after.roles)
        if before_roles != after_roles:
            channels =  await self.accessible_channels(after.id)
            await self.send_irc_command(after, 'join_part', channels)

    async def on_presence_update(self, before, after):
        """Manage AFK vs UNAFK status for puppets"""
        # Make sure we are ready:
        if not self.ready:
            return

        # Check if the user went from offline or dnd to online or idle
        previously_inactive = before.status in (discord.Status.offline, discord.Status.dnd)
        previously_active = before.status in (discord.Status.online, discord.Status.idle)
        now_active = after.status in (discord.Status.online, discord.Status.idle)
        now_inactive = after.status in (discord.Status.offline, discord.Status.dnd)

        if previously_inactive and now_active:
            if after.id in self.active_puppets:
                await self.send_irc_command(after, 'unafk')
            else:
                await self.activate_puppet(after)
        if previously_active and now_inactive:
            if after.id in self.active_puppets:
                await self.send_irc_command(after, 'afk')
                logging.debug("%s is now offline! (status: %s)", after.display_name, after.status)

    async def send_irc_command(self, user, command, data=None, channel=None):
        """Send a command to an IRC Puppet"""
        logging.debug('adding cmd to queue from discord: %s',command)
        self.queues['puppet_queue'].put({
            'nick': self.irc_safe_nickname(user.display_name),
            'display_name': user.display_name,
            'irc_nick': await self.generate_irc_nickname(user),
            'name': user.name,
            'id': user.id,
            'channel': channel,
            'command': command,
            'data': data,
            'timestamp': time.time()
        })
        if command == 'send':
            self.data.increment('discord_messages')

    async def on_member_remove(self, member):
        """Run when member is removed or leaves guild"""
        if member.id in self.active_puppets:
            # Update lookup table
            self.active_puppets.remove(member.id)
            irc_nick = await self.generate_irc_nickname(member)
            try:
                await self.filters.remove_from_mention_lookup(
                    irc_nick + self.listener_config['puppet_suffix'])
            except KeyError:
                logging.warning("Could not remove %s from mention_lookup table",
                                member.display_name)

            await self.send_irc_command(member, 'die')
            logging.debug("%s has left!", member.display_name)

    async def process_queue(self):
        """Thread to process our incoming queue from IRC"""
        while True:
        # Periodically check the queue and send messages
            try:
                msg = self.queues['irc_to_discord_queue'].get(timeout=0.5)
                channel = None

                if msg['channel'] in self.discord_channel_mapping:
                    channel = self.discord_channel_mapping[msg['channel']]

                if channel:
                    webhooks = await channel.webhooks()
                    webhook_name = 'CatPuppetBridge'
                    webhook = None
                    logging.debug("Searching for webhook")
                    for hook in webhooks:
                        if hook.name == webhook_name:
                            logging.debug("Reusing old webhook")
                            webhook = hook
                            break
                    if webhook is None:
                        logging.debug("Creating new webhook")
                        webhook = await channel.create_webhook(name='CatPuppetBridge')

                    # detect mentions
                    processed_message = msg['content']
                    if self.filters.mention_lookup_re:
                        processed_message = self.filters.lookup_mention(msg['content'])
                    # Detect Avatar
                    avatar = await self.find_avatar(msg['author'])
                    if avatar is None:
                        avatar = 'https://robohash.org/' + msg['author'] + '?set=set4'
                    # Detect emojis
                    processed_message = await self.replace_emojis(processed_message)
                    try:
                        await webhook.send(processed_message, username=msg['author'],
                                           avatar_url=avatar)
                    except discord.errors.HTTPException:
                        logging.warning("HTTP Error sending webhook. Author: '%s' Message: '%s'",
                                        msg['author'], processed_message)
            except queue.Empty:
                pass
            await asyncio.sleep(0.01)

    async def process_dm_queue(self):
        """Thread to process our incoming dm_queue from IRC private messages"""
        while True:
        # Periodically check the queue and send messages
            try:
                msg = self.queues['dm_out_queue'].get(timeout=0.5)
                target = None
                user = None

                if self.mention_lookup_re:
                    target = self.mention_lookup_re.sub(
                        lambda match: self.mention_lookup[match.group(0)].mention,
                        msg['channel'])
                    user_id = re.match(r"<@!?(\d+)>", target)
                    user = await self.fetch_user(user_id.group(1))
                if user:
                    # detect mentions
                    processed_message = msg['content']
                    if self.mention_lookup_re:
                        processed_message = self.mention_lookup_re.sub(
                            lambda match: self.mention_lookup[match.group(0)].mention,
                            msg['content'])
                        processed_message = 'Message from IRC user ' + msg['author'] + ': ' +\
                            processed_message
                    try:
                        await user.send(processed_message)
                    except discord.errors.HTTPException as e:
                        logging.warn(e)
            except queue.Empty:
                pass
            await asyncio.sleep(0.01)

    async def replace_emojis(self, processed_message):
        """ Replace strings like :heart: with their unicode emoji, or discord custom emoji """
        def replace(match):
            found_emoji = match.group(1)
            for discord_emoji in self.emojis:
                if discord_emoji.name == found_emoji:
                    return str(discord_emoji)
            unicode_emoji = emoji.emojize(f":{found_emoji}:", language='alias')
            if unicode_emoji != f":{found_emoji}:":
                return unicode_emoji

            # Fallback if not found
            return f":{found_emoji}:"

        return re.sub(r":([a-zA-Z0-9_]+):", replace, processed_message)

    async def find_avatar(self, user):
        """Find an avatar if user exists on irc and discord"""
        await self.guilds[0].chunk()
        members = self.guilds[0].members
        for member in members:
            if user == member.display_name:
                if member.avatar:
                    return member.avatar.url
        return None

    async def accessible_channels(self, user_id: int):
        """Find out what channels a puppet can see"""
        member = self.guilds[0].get_member(user_id) or await self.guilds[0].fetch_member(user_id)

        if not member:
            return []

        accessible = []

        for channel in self.discord_channel_mapping.items():
            if isinstance(channel[1], discord.abc.GuildChannel):
                perms = channel[1].permissions_for(member)
                if perms.view_channel:
                    accessible.append(channel[1].id)

        return accessible

    async def parse_message_content(self, message):
        """Parse message content and attachments"""
        content = None
        attach = None

        # Check for attachments
        for attachment in message.attachments:
            attach = attachment.url

        # Check for embeded images
        for embed in message.embeds:
            if embed.url:
                attach = embed.url
            elif embed.image.url:
                attach = embed.image.url
        if message.content:
            content = message.content

            # Check if this is a reply to a thread
            if message.reference and message.reference.message_id:
                try:
                    replied_to = await message.channel.fetch_message(message.reference.message_id)
                    if replied_to.webhook_id:
                        split_author = replied_to.author.name.split('#')
                        reply_author = split_author[0]
                    else:
                        reply_author = await self.generate_irc_nickname(replied_to.author)

                    replied_to_content = replied_to.content[:50]
                    replied_to_content = await self.filters.replace_mentions(replied_to_content)
                    replied_to_content = await self.filters.replace_customemotes(replied_to_content)
                    replied_to_content = await self.filters.replace_channels(replied_to_content)
                    replied_to_content = self.filters.replace_time(replied_to_content)

                    template = 'replied to {author} "{message}...": {content}'
                    content = template.format(author=reply_author,
                                              message=replied_to_content,
                                              content=content)
                except discord.NotFound:
                    logging.debug("Reply not found to message %s", message.content)

            content = await self.filters.replace_mentions(content)
            content = await self.filters.replace_customemotes(content)
            content = await self.filters.replace_channels(content)
            content = self.filters.replace_time(content)

        return content, attach

    async def on_message_edit(self, before, after):
        """Run when messages are edited on discord"""
        content = None
        attach = None
        if before.content != after.content:
            content, attach = await self.parse_message_content(after)

        if attach:
            await self.send_irc_command(before.author, 'send', attach, before.channel.id)
        if content and content != attach:
            content = '[edit] ' + content
            await self.send_irc_command(before.author, 'send', content, before.channel.id)

    async def on_message(self, message):
        """Run when messages are read from discord"""

        # Make sure we are ready first
        if not self.ready:
            return
        # Don't repeat messages
        if message.author.bot or message.webhook_id is not None:
            return

        if isinstance(message.channel, discord.DMChannel):
            logging.info("Discord bot received a DM, processing")

            dm_user = await self.fetch_user(message.author.id)
            if not self.active_puppets or message.author.id not in self.active_puppets:
                await self.activate_puppet(dm_user)
            reply = ''
            split_msg = message.content.split()
            command = split_msg[0] if len(split_msg) >= 1 else None
            if command == 'help':
                # pylint: disable=line-too-long
                reply = 'This is the CatPuppetBridge bot, that links Discord to IRC. Here is a list of commands:\n'\
                '* `dm USERNAME MESSAGE` - Send a Direct Message to a user on IRC. For example: `dm coolusername Whats up?` would DM `coolusername` on IRC the message `Whats up?`\n'\
                '* `session USERNAME` - Open a session with a user on IRC. All messages typed to this bot will be sent to the user until the session is ended\n'\
                '* `sessionend` - End a session with an IRC user\n'
            elif command == 'dm':
                if len(split_msg) >= 3:
                    target_user = split_msg[1]
                    dm = ' '.join(split_msg[2:])
                    await self.send_irc_command(message.author, 'send_dm', dm, target_user)
                else:
                    reply = 'Not enough parameters. Be sure to type `dm USERNAME MESSAGE`'
            elif command == "session":
                if len(split_msg) >= 2:
                    target_user = split_msg[1]
                else:
                    reply = 'Not enough parameters. Be sure to type `session USERNAME`'
            else:
                reply = 'Command not found, try using the command `help` for more information.'
            try:
                await dm_user.send(reply)
            except discord.errors.HTTPException as e:
                logging.error(e)
            return

        if not self.active_puppets or message.author.id not in self.active_puppets:
            await self.activate_puppet(message.author)

        content, attach = await self.parse_message_content(message)

        if attach:
            await self.send_irc_command(message.author, 'send', attach, message.channel.id)
        if content and content != attach:
            await self.send_irc_command(message.author, 'send', content, message.channel.id)
