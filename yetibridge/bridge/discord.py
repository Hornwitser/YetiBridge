import threading
import time
from asyncio import run_coroutine_threadsafe, get_event_loop_policy

from discord import Client, Status
from discord.utils import get

from . import BaseBridge
from ..event import Event, Target


class DiscordBridge(BaseBridge):
    def __init__(self, config):
        BaseBridge.__init__(self, config)
        self.users = {}
        self.user_map = {}
        self.user_lock = threading.Lock()

        self.leaving_users = {}
        self.lv_thread = threading.Thread(target=self.leave_loop, daemon=True)
        self.lv_thread.start()

        ready = threading.Event()
        self.thread = threading.Thread(target=self.run, args=(ready,))
        self.thread.start()
        ready.wait()

    def on_register(self):
        self.start.set()

        for name in self.config['channels']:
            self.send_event(self, Target.Manager, 'channel_join', name)

    def on_channel_add(self, channel):
        run_coroutine_threadsafe(self.bridge_bot.add_channel(channel),
                                 self.bridge_bot.loop).result()

    def on_channel_remove(self, channel):
        run_coroutine_threadsafe(self.bridge_bot.remove_channel(channel),
                                 self.bridge_bot.loop).result()

    def ev_message(self, event, content):
        if event.source_id in self.users:
            return

        name = self.get_user(event.source_id).name
        content = '<{}> {}'.format(name, content)

        if event.target_id in self.channels:
            self.bridge_bot.message(self.channels[event.target_id].name,
                                    content)

    def ev_action(self, event, content):
        if event.source_id in self.users:
            return

        name = self.get_user(event.source_id).name
        content = '<{}> {}'.format(name, content)

        if event.target_id in self.channels:
            self.bridge_bot.action(self.channels[event.target_id].name,
                                   content)

    def ev_shutdown(self, event):
        run_coroutine_threadsafe(self.bridge_bot.close(),
                                 self.bridge_bot.loop).result()
        self.detach()

    def on_terminate(self):
        run_coroutine_threadsafe(self.bridge_bot.close(),
                                 self.bridge_bot.loop).result()

    def run(self, ready):
        policy = get_event_loop_policy()
        policy.set_event_loop(policy.new_event_loop())
        self.bridge_bot = DiscordBridgeBot(self.config, self, id(self))

        self.start = threading.Event()
        ready.set()
        self.start.wait()

        try:
            self.bridge_bot.run(self.config['user'], self.config['password'])

        except BaseException as e:
            self.send_event(self, Target.Manager, 'exception', e)

    def leave_loop(self):
        while True:
            time.sleep(15)
            with self.user_lock:
                self.check_user_timeouts()

    def check_user_timeouts(self):
        leaving = []
        for (discord_id, channel), timestamp in self.leaving_users.items():
            if timestamp+self.config['timeout'] < time.time():
                leaving.append((discord_id, channel))

        for discord_id, channel in leaving:
            del self.leaving_users[(discord_id, channel)]
            self.user_timeout(discord_id, channel)

    def user_timeout(self, discord_id, channel):
        user_id = self.user_map[discord_id]
        self.send_event(self, Target.Manager, 'user_leave',
                        channel.id, user_id)

        user_channels = self.users[user_id].channels
        user_channels.remove(channel)

        if not user_channels:
            del self.users[user_id]
            del self.user_map[discord_id]

    def discord_user_join(self, channel, discord_id, name):
        with self.user_lock:
            # Discard possible pending leave for the user
            self.leaving_users.pop((discord_id, channel), None)

            if discord_id not in self.user_map:
                user = DiscordUser(discord_id, {channel})
                self.send_event(self, Target.Manager, 'user_join',
                                channel.id, id(user), name)

                self.users[id(user)] = user
                self.user_map[discord_id] = id(user)

            else:
                user = self.users[self.user_map[discord_id]]
                if channel not in user.channels:
                    self.send_event(self, Target.Manager, 'user_join',
                                    channel.id, id(user), name)

                    user.channels.add(channel)


    def discord_name_change(self, channel, discord_id, new_name):
        with self.user_lock:
            if discord_id in self.user_map:
                self.send_event(self, Target.Manager, 'user_change',
                                channel.id, self.user_map[discord_id],
                                new_name)

    def discord_user_leave(self, channel, discord_id):
        with self.user_lock:
            if discord_id in self.user_map:
                if (discord_id, channel) not in self.leaving_users:
                    self.leaving_users[(discord_id, channel)] = time.time()

    def discord_channel_message(self, channel, discord_id, content):
        with self.user_lock:
            if discord_id in self.user_map:
                user_id = self.user_map[discord_id]
                self.send_event(user_id, channel.id, 'message', content)

    def discord_channel_action(self, channel, discord_id, content):
        with self.user_lock:
            if discord_id in self.user_map:
                content = content[1:-1]
                user_id = self.user_map[discord_id]
                self.send_event(user_id, channel.id, 'action', content)

    def discord_private_message(self, user_id, discord_id, content):
        with self.user_lock:
            if discord_id in self.user_map:
                self.send_event(self.user_map[discord_id], user_id, 'message',
                                content)

    def discord_private_action(self, user_id, discord_id, content):
        with self.user_lock:
            if discord_id in self.user_map:
                content = content[1:-1]
                self.send_event(self.user_map[discord_id], user_id, 'message',
                                content)


