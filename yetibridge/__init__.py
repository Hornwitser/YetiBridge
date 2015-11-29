import queue
import collections

from .parse import split

def _command(function):
    function.is_command = True
    return function

class BridgeManager:
    def __init__(self, config):
        self.config = config
        self.events = queue.Queue()
        self._bridges = {"manager": self}
        self._users = {}

    def attach(self, name, bridge):
        assert name not in self._bridges, \
            "bridge '%s' is already attached!" % name

        for user_id, user in self._users.items():
            event = BaseEvent(id(self), 'user_joined', user_id, user['nick'])
            bridge._dispatch(event)

        self._bridges[name] = bridge
        bridge.register(self)

    def detach(self, name):
        assert name in self._bridges, "bridge '%s' is not attached!" % name
        self._bridges[name].deregister()

    def _ev_bridge_detach(self, event):
        name = self._bridge_name(event.bridge_id)
        for user_id, user in self._users.items():
            if user['bridge'] == event.bridge_id:
                event = BaseEvent(event.bridge_id, 'user_left', user_id)
                self.events.put(event)
            else:
                event = BaseEvent(id(self), 'user_left', user_id)
                self._bridges[name]._dispatch(event)

        del self._bridges[name]


    def _bridge_name(self, bridge_id):
        for name, bridge in self._bridges.items():
            if id(bridge) == bridge_id:
                return name
        else:
            raise ValueError("no bridge with id %s is attached" % bridge_id)

    def _ev_user_join(self, event, user_id, nick):
        self._users[user_id] = {'bridge': event.bridge_id, 'nick': nick}

    def _ev_user_update(self, event, user_id, nick):
        self._users[user_id] = {'bridge': event.bridge_id, 'nick': nick}

    def _ev_user_leave(self, bridge_id, user_id):
        del self._users[user_id]

    def _tr_bridge_command(self, event, string, authority):
        try:
            words = split(string)
        except ValueError as e:
            self._send_event('bridge_message', "error: {}".format(str(e)))
            return False

        if len(words) == 0:
            self._send_event('bridge_message', "error: empty command")
            return False

        if words[0] not in self._bridges:
            self._send_event('bridge_message',
                             "error: '{}' no such bridge".format(words[0]))
            return False

        target = id(self._bridges[words[0]])
        event.args = [target, words[1:], authority]
        return True

    def _ev_bridge_command(self, event, target, command, authority):
        if target != id(self):
            return

        if len(command) == 0:
            self._send_event('bridge_message', "error: empty command")
            return

        handler = getattr(self, '_{}'.format(command[0]), None)
        if getattr(handler, "is_command", False):
            try:
                response = handler(*command[1:])
            except Exception as e:
                self._send_event('bridge_message', "error: {}".format(e))
                return

            if response is not None:
                self._send_event('bridge_message', response)
        else:
            self._send_event('bridge_message',
                             "error: '{}' unkown command".format(command[0]))

    def _send_event(self, name, *args, **kwargs):
        event = BaseEvent(id(self), name, *args, **kwargs)
        self.events.put(event)

    def _dispatch(self, event):
        handler = getattr(self, '_ev_{}'.format(event.name), None)
        if handler is not None:
            handler(event, *event.args, **event.kwargs)

    def _translate(self, event):
        handler = getattr(self, '_tr_{}'.format(event.name), None)
        if handler is not None:
            return handler(event, *event.args, **event.kwargs)
        else:
            return True

    def once(self):
        event = self.events.get()
        if self._translate(event):
            for bridge in self._bridges.values():
                bridge._dispatch(event)

    def run(self):
        self._running = True
        try:
            while self._running:
                self.once()
        finally:
            self.terminate()

    def terminate(self):
        while True:
            try:
                name, bridge = self._bridges.popitem()
            except KeyError:
                break

            if bridge is not self:
                bridge.terminate()

class BaseEvent:
    def __init__(self, bridge_id, name, *args, **kwargs):
        self.bridge_id = bridge_id
        self.name = name
        self.args = args
        self.kwargs = kwargs

    def __str__(self):
        return 'Event({}, {}, *{}, **{})'.format(self.bridge_id, self.name,
                                                 self.args, self.kwargs)

# Some events
'user_join' # A user has joined in a bridged chat
'user_update' # User details has been updated in a bridged chat
'user_leave' # A user has left a bridged chat
'channel_message' # Message recieved from a bridged chat
'channel_command' # Command recieved from a bridged chat
'private_message' # Message to a user across the bridge
'bridge_broadcast' # Broadcast across the bridge
'bridge_message' # Message to the bridge from a user
'bridge_command' # Command to the bridge from a user
'bridge_detach' # Signal a bridge is detaching from the bridge manager
