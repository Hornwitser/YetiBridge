import re
import threading
import logging

from unidecode import unidecode

from irc.bot import SingleServerIRCBot
from irc.buffer import LenientDecodingLineBuffer
from irc.client import ServerConnection
from irc.strings import IRCFoldedCase
from irc.dict import IRCDict

from . import BaseBridge, User
from ..utf8wrap import Utf8Wrapper
from ..event import Event, Target


class IRCBridge(BaseBridge):
    def __init__(self, config):
        BaseBridge.__init__(self, config)
        nick, name = config['nick'], config['name']
        self.bridge_bot = IRCBridgeBot(nick, name, self.config, self, id(self))
        self.user_bots = {}
        self.user_bots_lock = threading.Lock()
        self.connect_queue = set()
        self.connecting = set()
        self.users = {}
        self.user_map = IRCDict()
        self.thread = threading.Thread(target=self.run)
        self.terminated = False

    def on_register(self):
        self.bridge_bot._connect()
        self.thread.start()

        for name in self.config['channels']:
            self.send_event(self, Target.Manager, 'channel_join', name)

    def add_bot(self, user):
        nick = self.user_nick(user.name)
        bot = IRCUserBot(nick, user.name, self.config, self, user.id)

        with self.user_bots_lock:
            self.user_bots[user.id] = bot
            self.connect_queue.add(user.id)

    def user_add(self, channel, user):
        if user.id not in self.users:
            if user.id not in self.user_bots:
                self.add_bot(user)

            self.user_bots[user.id].add_channel(channel)

    def on_channel_add(self, channel):
        self.bridge_bot.add_channel(channel)

        for user in channel.users:
            self.user_add(self, channel, user)

    def on_channel_remove(self, channel):
        self.bridge_bot.remove_channel(channel)

    def on_user_add(self, channel, user):
        self.user_add(channel, user)

    def on_user_update(self, channel, before, after):
        if before.id in self.user_bots:
            before_nick = self.user_nick(before.name)
            after_nick = self.user_nick(after.name)
            if after_nick != before_nick:
                self.user_bots[before.id].set_nick(after_nick)

    def on_user_remove(self, channel, user):
        if user.id in self.user_bots:
            bot = self.user_bots[user.id]
            bot.remove_channel(channel)

            if not bot.joined_channels:
                with self.user_bots_lock:
                    del self.user_bots[user.id]
                    self.connecting.discard(user.id)
                    bot.disconnect()

    def decode_mentions(self, content):
        def replace(match):
            user_id = int(match.group(1))
            if user_id in self.users:
                return '@{}'.format(self.users[user_id].nick)
            elif user_id in self.user_bots:
                nick = self.user_bots[user_id].connection.get_nickname()
                return '@{}'.format(nick)
            else:
                return match.group()

        return re.sub(r'<\[@([0-9]+)\]>', replace, content)

    def ev_message(self, event, content):
        if event.source_id in self.users:
            return

        if event.source_id in self.user_bots:
            bot = self.user_bots[event.source_id]
        else:
            name = self.name(event.source_id)
            content = '{} {}'.format(name, content)
            bot = self.bridge_bot

        content = self.decode_mentions(content)

        if event.target_id in self.channels:
            bot.message(self.channels[event.target_id].name, content)
        elif event.target_id in self.users:
            bot.message(self.users[event.target_id].nick, content)
        elif event.target_id == Target.AllChannels:
            for channel in self.channels.values():
                bot.message(channel.name, content)


    def ev_action(self, event, content):
        if event.source_id in self.users:
            return

        if event.source_id in self.user_bots:
            method = self.user_bots[event.source_id].action
        else:
            try:
                name = self.get_user(event.source_id).name
            except KeyError:
                name = self.name(event.source_id)

            content = '* {} {}'.format(name, content)
            method = self.bridge_bot.message

        content = self.decode_mentions(content)

        if event.target_id in self.channels:
            method(self.channels[event.target_id].name, content)
        elif event.target_id in self.users:
            method(self.users[event.target_id].nick, content)
        elif event.target_id == Target.AllChannels:
            for channel in self.channels.values():
                method(channel.name, content)

    def ev_shutdown(self, event):
        for bot in self.bots:
            bot.disconnect("Bridge shutting down")
        self.terminated = True
        self.detach()

    def on_terminate(self):
        self.terminated = True

    def run(self):
        try:
            while not self.terminated:
                self.bridge_bot.reactor.process_once(0.2)

                with self.user_bots_lock:
                    if len(self.connecting) < 3 and self.connect_queue:
                        user_id = self.connect_queue.pop()
                        try:
                            self.user_bots[user_id].sane_connect()
                        except KeyError:
                            pass # User bot has been removed
                        else:
                            self.connecting.add(user_id)

                    for bot in self.user_bots.values():
                        bot.reactor.process_once()

        except BaseException as e:
            self.send_event(self, Target.Manager, 'exception', e)

    def user_nick(self, name):
        name = unidecode(name)
        if not name:
            name = 'unicode_garbage'

        nick = self.config['user_prefix']
        for c in name:
            if c in self.config['valid_chars']:
                nick += c
            else:
                nick += '_'

        if nick[0] in '0123456789-':
            nick = '_' + nick

        return nick[:self.config['user_length']]

    @property
    def bots(self):
        bot_iterators = ((self.bridge_bot,), self.user_bots.values())
        return (b for i in bot_iterators for b in i)

    @property
    def own_nicknames(self):
        active_bots = (b for b in self.bots if b.connection.is_connected())
        nicknames = map(lambda b: b.connection.get_nickname(), active_bots)
        return map(IRCFoldedCase, nicknames)

    def irc_ready(self, user_id):
        self.connecting.discard(user_id)

    def irc_user_join(self, channel, nick):
        if nick in self.own_nicknames:
            return

        if nick not in self.user_map:
            user = IRCUser(nick, {channel})
            self.send_event(self, Target.Manager, 'user_join',
                            channel.id, id(user), nick)

            self.users[id(user)] = user
            self.user_map[nick] = id(user)

        else:
            user = self.users[self.user_map[nick]]
            if channel not in user.channels:
                self.send_event(self, Target.Manager, 'user_join',
                                channel.id, id(user), nick)

                user.channels.add(channel)


    def irc_nick_change(self, old_nick, new_nick):
        if old_nick in self.user_map:
            user_id = self.user_map[old_nick]
            user = self.users[user_id]
            for channel in self.channels.values():
                if user in channel.users:
                    self.send_event(self, Target.Manager, 'user_change',
                                    channel.id, user_id, new_nick)

            user._nick = new_nick
            del self.user_map[old_nick]
            self.user_map[new_nick] = user_id

    def irc_user_leave(self, channel, nick):
        if nick in self.user_map:
            user_id = self.user_map[nick]
            user = self.users[user_id]

            if channel not in user.channels:
                return

            self.send_event(self, Target.Manager, 'user_leave',
                            channel.id, user_id)

            user.channels.remove(channel)

            if not user.channels:
                del self.users[user_id]
                del self.user_map[nick]

    def nick_map(self):
        nick_map = IRCDict({b.connection.get_nickname(): i
                       for i, b in self.user_bots.items()
                           if b.connection.is_connected()})

        nick_map.update(self.user_map)
        return nick_map

    def convert_mentions(self, message):
        nick_map = self.nick_map()

        def replace(match):
            nick = match.group(1)
            for i in range(len(nick), 0, -1):
                part = nick[:i]
                if part in nick_map:
                    return '<[@{}]>{}'.format(nick_map[part], nick[i:])
            else:
                return match.group()

        return re.sub(r'@([^ @]+)', replace, message)

    def irc_channel_message(self, channel, nick, message):
        if nick in self.user_map:
            user_id = self.user_map[nick]
            message = self.convert_mentions(message)
            self.send_event(user_id, channel.id, 'message', message)

    def irc_channel_action(self, channel, nick, message):
        if nick in self.user_map:
            user_id = self.user_map[nick]
            message = self.convert_mentions(message)
            self.send_event(user_id, channel.id, 'action', message)

    def irc_private_message(self, user_id, nick, message):
        message = self.convert_mentions(message)
        self.send_event(self.user_map[nick], user_id, 'message', message)

    def irc_private_action(self, user_id, nick, message):
        message = self.convert_mentions(message)
        self.send_event(self.user_map[nick], user_id, 'action', message)


