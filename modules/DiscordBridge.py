import discord
import asyncio


class DiscordBot(discord.Client):
    inQueue = None
    outQueue = None
    ircToDiscordLinks = None
    discordChannelMapping = None

    def __init__(self, inQueue, outQueue, ircToDiscordLinks):
        intents = discord.Intents.default()
        intents.message_content = True
        self.inQueue = inQueue
        self.outQueue = outQueue
        self.ircToDiscordLinks = ircToDiscordLinks

        super().__init__(intents=intents)

    async def on_ready(self):
        print(f'We have logged in as {self.user}')
        self.discordChannelMapping = {}
        for channel in self.ircToDiscordLinks:
            self.discordChannelMapping[channel] = await self.fetch_channel(self.ircToDiscordLinks[channel])
        print(self.discordChannelMapping)

        asyncio.create_task(self.process_queue())

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
                    await webhook.send(msg['content'], username=msg['author'], avatar_url='https://robohash.org/' + msg['author'] + '?set=set4')

            await asyncio.sleep(1)  # Check the queue every 1 second

    async def on_message(self, message):
        if message.author == self.user:
            return

        if message.content:
            data = {
                'author': message.author,
                'channel': message.channel.id,
                'content': message.content
            }
            self.outQueue.put(data)
