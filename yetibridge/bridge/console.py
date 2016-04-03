import threading

from . import BaseBridge
from ..event import Target
from ..cmdsys import split, command, is_command


class ConsoleBridge(BaseBridge):
    def __init__(self, config):
        BaseBridge.__init__(self, config)
        self._thread = threading.Thread(target=self.run, daemon=True)

    def on_register(self):
        self._thread.start()

        for channel_name in self.config['channels']:
            self.join(channel_name)

    def on_channel_add(self, channel):
        print('joined #{}'.format(channel.name))

    def on_channel_remove(self, channel):
        print('left #{}'.format(channel.name))

    def on_user_add(self, channel, user):
        print('#{}: {} joined'.format(channel.name, user.name))

    def on_user_update(self, channel, before, after):
        print('#{}: {} -> {}'.format(channel.name, before.name, after.name))

    def on_user_remove(self, channel, user):
        print('#{}: {} left'.format(channel.name, user.name))

    def run(self):
        while True:
            string = input()
            try:
                words = split(string)
            except ValueError as e:
                print('error: {}'.format(e))
            else:
                if not len(words):
                    continue

                func = getattr(self, words[0], None)
                if is_command(func):
                    try:
                        func(*words[1:])
                    except Exception as e:
                        print("{}: {}".format(e.__class__.__name__, e))
                else:
                    print("error: '{}' unknown command".format(words[0]))

    @command
    def bridge(self, *words):
        self.send_event(self, Target.Manager, 'command', words, 'console')

    @command
    def manager(self, *words):
        self.bridge(*(['manager']+list(words)))

    @command
    def shutdown(self):
        self.manager('shutdown')

    @command
    def debug(self, *code):
        try:
            result = eval(' '.join(code))
        except Exception as e:
            print("{}: {}".format(e.__class__.__name__, e))
        else:
            print(repr(result))

    @command
    def set(self, prop):
        if prop in ('eavesdrop', 'ev'):
            self._manager._eavesdropper = self.on_eavesdrop
        elif prop in ('noeavesdrop', 'noev'):
            self._manager._eavesdropper = None
        else:
            print("error: unknown property '{}'".format(prop))

    @command
    def join(self, channel_name):
        self.send_event(self, Target.Manager, 'channel_join', channel_name)

    @command
    def leave(self, channel_name):
        self.send_event(self, Target.Manager, 'channel_leave', channel_name)

    target_names = {
        id(Target.Everything): "Everything",
        id(Target.Manager): "Manager",
        id(Target.AllBridges): "AllBridges",
        id(Target.AllChannels): "AllChannels",
        id(Target.AllUsers): "AllUsers",
    }

    def name(self, item_id):
        if type(item_id) is not int:
            return repr(item_id)

        if item_id in self.target_names:
            return self.target_names[item_id]

        if item_id in self.channels:
            return '#{}'.format(self.channels[item_id].name)

        try:
            return self._manager._bridge_name(item_id)
        except (KeyError, AttributeError):
            pass

        try:
            return '#{}'.format(self._manager._channel_name(item_id))
        except (KeyError, AttributeError):
            pass

        for channel in self.channels.values():
            if item_id in channel._users:
                return channel._users[item_id].name

        return str(item_id)

    def on_eavesdrop(self, event):
        args = map(self.name, event.args)
        kwargs = ('{}={}'.format(k, repr(v)) for k, v in event.kwargs.items())
        params = (p for i in (args, kwargs) for p in i)
        print("{} -> {}: {}({})"
              "".format(self.name(event.source_id), self.name(event.target_id),
                        event.name, ', '.join(params)))