class IRCUser:
    def __init__(self, nick, channels):
        self._nick = IRCFoldedCase(nick)
        self.channels = channels

    def __eq__(self, other):
        if isinstance(other, IRCUser):
            return self._nick == other._nick
        elif isinstance(other, User):
            return id(self) == other.id
        elif isinstance(other, str):
            return self._nick == other
        else:
            return NotImplemented

    def __str__(self):
        return 'IRCUser({!r})'.format(self._nick)

    @property
    def nick(self):
        return self._nick


# Prevent decoding errors from IRC clients that don't use UTF-8
ServerConnection.buffer_class = LenientDecodingLineBuffer

class IRCBot(SingleServerIRCBot):
    def __init__(self, nick, name, config, bridge, user_id):
        SingleServerIRCBot.__init__(self, [config['server']], nick, name)

        self.config = config
        self.bridge = bridge
        self.user_id = user_id
        self.joined_channels = IRCDict()
        self.distinguisher = 1

        self.wrapper = Utf8Wrapper(width=400)

    def die(self):
        raise RuntimeError("This function would have called sys.exit()")

    def sane_connect(self):
        server = self.server_list[0]
        self.connect(server.host, server.port, self._nickname,
                     server.password, ircname=self._realname,
                     **self._SingleServerIRCBot__connect_params)

    def _part(self, content):
        lines = content.replace('\r', '\n').split('\n')

        # NOTE: Lines containing just spaces are stripped out by the
        #       text wrapper.

        for line in lines:
            for part in self.wrapper.wrap(line):
                yield part

    def message(self, target, content):
        if target in self.config['channels']:
            target = self.config['channels'][target]

        if self.connection.is_connected():
            for part in self._part(content):
                self.connection.privmsg(target, part)
        else:
            print("Dropping message for", self._nickname)

    def action(self, target, content):
        if target in self.config['channels']:
            target = self.config['channels'][target]

        if self.connection.is_connected():
            for part in self._part(content):
                self.connection.action(target, part)
        else:
            print("Dropping action for", self._nickname)

    def on_nicknameinuse(self, connection, event):
        print('Error:', connection.get_nickname(), 'in use')

        self.distinguisher += 1
        number = '_{}'.format(self.distinguisher)

        nick = connection.get_nickname()
        nick = ''.join([nick[:self.config['user_length']-len(number)], number])

        connection.nick(nick)

    def on_erroneusnickname(self, connection, event):
        print('Error:', event.target, event.arguments[0])

    def on_welcome(self, connection, event):
        self.bridge.irc_ready(self.user_id)
        for irc_channel in self.joined_channels:
            connection.join(irc_channel)

    def on_privmsg(self, connection, event):
        self.bridge.irc_private_message(self.user_id, event.source.nick,
                                        event.arguments[0])

    def on_action(self, connection, event):
        if event.target[0] != '#':
            self.bridge.irc_private_action(self.user_id, event.source.nick,
                                           event.arguments[0])

    def set_nick(self, nick):
        self._nickname, self.distinguisher = nick, 1

        if self.connection.is_connected():
            self.connection.nick(nick)

    def add_channel(self, channel):
        irc_channel = self.config['channels'][channel.name]
        self.joined_channels[irc_channel] = channel

        if self.connection.is_connected():
            self.connection.join(irc_channel)

    def remove_channel(self, channel):
        irc_channel = self.config['channels'][channel.name]
        if self.connection.is_connected():
            self.connection.part(irc_channel)

        del self.joined_channels[irc_channel]

