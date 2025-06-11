import asyncio
import discord
import threading
import time
import re
import queue
import logging


class DiscordBot(discord.Client):
    inQueue = None
    outQueue = None
    ircToDiscordLinks = None
    discordChannelMapping = None
    PuppetQueue = None
    guild = None
    active_puppets = []
    mention_lookup = {}
    mention_lookup_re = None
    listener_config = None
    ready = False
    process_queue_thread = None
    max_puppet_username = 30

    def __init__(self, inQueue, outQueue, PuppetQueue, ircToDiscordLinks, listener_config):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.guilds = True
        intents.presences = True

        self.inQueue = inQueue
        self.outQueue = outQueue
        self.PuppetQueue = PuppetQueue
        self.ircToDiscordLinks = ircToDiscordLinks
        self.listener_config = listener_config

        super().__init__(intents=intents, chunk_guilds_at_startup=True)

    async def on_ready(self):
        logging.info(f'We have logged in as {self.user}')
        self.discordChannelMapping = {}
        for channel in self.ircToDiscordLinks:
            self.discordChannelMapping[channel] = self.get_channel(self.ircToDiscordLinks[channel]) or await self.fetch_channel(self.ircToDiscordLinks[channel])

        #asyncio.create_task(self.process_queue())
        self.loop.create_task(self.process_queue())
        self.ready = True

    def irc_safe_nickname(self, nickname: str) -> str:
        allowed_special = r"\[\]\\`_^{|}"
        nickname = nickname.strip()

        first_char = nickname[0]
        if not re.match(r"[A-Za-z" + allowed_special + "]", first_char):
            nickname = "_" + nickname[1:]

        valid_nick = re.sub(r"[^A-Za-z0-9" + allowed_special + "]", "", nickname)
        return valid_nick

    async def generate_irc_nickname(self, user):
        username = self.irc_safe_nickname(user.name)
        display_name = self.irc_safe_nickname(user.display_name)

        #still too big? shorten the username too (sheesh)
        if len(display_name) + len(username) + 6 > self.max_puppet_username:
            remove_len = (len(display_name) + len(username) + 6) - self.max_puppet_username
            username = username[:len(username)-remove_len]

        if len(display_name) + len(username) + 6 > self.max_puppet_username:
            # +5, two for [] and 3 for prefix
            # TODO: Make this dynamic
            remove_len = (len(display_name) + len(username) + 6) - self.max_puppet_username
            display_name = display_name[:len(display_name)-remove_len]

        return "{display_name}[{username}]".format(display_name=display_name, username=username)
            
    async def activate_puppet(self, user):
        if not self.ready:
            logging.warn("Discord not ready yet")
        channels =  await self.accessible_channels(user.id)
        await self.send_irc_command(user, 'active', channels)

        self.active_puppets.append(user.id)

        await self.compile_mention_lookup_re(user)
        logging.info(f"{user.display_name} is now active! (status: {user.status})")

    async def compile_mention_lookup_re(self, user: discord.Member = None):
        if user:
            irc_name = await self.generate_irc_nickname(user)
            self.mention_lookup[irc_name + self.listener_config['puppet_suffix']] = user
        self.mention_lookup_re = re.compile(r'\b(' + '|'.join(map(re.escape, self.mention_lookup.keys())) + r')\b')

    async def on_member_update(self, before: discord.Member, after: discord.Member):

        # Check for displayname Change
        if before.display_name != after.display_name:
            self.active_puppets.remove(before.id)
            self.active_puppets.append(after.id)
            await self.compile_mention_lookup_re(after)
            await self.send_irc_command(after, 'nick', None)
            logging.info(f"{before.name} changed display name from '{before.display_name}' to '{after.display_name}'")

        # Check for role change:
        before_roles = set(before.roles)
        after_roles = set(after.roles)
        if before_roles != after_roles:
            channels =  await self.accessible_channels(after.id)
            await self.send_irc_command(after, 'join_part', channels)

    async def on_presence_update(self, before, after):
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
                    logging.info(f"{after.display_name} is now offline! (status: {after.status})")

    async def send_irc_command(self, user, command, data=None, channel=None):
        logging.info('adding cmd to queue from discord: ' + command)
        self.PuppetQueue.put({
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
        if member.id in self.active_puppets:
            # Update lookup table
            self.active_puppets.remove(member.id)
            del self.mention_lookup[member.irc_nick + self.listener_config['puppet_suffix']]
            await self.compile_mention_lookup_re()

            await self.send_irc_command(member, 'die')
            logging.info(f"{member.display_name} has left!")

    async def process_queue(self):
        while True:
        # Periodically check the queue and send messages
            try:
                msg = self.inQueue.get(timeout=0.5)
                channel = None

                if msg['channel'] in self.discordChannelMapping:
                    channel = self.discordChannelMapping[msg['channel']]

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
                    if webhook == None:
                        logging.debug("Creating new webhook")
                        webhook = await channel.create_webhook(name='CatPuppetBridge')

                    # detect mentions
                    processed_message = msg['content']
                    if self.mention_lookup_re:
                        processed_message = self.mention_lookup_re.sub(lambda match: self.mention_lookup[match.group(0)].mention, msg['content'])
                    # Detect Avatar
                    avatar = await self.find_avatar(msg['author'])
                    if avatar is None:
                        avatar = 'https://robohash.org/' + msg['author'] + '?set=set4'
                    await webhook.send(processed_message, username=msg['author'], avatar_url=avatar)
            except queue.Empty:
                pass
            await asyncio.sleep(0.01)

    async def find_avatar(self, user):
        await self.guilds[0].chunk()
        members = self.guilds[0].members
        for member in members:
            if user == member.display_name:
                if member.avatar:
                    return member.avatar.url
        return None

    async def replace_customemotes(self, message):
        new_message = re.sub(r"<:([^:]+):\d+>", r":\1:", message)
        return new_message

    async def replace_channels(self, message):
        mention_pattern = r'<#!?(\d+)>'
        new_message = ""
        last_end = 0

        for match in re.finditer(mention_pattern, message):
            channel_id = int(match.group(1))
            new_message += message[last_end:match.start()]
            try:
                channel = self.guilds[0].get_channel(channel_id) or await self.guilds[0].fetch_channel(channel_id)
                new_message += '#' + channel.name
            except Exception as e:
                logging.error('failed to find channel '+str(channel_id))
                logging.error(e)
                new_message += match.group(0)  # fallback: keep original mention
            last_end = match.end()

        new_message += message[last_end:]  # append rest of string
        return new_message


    async def replace_mentions(self, message):
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
            except Exception as e:
                logging.error('failed to find user '+str(user_id))
                logging.error(e)
                new_message += match.group(0)  # fallback: keep original mention
            last_end = match.end()

        new_message += message[last_end:]  # append rest of string
        return new_message

    async def accessible_channels(self, user_id: int):
        member = self.guilds[0].get_member(user_id) or await self.guilds[0].fetch_member(user_id)

        if not member:
            return []

        accessible = []

        for channel in self.discordChannelMapping:
            if isinstance(self.discordChannelMapping[channel], discord.abc.GuildChannel):
                perms = self.discordChannelMapping[channel].permissions_for(member)
                if perms.view_channel:
                    accessible.append(self.discordChannelMapping[channel].id)

        return accessible

    async def on_message(self, message):
        # Make sure we are ready first
        if not self.ready:
            return
        # Don't repeat messages
        if message.author.bot and message.webhook_id is not None:
            return

        if not self.active_puppets or message.author.id not in self.active_puppets:
            await self.activate_puppet(message.author)

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
                    reply_author = await self.generate_irc_nickname(replied_to.author)
                    template = 'replied to {author} "{message}...": {content}'
                    content = template.format(author=reply_author,
                                     message=replied_to.content[:20],
                                     content=content)
                except discord.NotFound:
                    logging.info(f"Reply not found to message {contnet}".format(content=message.content))

            content = await self.replace_mentions(content)
            content = await self.replace_customemotes(content)
            content = await self.replace_channels(content)

        if attach:
            data = {
                'nick': self.irc_safe_nickname(message.author.display_name),
                'display_name': message.author.display_name,
                'irc_nick': await self.generate_irc_nickname(message.author),
                'name': message.author.name,
                'id': message.author.id,
                'channel': message.channel.id,
                'command': 'send',
                'data': attach,
                'timestamp': time.time()
            }
            self.PuppetQueue.put(data)
        if content:
            data = {
                'nick': self.irc_safe_nickname(message.author.display_name),
                'display_name': message.author.display_name,
                'irc_nick': await self.generate_irc_nickname(message.author),
                'name': message.author.name,
                'id': message.author.id,
                'channel': message.channel.id,
                'command': 'send',
                'data': content,
                'timestamp': time.time()
            }
            self.PuppetQueue.put(data)
