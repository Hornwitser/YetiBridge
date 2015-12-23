import queue
import collections

from .cmdsys import command, is_command
from .mixin import Manager
from .event import Event, Target

class BridgeManager(Manager):
    def __init__(self, config):
        self.config = config
        self.events = queue.Queue()
        self._bridges = {"manager": self}
        self._users = {}
        self._eavesdropper = None

    def attach(self, name, bridge):
        assert name not in self._bridges, \
            "bridge '%s' is already attached!" % name

        for user_id, user in self._users.items():
            event = Event(self, bridge, 'user_join', user_id, user['nick'])
            bridge._dispatch(event)

        self._bridges[name] = bridge
        bridge.register(self)

    def detach(self, name):
        assert name in self._bridges, "bridge '%s' is not attached!" % name
        self._bridges[name].deregister()

    def _tr_detach(self, event):
        name = self._bridge_name(event.source_id)
        for user_id, user in self._users.items():
            if user['bridge'] == event.source_id:
                event = Event(event.source_id, Target.AllBridges, 'user_left',
                              user_id)
                self.events.put(event)
            else:
                event = Event(self, event.source_id, 'user_left', user_id)
                self._bridges[name]._dispatch(event)

        del self._bridges[name]
        self._running = len(self._bridges) > 1
        return True

    def _bridge_name(self, bridge_id):
        for name, bridge in self._bridges.items():
            if id(bridge) == bridge_id:
                return name
        else:
            raise KeyError("no bridge with id %s is attached" % bridge_id)

    def _ev_user_join(self, event, user_id, nick):
        self._users[user_id] = {'bridge': event.source_id, 'nick': nick}

    def _ev_user_update(self, event, user_id, nick):
        self._users[user_id] = {'bridge': event.source_id, 'nick': nick}

    def _ev_user_leave(self, event, user_id):
        del self._users[user_id]

    def _tr_command(self, event, words, authority):
        if len(words) == 0:
            self._send_event(event.source_id, 'message',
                             "error: empty command")
            return False

        elif words[0] not in self._bridges:
            self._send_event(event.source_id, 'message',
                             "error: '{}' no such bridge".format(words[0]))
            return False

        event.target_id = id(self._bridges[words[0]])
        event.args = [words[1:], authority]
        return True

    def _ev_command(self, event, command, authority):
        if len(command) == 0:
            self._send_event(event.source_id, 'message',
                             "error: empty command")
            return

        handler = getattr(self, '_{}'.format(command[0]), None)
        if is_command(handler):
            try:
                response = handler(*command[1:])
            except Exception as e:
                self._send_event(event.source_id, 'message',
                                 "error: {}".format(e))
            else:
                if response is not None:
                    self._send_event(event.source_id, 'message', response)
        else:
            self._send_event(event.source_id, 'message', "error: '{}' "
                             "unkown command".format(command[0]))

    def _ev_exception(self, event, exception):
        raise exception

    def _send_event(self, target, name, *args, **kwargs):
        self.events.put(Event(self, target, name, *args, **kwargs))

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
            if self._eavesdropper is not None:
                self._eavesdropper(event)

            if event.is_target(Target.AllUsers):
                test = lambda b: b is not self
            else:
                test = lambda b: event.is_target(b)

            bridges = [b for b in self._bridges.values() if test(b)]
            if not len(bridges):
                bridge_id = self._users[event.target_id]['bridge']
                bridges = (self._bridges[self._bridge_name(bridge_id)],)

            for bridge in bridges:
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

    @command
    def _shutdown(self):
        self._send_event(Target.AllBridges, 'shutdown')
