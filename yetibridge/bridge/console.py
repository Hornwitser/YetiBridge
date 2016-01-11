import threading

from . import BaseBridge
from ..event import Target
from ..cmdsys import split, command, is_command

class ConsoleBridge(BaseBridge):
    def __init__(self, config):
        BaseBridge.__init__(self, config)
        self._thread = threading.Thread(target=self.run, daemon=True)
        self.users = {}

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

    target_names = {
        id(Target.Everything): "Everything",
        id(Target.Manager): "Manager",
        id(Target.AllBridges): "AllBridges",
        id(Target.AllChannels): "AllChannels",
        id(Target.AllUsers): "AllUsers",
    }

    def name(self, item_id):
        if item_id in self.target_names:
            return self.target_names[item_id]

        if item_id in self.users:
            return self.users[item_id]

        try:
            return self._manager._bridge_name(item_id)
        except (KeyError, AttributeError):
            pass

        return str(item_id)

    def on_eavesdrop(self, event):
        print("{} -> {}: {} (*{}, **{})"
              "".format(self.name(event.source_id), self.name(event.target_id),
                        event.name, event.args, event.kwargs))
