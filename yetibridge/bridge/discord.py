import logging
import re
import threading
import time
from asyncio import run_coroutine_threadsafe, get_event_loop_policy, \
                    new_event_loop, sleep

from aiohttp import ClientError
from discord import Client, Status, HTTPException, GatewayNotFound
from discord.utils import get
from websockets import InvalidHandshake, WebSocketProtocolError

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

        self.loop = loop = new_event_loop()
        self.bridge_bot = DiscordBridgeBot(self.config, self, id(self), loop)

    def on_register(self):
        self.thread = threading.Thread(target=self.run)
        self.thread.start()

        for name in self.config['channels']:
            self.send_event(self, Target.Manager, 'channel_join', name)

    def on_channel_add(self, channel):
        run_coroutine_threadsafe(self.bridge_bot.add_channel(channel),
                                 self.bridge_bot.loop).result()

    def on_channel_remove(self, channel):
        run_coroutine_threadsafe(self.bridge_bot.remove_channel(channel),
                                 self.bridge_bot.loop).result()

    def decode_mentions(self, content, channel_id):
        # TODO: Avoid using private member
        users = self.channels[channel_id]._users

        def replace(match):
            user_id = int(match.group(1))
            if user_id in self.users:
                return '<@{}>'.format(self.users[user_id].discord_id)
            elif user_id in users:
                return '@{}'.format(users[user_id].name)
            else:
                return match.group()

        return re.sub(r'<\[@([0-9]+)\]>', replace, content)

    def ev_message(self, event, content):
        if event.source_id in self.users:
            return

        name = self.get_user(event.source_id).name
        content = '<{}> {}'.format(name, content)

        if event.target_id in self.channels:
            content = self.decode_mentions(content, event.target_id)
            self.bridge_bot.message(self.channels[event.target_id].name,
                                    content)

    def ev_action(self, event, content):
        if event.source_id in self.users:
            return

        name = self.get_user(event.source_id).name
        content = '* {} {}'.format(name, content)

        if event.target_id in self.channels:
            content = self.decode_mentions(content, event.target_id)
            self.bridge_bot.message(self.channels[event.target_id].name,
                                    content)

    def ev_shutdown(self, event):
        if self.loop.is_running() and self.bridge_bot._is_ready.is_set():
            run_coroutine_threadsafe(self.bridge_bot.close(),
                                     self.loop).result()

        self.detach()

    def on_terminate(self):
        if self.loop.is_running() and self.bridge_bot._is_ready.is_set():
            run_coroutine_threadsafe(self.bridge_bot.close(),
                                     self.loop).result()

    def run(self):
        policy = get_event_loop_policy()
        policy.set_event_loop(self.loop)

        while True:
            try:
                task = self.bridge_bot.login(self.config['user'],
                                             self.config['password'])
                self.loop.run_until_complete(task)

            except (HTTPException, ClientError):
                logging.exception("Failed to log in to Discord")
                self.loop.run_until_complete(sleep(10))

            except BaseException as e:
                self.send_event(self, Target.Manager, 'exception', e)
                return

            else:
                break

        while not self.bridge_bot.is_closed:
            try:
                self.loop.run_until_complete(self.bridge_bot.sane_connect())

            except (HTTPException, ClientError, GatewayNotFound,
                    InvalidHandshake, WebSocketProtocolError):
                logging.exception("Lost connection with Discord")
                self.loop.run_until_complete(sleep(10))

            except BaseException as e:
                self.send_event(self, Target.Manager, 'exception', e)
                return

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

    def translate_mentions(self, content, mentions):
        def replace(match):
            discord_id = match.group(1)
            if discord_id in self.user_map:
                return '<[@{}]>'.format(self.user_map[discord_id])
            else:
                user = get(mentions, id=discord_id)
                if user:
                    return '@{}'.format(user.name)
                else:
                    return match.group()

        return re.sub(r'<@([0-9]+)>', replace, content)

    def discord_channel_message(self, channel, discord_id, content, mentions):
        with self.user_lock:
            if discord_id in self.user_map:
                user_id = self.user_map[discord_id]
                content = self.translate_mentions(content, mentions)
                self.send_event(user_id, channel.id, 'message', content)

    def discord_channel_action(self, channel, discord_id, content, mentions):
        with self.user_lock:
            if discord_id in self.user_map:
                user_id = self.user_map[discord_id]
                content = self.translate_mentions(content[1:-1], mentions)
                self.send_event(user_id, channel.id, 'action', content)

    def discord_private_message(self, user_id, discord_id, content, mentions):
        with self.user_lock:
            if discord_id in self.user_map:
                content = self.translate_mentions(content, mentions)
                self.send_event(self.user_map[discord_id], user_id, 'message',
                                content)

    def discord_private_action(self, user_id, discord_id, content, mentions):
        with self.user_lock:
            if discord_id in self.user_map:
                content = self.translate_mentions(content[1:-1], mentions)
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
    def __init__(self, config, bridge, user_id, loop):
        Client.__init__(self, loop=loop)

        self.config = config
        self.bridge = bridge
        self.user_id = user_id
        self.joined_channels = {}

    async def sane_connect(self):
        self.gateway = await self._get_gateway()
        await self._make_websocket()

        while not self.is_closed:
            msg = await self.ws.recv()
            if msg is None:
                if self.ws.close_code == 1012:
                    await self.redirect_websocket(self.gateway)
                    continue
                else:
                    # Connection was dropped, break out
                    break

            await self.received_message(msg)

    def action(self, target_id, content):
        target_id = self.config['channels'][target_id]
        content = '_{}_'.format(content) # Yes, this is what /me does.
        self.loop.call_soon_threadsafe(self.do_msg, target_id, content)

    def message(self, target_id, content):
        target_id = self.config['channels'][target_id]
        self.loop.call_soon_threadsafe(self.do_msg, target_id, content)

    def do_msg(self, target_id, content):
        channel = self.get_channel(target_id)
        if channel is not None:
            task = self.loop.create_task(self.send_message(channel, content))
            task.add_done_callback(lambda task: self.msg_done(task, content))

        else:
            print("unkown target", target_id)

    def msg_done(self, task, content):
        try:
            task.result()
        except (HTTPException, ClientError):
            logging.exception('Error sending "{}"'.format(content))
        except BaseException as e:
            self.bridge.send_event(self, Target.Manager, 'exception', e)

    @staticmethod
    def is_action(message):
        content = message.content
        return (len(content) > 2 and content[0] == content[-1] == '_'
                and content[-2] != '_' and content[1] != '_')

    async def on_message(self, message):
        if message.channel.is_private:
            args = (self.user_id, message.author.id,
                    message.content, message.mentions)
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
            content, mentions = message.content, message.mentions

            if self.is_action(message):
                self.bridge.discord_channel_action(*args, content, mentions)
            elif message.content:
                self.bridge.discord_channel_message(*args, content, mentions)

            if message.attachments:
                urls = ', '.join((a['url'] for a in message.attachments))
                self.bridge.discord_channel_message(*args, urls, mentions)

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
