import discord
import asyncio
import time
import re


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
        print(f'We have logged in as {self.user}')
        self.discordChannelMapping = {}
        for channel in self.ircToDiscordLinks:
            self.discordChannelMapping[channel] = await self.fetch_channel(self.ircToDiscordLinks[channel])
        self.guild = await self.fetch_guild(self.guild_id)
        asyncio.create_task(self.process_queue())
        self.ready = True

    def irc_safe_nickname(self, nickname: str) -> str:
        allowed_special = r"\[\]\\`_^{|}"
        nickname = nickname.strip()

        first_char = nickname[0]
        if not re.match(r"[A-Za-z" + allowed_special + "]", first_char):
            nickname = "_" + nickname[1:]

        valid_nick = re.sub(r"[^A-Za-z0-9" + allowed_special + "]", "", nickname)
        return valid_nick

    async def activate_puppet(self, user):
        if not self.ready:
            print("Not ready")
        channels =  await self.accessible_channels(user.id)
        self.PuppetQueue.put({
            'nick': self.irc_safe_nickname(user.display_name),
            'display_name': user.display_name,
            'name': user.name,
            'id': user.id,
            'command': 'active',
            'data': channels,
            'timestamp': time.time()
        })
        self.active_puppets.append(user.id)
        self.mention_lookup[user.display_name + self.listener_config['puppet_suffix']] = user
        self.mention_lookup_re = re.compile(r'\b(' + '|'.join(map(re.escape, self.mention_lookup.keys())) + r')\b')
        print(f"{user.display_name} is now active! (status: {user.status})")
    
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
                self.PuppetQueue.put({
                    'nick': self.irc_safe_nickname(after.display_name),
                    'display_name': after.display_name,
                    'name': after.name,
                    'id': after.id,
                    'command': 'unafk',
                    'data': None,
                    'timestamp': time.time()
                })
            else:
                await self.activate_puppet(after)
        if previously_active and now_inactive:
            if after.id in self.active_puppets:
                self.PuppetQueue.put({
                    'nick': self.irc_safe_nickname(after.display_name),
                    'display_name': after.display_name,
                    'name': after.name,
                    'id': after.id,
                    'command': 'afk',
                    'data': None,
                    'timestamp': time.time()
                })
                print(f"{after.display_name} is now offline! (status: {after.status})")

    async def on_member_remove(member):
            if after.id in self.active_puppets:
                self.PuppetQueue.put({
                    'nick': self.irc_safe_nickname(member.display_name),
                    'display_name': member.display_name,
                    'name': member.name,
                    'id': member.id,
                    'command': 'die',
                    'data': None,
                    'timestamp': time.time()
                })
                print(f"{member.display_name} has left!")

    async def process_queue(self):
        # Periodically check the queue and send messages
        while True:
            if not self.inQueue.empty():
                msg = self.inQueue.get()
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

            await asyncio.sleep(1)  # Check the queue every 1 second

    async def replace_mentions(self, message):
        mention_pattern = r'<@!?(\d+)>'
        new_message = ""
        last_end = 0

        for match in re.finditer(mention_pattern, message):
            user_id = int(match.group(1))
            new_message += message[last_end:match.start()]
            try:
                user = await self.fetch_user(user_id)
                new_message += self.irc_safe_nickname(user.display_name) + self.listener_config['puppet_suffix']
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
            print('adding message')
            content = await self.replace_mentions(message.content)
            data = {
                'nick': self.irc_safe_nickname(message.author.display_name),
                'display_name': message.author.display_name,
                'name': message.author.name,
                'id': message.author.id,
                'channel': message.channel.id,
                'command': 'send',
                'data': content,
                'timestamp': time.time()
            }
            self.PuppetQueue.put(data)
