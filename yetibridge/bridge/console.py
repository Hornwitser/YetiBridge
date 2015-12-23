import threading

from . import BaseBridge
from ..event import Target
from ..cmdsys import split, command, is_command

target_names = {
    id(Target.Everything): "Everything",
    id(Target.Manager): "Manager",
    id(Target.AllBridges): "AllBridges",
    id(Target.AllUsers): "AllUsers",
}

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
        self.send_event(Target.Manager, 'command', words, 'console')

    @command
    def manager(self, *words):
        self.bridge(*(['manager']+list(words)))

    @command
    def shutdown(self):
        self.manager('shutdown')

    def name(self, item_id):
        if item_id in target_names:
            return target_names[item_id]

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

    def ev_user_join(self, event, user_id, name):
        self.users[user_id] = name
        print("{}: user '{}' joined".format(self.name(event.source_id), name))

    def ev_user_update(self, event, user_id, name):
        self.users[user_id] = name
        print("{}: user '{}' updated".format(bridge_name, name))

    def ev_user_leave(self, event, user_id):
        print("{}: user '{}' left".format(self.name(event.source_id),
                                          self.users[user_id]))
        del self.users[user_id]

    def ev_message(self, event, content):
        print("{}: {}".format(self.name(event.source_id), content))

    def ev_command(self, event, command, authority):
        print("{} -> {}: command {}"
              "".format(self.name(event.source_id),
                        self.name(event.target_id), command))
