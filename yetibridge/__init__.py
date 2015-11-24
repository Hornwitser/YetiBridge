import queue
import collections

class BridgeManager:
    def __init__(self, config):
        self.config = config
        self.events = queue.Queue()
        self._bridges = {}
        self._users = {}

    def attach(self, name, bridge):
        if name in self._bridges:
            raise ValueError("Bridge already attached!")

        for user_id, user in self._users.items():
            event = BaseEvent(id(self), 'user_joined', user_id, user['nick'])
            bridge.dispatch(event)

        self._bridges[name] = bridge
        bridge.register(self)

    def detach(self, name):
        if name not in self._bridges:
            raise ValueError("Bridge not attached!")

        self._bridges[name].deregister()

    def _ev_bridge_detach(self, event):
        name = self.get_bridge_name(event.bridge_id)
        for user_id, user in self._users.items():
            if user['bridge'] == event.bride_id:
                event = BaseEvent(event.bride_id, 'user_left', user_id)
                self.events.put(event)
            else:
                event = BaseEvent(id(self), 'user_left', user_id)
                self._bridges[name].dispatch(event)

        del self._bridges[name]


    def get_bridge_name(self, bridge_id):
        for name, bridge in self._bridges.items():
            if id(bridge) == bridge_id:
                return name
        else:
            raise ValueError("No bridge with id %s found" % bridge_id)

    def _ev_user_join(self, event, user_id, nick):
        self._users[user_id] = {'bridge': event.bridge_id, 'nick': nick}

    def _ev_user_update(self, event, user_id, nick):
        self._users[user_id] = {'bridge': event.bridge_id, 'nick': nick}

    def _ev_user_leave(self, bridge_id, user_id):
        del self._users[user_id]

    def _dispatch(self, event):
        handler = getattr(self, '_ev_{}'.format(event.name), None)
        if handler is not None:
            handler(event, *event.args, **event.kwargs)

    def run(self):
        while True:
            event = self.events.get()
            print(event)
            self._dispatch(event)
            for bridge in self._bridges.values():
                bridge.dispatch(event)

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
