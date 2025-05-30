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
    guild_id = None
    guild = None
    active_puppets = []
    mention_lookup = {}
    mention_lookup_re = None
    listener_config = None
    ready = False
    process_queue_thread = None
    max_puppet_username = 30

    def __init__(self, inQueue, outQueue, PuppetQueue, ircToDiscordLinks, guild_id, listener_config):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.presences = True

        self.inQueue = inQueue
        self.outQueue = outQueue
        self.PuppetQueue = PuppetQueue
        self.ircToDiscordLinks = ircToDiscordLinks
        self.guild_id = guild_id
        self.listener_config = listener_config

        super().__init__(intents=intents)

    async def on_ready(self):
        logging.info(f'We have logged in as {self.user}')
        self.discordChannelMapping = {}
        for channel in self.ircToDiscordLinks:
            self.discordChannelMapping[channel] = await self.fetch_channel(self.ircToDiscordLinks[channel])
        self.guild = await self.fetch_guild(self.guild_id)
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
        username = user.name
        display_name = user.display_name
        if len(display_name) + len(username) + 2 > self.max_puppet_username:
            # +5, two for [] and 3 for prefix
            # TODO: Make this dynamic
            remove_len = (len(display_name) + len(username) + 5) - self.max_puppet_username
            display_name = display_name[:len(display_name)-remove_len]
        #still too big? shorten the username too (sheesh)
        if len(display_name) + len(username) + 2 > self.max_puppet_username:
            remove_len = (len(display_name) + len(username) + 5) - self.max_puppet_username
            username = username[:len(username)-remove_len]
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

    async def on_member_update(before: discord.Member, after: discord.Member):
        if before.display_name != after.display_name:
            self.active_puppets.remove(before.id)
            self.active_puppets.append(after.id)
            await compile_mention_lookup_re(after)
            await self.send_irc_command(after, 'nick', None)
            logging.info(f"{before.name} changed display name from '{before.display_name}' to '{after.display_name}'")

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
                    for webhook in webhooks:
                        if webhook.name == webhook_name:
                            webhook = webhook
                            break
                    if webhook == None:
                        webhook = await channel.create_webhook(name='CatPuppetBridge')

                    # detect mentions
                    processed_message = msg['content']
                    if self.mention_lookup_re:
                        processed_message = self.mention_lookup_re.sub(lambda match: self.mention_lookup[match.group(0)].mention, msg['content'])
                    await webhook.send(processed_message, username=msg['author'], avatar_url='https://robohash.org/' + msg['author'] + '?set=set4')
            except queue.Empty:
                pass
            await asyncio.sleep(0.01)

    async def replace_mentions(self, message):
        mention_pattern = r'<@!?(\d+)>'
        new_message = ""
        last_end = 0

        for match in re.finditer(mention_pattern, message):
            user_id = int(match.group(1))
            new_message += message[last_end:match.start()]
            try:
                user = await self.fetch_user(user_id)
                new_message += self.irc_safe_nickname(user.irc_nick) + self.listener_config['puppet_suffix']
            except Exception:
                new_message += match.group(0)  # fallback: keep original mention
            last_end = match.end()

        new_message += message[last_end:]  # append rest of string
        return new_message

    async def accessible_channels(self, user_id: int):
        member = self.guild.get_member(user_id) or await self.guild.fetch_member(user_id)

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
        if message.author.bot and message.webhook_id is not None:
            return
        if message.content:
            if self.active_puppets == None:
                time.sleep(5)
            if not self.active_puppets or message.author.id not in self.active_puppets:
                await self.activate_puppet(message.author)

            content = await self.replace_mentions(message.content)
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
