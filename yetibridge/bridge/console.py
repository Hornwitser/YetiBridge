import re
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

    def decode_mentions(self, content):
        def replace(match):
            user_id = int(match.group(1))
            try:
                return '@{}'.format(self.get_user(user_id).name)
            except KeyError:
                return match.group()

        return re.sub(r'<\[@([0-9]+)\]>', replace, content)

    def ev_message(self, event, content):
        content = self.decode_mentions(content)

        source = self.name(event.source_id)

        if event.target_id != id(self):
            target = '{}: '.format(self.name(event.target_id))
        else:
            target = ''

        print('{}{} {}'.format(target, source, content))

    def ev_action(self, event, content):
        content = self.decode_mentions(content)

        try:
            source = '* {}'.format(self.get_user(event.source_id).name)
        except KeyError:
            source = '* {}'.format(self.name(event.source_id))

        if event.target_id != id(self):
            target = '{} '.format(self.name(event.target_id))
        else:
            target = ''

        print('{}{} {}'.format(target, source, content))

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

    def on_eavesdrop(self, event):
        args = map(self.name, event.args)
        kwargs = ('{}={}'.format(k, repr(v)) for k, v in event.kwargs.items())
        params = (p for i in (args, kwargs) for p in i)
        print("{} -> {}: {}({})"
              "".format(self.name(event.source_id), self.name(event.target_id),
                        event.name, ', '.join(params)))
