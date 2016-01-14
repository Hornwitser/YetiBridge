import threading

from . import BaseBridge
from ..event import Target
from ..cmdsys import split, command, is_command

class ConsoleBridge(BaseBridge):
    def __init__(self, config):
        BaseBridge.__init__(self, config)
        self._thread = threading.Thread(target=self.run, daemon=True)
        self.channels = {}

    def ev_channel_add(self, event, channel_id, name, users):
        print('joined #{}'.format(name))

        self.channels[channel_id] = {'name': name, 'users': users}

    def ev_channel_remove(self, event, channel_id):
        print('left #{}'.format(self.channels[channel_id]['name']))

        del self.channels[channel_id]

    def ev_user_add(self, event, user_id, name):
        self.channels[event.target_id]['users'][user_id] = {'name': name}

        channel_name = self.channels[event.target_id]['name']
        print('#{}: {} joined'.format(channel_name, name))

    def ev_user_update(self, event, user_id, name):
        old_name = self.channels[event.target_id]['users'][user_id]['name']
        channel_name = self.channels[event.target_id]['name']
        print('#{}: {} -> {}'.format(channel_name, old_name, name))

        self.channels[event.target_id]['users'][user_id]['name'] = name

    def ev_user_remove(self, event, user_id):
        name = self.channels[event.target_id]['users'][user_id]['name']
        channel_name = self.channels[event.target_id]['name']
        print('#{}: {} left'.format(channel_name, old_name, name))

        del self.channels[event.target_id]['users'][user_id]

    def on_register(self):
        self._thread.start()
        self._manager._eavesdropper = self.on_eavesdrop

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
            return '#{}'.format(self.channels[item_id]['name'])

        try:
            return self._manager._bridge_name(item_id)
        except (KeyError, AttributeError):
            pass

        try:
            return '#{}'.format(self._manager._channel_name(item_id))
        except (KeyError, AttributeError):
            pass

        for channel in self.channels.values():
            if item_id in channel['users']:
                return channel['users'][item_id]['name']

        return str(item_id)

    def on_eavesdrop(self, event):
        args = map(self.name, event.args)
        kwargs = ('{}={}'.format(k, repr(v)) for k, v in event.kwargs.items())
        params = (p for i in (args, kwargs) for p in i)
        print("{} -> {}: {}({})"
              "".format(self.name(event.source_id), self.name(event.target_id),
                        event.name, ', '.join(params)))
