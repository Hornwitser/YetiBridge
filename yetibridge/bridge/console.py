import threading

from . import BaseBridge
from .. import BaseEvent
from ..cmdsys import split

class ConsoleBridge(BaseBridge):
    def __init__(self, config):
        BaseBridge.__init__(self, config)
        self._thread = threading.Thread(target=self.run, daemon=True)
        self.users = {}

    def on_register(self):
        self._thread.start()

    def run(self):
        while True:
            string = input()
            try:
                words = split(string)
            except ValueError as e:
                print('error: {}'.format(e))
            else:
                self.send_event('bridge_command', words, 'console')

    def name(self, item_id):
        try:
            return self.users[item_id]
        except KeyError:
            pass

        try:
            return self._manager._bridge_name(item_id)
        except ValueError:
            pass

        return str(item_id)

    def ev_user_join(self, event, user_id, name):
        self.users[user_id] = name
        print("{}: user '{}' joined".format(self.name(event.bridge_id), name))

    def ev_user_update(self, event, user_id, name):
        self.users[user_id] = name
        print("{}: user '{}' updated".format(bridge_name, name))

    def ev_user_leave(self, event, user_id):
        print("{}: user '{}' left".format(self.name(event.bridge_id),
                                          self.users[user_id]))
        del self.users[user_id]

    def ev_bridge_message(self, event, content):
        print("{}: {}".format(self.name(event.bridge_id), content))

    def ev_bridge_command(self, event, target, command, authority):
        print("{} -> {}: command {}".format(self.name(event.bridge_id),
                                            self.name(target), command))
