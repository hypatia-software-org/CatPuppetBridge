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
from datetime import datetime, timezone
import discord

class DiscordFilters():
    """ Filter messages from and to discord for IRC readablity """
    discord_timeformat_re = re.compile(r"<t:(\d+)(?::([tTdDfFR]))?>")
    mention_lookup = {}
    mention_lookup_re = None
    bot = None

    def __init__(self, bot):
        self.bot = bot

    def format_relative_time(self, dt: datetime) -> str:
        """ Convert time to 'relative' time eg/ 1 year ago, 5 days ago"""
        now = datetime.now(timezone.utc)
        diff = dt - now
        seconds = int(diff.total_seconds())
        past = seconds < 0
        seconds = abs(seconds)
        time_unit_map = [
            ("year", 31536000),
            ("month", 2592000),
            ("day", 86400),
            ("hour", 3600),
            ("minute", 60),
        ]

        for unit, length in time_unit_map:
            if seconds >= length:
                value = seconds // length
                s = "" if value == 1 else "s"
                return f"{value} {unit}{s} ago" if past else f"in {value} {unit}{s}"

        return f"{seconds} second{'s' if seconds != 1 else ''} ago" \
            if past else f"in {seconds} seconds"

    def replace_discord_timeformat(self, match):
        """ Process regex for discord time formats """

        unix_time = int(match.group(1))
        fmt = match.group(2) or "f"
        diff = datetime.fromtimestamp(unix_time, tz=timezone.utc)

        discord_time_format_map = {
            "t": "%H:%M",
            "T": "%H:%M:%S",
            "d": "%m/%d/%Y",
            "D": "%B %d, %Y",
            "f": "%B %d, %Y at %H:%M",
            "F": "%A, %B %d, %Y at %H:%M",
        }

        output = ''
        if fmt == "R":
            output = self.format_relative_time(diff)
        else:
            output = diff.strftime(discord_time_format_map.get(fmt, "%Y-%m-%d %H:%M:%S UTC"))

        return output

    def replace_time(self, msg: str):
        """ Replace discord time formats eg/ <t:304343:F> with human readable time """
        return self.discord_timeformat_re.sub(self.replace_discord_timeformat, msg)

    async def replace_customemotes(self, message):
        """Replace custom emotes with :emote_id:"""
        return re.sub(r"<[:alpha:]?:([^:]+):\d+>", r":\1:", message)

    async def replace_channels(self, message):
        """Replace channel names with plaintext"""
        channel_pattern = r'<#!?(\d+)>'
        new_message = ""
        last_end = 0

        for match in re.finditer(channel_pattern, message):
            channel_id = int(match.group(1))
            new_message += message[last_end:match.start()]
            try:
                channel = self.bot.guilds[0].get_channel(channel_id) or \
                    await self.bot.guilds[0].fetch_channel(channel_id)
                new_message += '#' + channel.name
            except discord.NotFound as e:
                logging.error('failed to find channel %i', channel_id)
                logging.error(e)
                new_message += match.group(0)
            last_end = match.end()

        new_message += message[last_end:]
        return new_message

    def lookup_mention(self, content):
        """ Lookup mentions mentions from IRC and convert to Discord mentions """
        return self.mention_lookup_re.sub(
            lambda match: self.mention_lookup[match.group(0)].mention,
            content)

    async def compile_mention_lookup_re(self, user: discord.Member = None):
        """Compile our regex for looking up mentions"""
        if user:
            irc_name = await self.bot.generate_irc_nickname(user)
            self.mention_lookup[irc_name + self.bot.listener_config['puppet_suffix']] = user
        self.mention_lookup_re = re.compile(
            r'\b(' + '|'.join(map(re.escape, self.mention_lookup.keys())) + r')\b')

    async def remove_from_mention_lookup(self, nick):
        """ Remove a mention from the lookup table, given their irc nick """
        del self.mention_lookup[nick]
        await self.compile_mention_lookup_re()

    async def replace_mentions(self, message):
        """Replace mentions with plaintext"""
        mention_pattern = r'<@!?(\d+)>'
        new_message = ""
        last_end = 0

        for match in re.finditer(mention_pattern, message):
            user_id = int(match.group(1))
            new_message += message[last_end:match.start()]
            try:
                user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)

                irc_nick = await self.bot.generate_irc_nickname(user)
                new_message += irc_nick + self.bot.listener_config['puppet_suffix']
            except discord.NotFound as e:
                logging.error('failed to find user %i', user_id)
                logging.error(e)
                new_message += match.group(0)
            last_end = match.end()

        new_message += message[last_end:]
        return new_message
