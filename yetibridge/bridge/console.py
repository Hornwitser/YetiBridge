import threading

from . import BaseBridge
from .. import BaseEvent

class ConsoleBridge(BaseBridge):
    def __init__(self, config):
        BaseBridge.__init__(self, config)
        self._thread = threading.Thread(target=self.run)
        self.users = {}

    def init(self):
        self._thread.start()

    def run(self):
        while True:
            command = input()
            self.send_event('bridge_command', command, 'console')

    def ev_user_join(self, event, user_id, name):
        self.users[user_id] = name
        bridge_name = self._manager.get_bridge_name(event.bridge_id)
        print("{}: User '{}' joined".format(bridge_name, name))

    def ev_user_leave(self, event, user_id):
        bridge_name = self._manager.get_bridge_name(event.bridge_id)
        print("{}: User '{}' joined".format(bridge_name, self.users[user_id]))
        del self.users[user_id]
