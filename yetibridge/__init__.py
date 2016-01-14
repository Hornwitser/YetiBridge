import queue
import collections

from .cmdsys import command, is_command
from .event import Event, Target

class BridgeChannel:
    def __init__(self, manager):
        self._manager = manager
        self.bridges = set()
        self.users = {}

    def _bridge_join(self, bridge_id):
        if bridge_id in self.bridges:
            raise ValueError("bridge already joined")

        self.bridges.add(bridge_id)

    def _bridge_leave(self, bridge_id):
        bridge_users = [(i, u) for i, u in self.users.items()
                            if u['bridge_id'] == bridge_id]

        for user_id, user in bridge_users:
            event = Event(self, self._manager, 'user_leave', id(self), user_id)
            self._manager.events.put(event)

        self.bridges.remove(bridge_id)

    def _user_join(self, user_id, name, bridge_id):
        if user_id in self.users:
            raise ValueError("user already joined")

        self.users[user_id] = {"name": name, "bridge_id": bridge_id}

    def _user_update(self, user_id, name):
        self.users[user_id]["name"] = name

    def _user_leave(self, user_id):
        del self.users[user_id]

class BridgeManager:
    def __init__(self, config):
        self.config = config
        self.events = queue.Queue()
        self._bridges = {"manager": self}
        self._channels = {}
        self._eavesdropper = None

    def attach(self, name, bridge):
        assert name not in self._bridges, \
            "bridge '%s' is already attached!" % name

        self._bridges[name] = bridge
        bridge.register(self)

    def detach(self, name):
        assert name in self._bridges, "bridge '%s' is not attached!" % name
        self._bridges[name].deregister()

    def _tr_detach(self, event):
        name = self._bridge_name(event.source_id)

        turned_empty = []
        for channel_name, channel in self._channels.items():
            if event.source_id in channel.bridges:
                channel._bridge_leave(event.source_id)
                if not len(channel.bridges):
                    turned_empty.append(channel_name)

        for channel_name in turned_empty:
            del self._channels[channel_name]

        del self._bridges[name]
        self._running = len(self._bridges) > 1
        return True

    def _bridge_name(self, bridge_id):
        for name, bridge in self._bridges.items():
            if id(bridge) == bridge_id:
                return name
        else:
            raise KeyError("no bridge with id %s is attached" % bridge_id)

    def _channel_name(self, channel_id):
        for name, channel in self._channels.items():
            if id(channel) == channel_id:
                return name
        else:
            raise KeyError("no channel with id %s is attached" % channel_id)

    def _ev_channel_join(self, event, name):
        try:
            channel = self._channels[name]
        except KeyError:
            channel = self._channels[name] = BridgeChannel(self)

        bridge_id, users = event.source_id, channel.users.copy()
        self._send_event(bridge_id, 'channel_add', id(channel), name, users)
        channel._bridge_join(bridge_id)

    def _ev_channel_leave(self, event, name):
        self._channels[name]._bridge_leave(event.source_id)
        channel = self._channels[name]
        self._send_event(event.source_id, 'channel_remove', id(channel))

        if not len(self._channels[name].bridges):
            del self._channels[name]

    def _ev_user_join(self, event, channel_id, user_id, name):
        channel_name = self._channel_name(channel_id)

        self._send_event(channel_id, 'user_add', user_id, name)
        self._channels[channel_name]._user_join(user_id, name, event.source_id)

    def _ev_user_change(self, event, channel_id, user_id, name):
        channel_name = self._channel_name(channel_id)

        self._send_event(channel_id, 'user_update', user_id, name)
        self._channels[channel_name]._user_update(user_id, name)

    def _ev_user_leave(self, event, channel_id, user_id):
        channel_name = self._channel_name(channel_id)

        self._channels[channel_name]._user_leave(user_id)
        self._send_event(channel_id, 'user_remove', user_id)

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

            if event.target_id == Target.Everything:
                bridges = self._bridges.values()

            elif event.target_id == Target.Manager:
                bridges = (self,)

            elif event.target_id == Target.AllBridges:
                bridges = (b for b in self._bridges.values() if b is not self)

            elif event.target_id == Target.AllChannels:
                bridge_ids = {i for c in self._channels for i in c.bridges}
                bridges = (b for b in self._bridges.values()
                               if id(b) in bridge_ids)

            elif event.target_id == Target.AllUsers:
                users = (u for c in self._channels for u in c.users)
                bridge_ids = {u['bridge_id'] for u in users}
                bridges = (b for b in self._bridges.values()
                               if id(b) in bridge_ids)

            else:
                for bridge in self._bridges.values():
                    if id(bridge) == event.target_id:
                        bridges = (bridge,)
                        break

                else:
                    for channel in self._channels.values():
                        if id(channel) == event.target_id:
                            bridges = (b for b in self._bridges.values()
                                           if id(b) in channel.bridges)
                            break

                        elif event.target_id in channel.users:
                            user = channel.users[event.target_id]
                            bridges = (b for b in self._bridges.values()
                                           if id(b) == user['bridge_id'])
                            break
                    else:
                        raise ValueError("invalid target")

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