class IRCBridgeBot(IRCBot):
    def on_pubmsg(self, connection, event):
        channel, nick = self.joined_channels[event.target], event.source.nick
        self.bridge.irc_channel_message(channel, nick, event.arguments[0])

    def on_action(self, connection, event):
        IRCBot.on_action(self, connection, event)
        if event.target in self.joined_channels:
            channel = self.joined_channels[event.target]
            nick = event.source.nick
            self.bridge.irc_channel_action(channel, nick, event.arguments[0])

    def on_nick(self, connection, event):
        before = event.source.nick
        after = event.target

        self.bridge.irc_nick_change(before, after)

    def on_namreply(self, connection, event):
        channel = self.joined_channels[event.arguments[1]]
        users = event.arguments[2].strip(' ').split(' ')
        for nick in users:
            if nick[0] in '~@&+':
                nick = nick[1:]
            self.bridge.irc_user_join(channel, nick)

    def on_join(self, connection, event):
        channel = self.joined_channels[event.target]
        self.bridge.irc_user_join(channel, event.source.nick)

    def on_kick(self, connection, event):
        channel = self.joined_channels[event.target]
        self.bridge.irc_user_leave(channel, event.source.nick)

        if event.source.nick == connection.get_nickname():
            # Bot was kiced from the channel
            logging.error("IRCBot kicked from %s!", ch)
            # TODO handle this better

    def on_part(self, connection, event):
        channel = self.joined_channels[event.target]
        self.bridge.irc_user_leave(channel, event.source.nick)

        if event.source.nick == connection.get_nickname():
            # Bot was parted from the channel
            logging.error("IRCBot parted from %s!", ch)
            # TODO handle this better

    def on_quit(self, connection, event):
        for channel in self.joined_channels.values():
            self.bridge.irc_user_leave(channel, event.source.nick)


class IRCUserBot(IRCBot):
    pass
