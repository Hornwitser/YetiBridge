import threading

from . import BaseBridge
from .. import BaseEvent

class ConsoleBridge(BaseBridge):
    def __init__(self, config):
        BaseBridge.__init__(self, config)
        self._thread = threading.Thread(target=self.run, daemon=True)
        self.users = {}

    def on_register(self):
        self._thread.start()

    def run(self):
        while True:
            command = input()
            self.send_event('bridge_command', command, 'console')

    def name(self, item_id):
        try:
            return self.users[item_id]
        except KeyError:
            pass

        try:
            return self._manager._bridge_name(item_id)
        except ValueError:
            pass

        if item_id == id(self._manager):
            return 'manager'

        return str(item_id)

    def ev_user_join(self, event, user_id, name):
        self.users[user_id] = name
        print("{}: user '{}' joined".format(self.name(event.bridge_id), name))

    def ev_user_leave(self, event, user_id):
        print("{}: user '{}' left".format(self.name(event.bridge_id),
                                          self.users[user_id]))
        del self.users[user_id]
