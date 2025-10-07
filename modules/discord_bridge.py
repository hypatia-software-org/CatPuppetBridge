"""Main thread for the DiscordBot part of the bridge"""

import re
import logging
import time
import queue
import asyncio

import discord


class DiscordBot(discord.Client):
    """Instance of discord.Client to run our bridge"""
    queues = None
    irc_to_discord_links = None
    discord_channel_mapping = None
    active_puppets = []
    mention_lookup = {}
    mention_lookup_re = None
    listener_config = None
    ready = False
    max_puppet_username = 30

    def __init__(self, queues, irc_to_discord_links, discord_config):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True
        intents.presences = True

        self.queues = queues
        self.irc_to_discord_links = irc_to_discord_links
        self.listener_config = discord_config

        super().__init__(intents=intents, chunk_guilds_at_startup=True)

    async def on_ready(self):
        """Init discord bot when ready, set the self.ready value"""
        logging.info('We have logged in as %s', self.user)
        self.discord_channel_mapping = {}
        for channel in self.irc_to_discord_links:
            self.discord_channel_mapping[channel] = self.get_channel(
                self.irc_to_discord_links[channel]) or \
                await self.fetch_channel(self.irc_to_discord_links[channel])

        #asyncio.create_task(self.process_queue())
        self.loop.create_task(self.process_queue())
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
        reserved_size = 2 + len(self.config['puppet_suffix']) # 2 for [] around username + suffix
        min_size = self.config['puppet_min_displayname_size']

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
            logging.info("Discord not ready yet")
        channels =  await self.accessible_channels(user.id)
        await self.send_irc_command(user, 'active', channels)

        self.active_puppets.append(user.id)

        await self.compile_mention_lookup_re(user)
        logging.info("%s is now active! (status: %s)", user.display_name, user.status)

    async def compile_mention_lookup_re(self, user: discord.Member = None):
        """Compile our regex for looking up mentions"""
        if user:
            irc_name = await self.generate_irc_nickname(user)
            self.mention_lookup[irc_name + self.listener_config['puppet_suffix']] = user
        self.mention_lookup_re = re.compile(
            r'\b(' + '|'.join(map(re.escape, self.mention_lookup.keys())) + r')\b')

    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Run on updates to members, check for display_name and role changes"""
        # Check for displayname Change
        if before.display_name != after.display_name:
            self.active_puppets.remove(before.id)
            self.active_puppets.append(after.id)
            await self.compile_mention_lookup_re(after)
            await self.send_irc_command(after, 'nick', None)
            logging.info("%s changed display name from"
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
                logging.info("%s is now offline! (status: %s)", after.display_name, after.status)

    async def send_irc_command(self, user, command, data=None, channel=None):
        """Send a command to an IRC Puppet"""
        logging.info('adding cmd to queue from discord: %s',command)
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

    async def on_member_remove(self, member):
        """Run when member is removed or leaves guild"""
        if member.id in self.active_puppets:
            # Update lookup table
            self.active_puppets.remove(member.id)
            irc_nick = await self.generate_irc_nickname(member)
            try:
                del self.mention_lookup[irc_nick + self.listener_config['puppet_suffix']]
                await self.compile_mention_lookup_re()
            except KeyError:
                logging.warning("Could not remove %s from mention_lookup table",
                                member.display_name)

            await self.send_irc_command(member, 'die')
            logging.info("%s has left!", member.display_name)

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
                    if self.mention_lookup_re:
                        processed_message = self.mention_lookup_re.sub(
                            lambda match: self.mention_lookup[match.group(0)].mention,
                            msg['content'])
                    # Detect Avatar
                    avatar = await self.find_avatar(msg['author'])
                    if avatar is None:
                        avatar = 'https://robohash.org/' + msg['author'] + '?set=set4'
                    try:
                        await webhook.send(processed_message, username=msg['author'],
                                           avatar_url=avatar)
                    except discord.errors.HTTPException:
                        logging.warning("HTTP Error sending webhook. Author: '%s' Message: '%s'",
                                        msg['author'], processed_message)
            except queue.Empty:
                pass
            await asyncio.sleep(0.01)

    async def find_avatar(self, user):
        """Find an avatar if user exists on irc and discord"""
        await self.guilds[0].chunk()
        members = self.guilds[0].members
        for member in members:
            if user == member.display_name:
                if member.avatar:
                    return member.avatar.url
        return None

    async def replace_customemotes(self, message):
        """Replace custom emotes with :emote_id:"""
        new_message = re.sub(r"<:([^:]+):\d+>", r":\1:", message)
        return new_message

    async def replace_channels(self, message):
        """Replace channel names with plaintext"""
        mention_pattern = r'<#!?(\d+)>'
        new_message = ""
        last_end = 0

        for match in re.finditer(mention_pattern, message):
            channel_id = int(match.group(1))
            new_message += message[last_end:match.start()]
            try:
                channel = self.guilds[0].get_channel(channel_id) or \
                    await self.guilds[0].fetch_channel(channel_id)
                new_message += '#' + channel.name
            except discord.NotFound as e:
                logging.error('failed to find channel %i', channel_id)
                logging.error(e)
                new_message += match.group(0)  # fallback: keep original mention
            last_end = match.end()

        new_message += message[last_end:]  # append rest of string
        return new_message


    async def replace_mentions(self, message):
        """Replace mentions with plaintext"""
        mention_pattern = r'<@!?(\d+)>'
        new_message = ""
        last_end = 0

        for match in re.finditer(mention_pattern, message):
            user_id = int(match.group(1))
            new_message += message[last_end:match.start()]
            try:
                user = self.get_user(user_id) or await self.fetch_user(user_id)
                irc_nick = await self.generate_irc_nickname(user)
                new_message += irc_nick + self.listener_config['puppet_suffix']
            except discord.NotFound as e:
                logging.error('failed to find user %i', user_id)
                logging.error(e)
                new_message += match.group(0)  # fallback: keep original mention
            last_end = match.end()

        new_message += message[last_end:]  # append rest of string
        return new_message

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
                    replied_to_content = await self.replace_mentions(replied_to_content)
                    replied_to_content = await self.replace_customemotes(replied_to_content)
                    replied_to_content = await self.replace_channels(replied_to_content)

                    template = 'replied to {author} "{message}...": {content}'
                    content = template.format(author=reply_author,
                                              message=replied_to_content,
                                              content=content)
                except discord.NotFound:
                    logging.info("Reply not found to message %s", message.content)

            content = await self.replace_mentions(content)
            content = await self.replace_customemotes(content)
            content = await self.replace_channels(content)

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
        if message.author.bot and message.webhook_id is not None:
            return

        if not self.active_puppets or message.author.id not in self.active_puppets:
            await self.activate_puppet(message.author)

        content, attach = await self.parse_message_content(message)

        if attach:
            await self.send_irc_command(message.author, 'send', attach, message.channel.id)
        if content and content != attach:
            await self.send_irc_command(message.author, 'send', content, message.channel.id)