class DiscordUser:
    def __init__(self, discord_id, channels):
        self._discord_id = discord_id
        self.channels = channels

    def __eq__(self, other):
        if isinstance(other, DiscordUser):
            return self._discord_id == other._discord_id
        elif isinstance(other, str):
            return self._discord_id == other
        else:
            return NotImplemented

    def __str__(self):
        return 'DiscordUser({!r})'.format(self._discord_id)

    @property
    def discord_id(self):
        return self._discord_id


class DiscordBot(Client):
    def __init__(self, config, bridge, user_id):
        Client.__init__(self)

        self.config = config
        self.bridge = bridge
        self.user_id = user_id
        self.joined_channels = {}

    def action(self, target_id, content):
        target_id = self.config['channels'][target_id]

        content = '*{}*'.format(content)
        run_coroutine_threadsafe(self.do_msg(target_id, content),
                                 self.loop).result()

    def message(self, target_id, content):
        target_id = self.config['channels'][target_id]

        run_coroutine_threadsafe(self.do_msg(target_id, content),
                                 self.loop).result()

    async def do_msg(self, target_id, content):
        channel = self.get_channel(target_id)
        if channel is not None:
            await self.send_message(channel, content)
            return

        print("unkown target", target_id)

    @staticmethod
    def is_action(message):
        content = message.content
        return content.startswith('*') and content.endswith('*')

    async def on_message(self, message):
        if message.channel.is_private:
            args = (self.user_id, message.author.id, message.clean_content)
            if self.is_action(message):
                self.bridge.discord_private_action(*args)
            else:
                self.bridge.discord_private_message(*args)

    async def add_channel(self, channel):
        channel_id = self.config['channels'][channel.name]
        self.joined_channels[channel_id] = channel

    async def remove_channel(self, channel):
        channel_id = self.config['channels'][channel.name]
        del self.joined_channels[channel_id]

class DiscordBridgeBot(DiscordBot):
    def _sync_member(self, channel, member, discord_channel):
        if member != self.user:
            if (discord_channel.permissions_for(member).read_messages
                    and member.status != Status.offline):
                self.bridge.discord_user_join(channel, member.id, member.name)
            else:
                self.bridge.discord_user_leave(channel, member.id)

    def _sync_channel_members(self, channel, discord_channel):
        for member in discord_channel.server.members:
            self._sync_member(channel, member, discord_channel)

    async def on_member_join(self, member):
        for channel_id, channel in self.joined_channels.items():
            discord_channel = self.get_channel(channel_id)
            if discord_channel is not None:
                self._sync_member(channel, member, discord_channel)

    async def on_member_remove(self, member):
        for channel_id, channel in self.joined_channels.items():
            self.bridge.discord_user_leave(channel, member.id)

    async def on_member_update(self, before, after):
        if after.name != before.name:
            for channel in self.joined_channels.values():
                self.bridge.discord_name_change(channel, after.id, after.name)

        for discord_channel in after.server.channels:
            if discord_channel.id in self.joined_channels:
                channel = self.joined_channels[discord_channel.id]
                self._sync_member(channel, after, discord_channel)

    async def on_ready(self):
        for channel_id, channel in self.joined_channels.items():
            discord_channel = self.get_channel(channel_id)
            if discord_channel is not None:
                self._sync_channel_members(channel, discord_channel)

    async def on_message(self, message):
        await DiscordBot.on_message(self, message)

        if message.channel.id in self.joined_channels:
            channel = self.joined_channels[message.channel.id]
            args = (channel, message.author.id)
            if message.attachments:
                urls = ', '.join((a['url'] for a in message.attachments))
                self.bridge.discord_channel_message(*args, urls)
            elif self.is_action(message):
                self.bridge.discord_channel_action(*args, message.content)
            else:
                self.bridge.discord_channel_message(*args, message.content)

    async def add_channel(self, channel):
        await DiscordBot.add_channel(self, channel)
        discord_channel_id = self.config['channels'][channel.name]

        discord_channel = self.get_channel(discord_channel_id)
        if discord_channel is not None:
            self._sync_channel_members(channel, discord_channel)

    async def remove_channel(self, channel):
        await DiscordBot.remove_channel(self, channel)
        discord_channel_id = self.config['channels'][channel.name]

        discord_channel = self.get_channel(discord_channel_id)
        if discord_channel is not None:
            for member in discord_channel.server.members:
                self.bridge.discord_user_leave(channel, member.id)
