from ..event import Event, Target

class Channel:
    __slots__ = ('_id', '_name', '_users')

    def __init__(self, id, name, users):
        self._id = id
        self._name = name
        self._users = {}

        for user_id, user in users:
            self._users[user_id] = User(user_id, user['name'])

    def copy(self):
        return Channel(self._id, self._name, self._users.copy())

    @property
    def id(self):
        return self._id

    @property
    def name(self):
        return self._name

    @property
    def users(self):
        return self._users.values()


class User:
    __slots__ = ('_id', '_name')

    def __init__(self, id, name):
        self._id = id
        self._name = name

    def copy(self):
        return User(self._id, self._name)

    @property
    def id(self):
        return self._id

    @property
    def name(self):
        return self._name


class BaseBridge:
    def __init__(self, config):
        self.config = config
        self.channels = {}

    def _assert_registered(self):
        if not self.is_registered:
            raise RuntimeError("this {} is not registered".format(type(self)))

    def register(self, manager):
        if self.is_registered:
            raise RuntimeError("attempt to register already registered {}"
                               "".format(type(self)))

        self._manager = manager
        self._hook('on_register')

    def deregister(self):
        self._assert_registered()

        self._hook('on_deregister')
        self.detach()

    def detach(self):
        self.send_event(self, Target.Manager, 'detach')
        del self._manager

    @property
    def is_registered(self):
        return hasattr(self, "_manager")

    def ev_channel_add(self, event, channel_id, name, users):
        self.channels[channel_id] = channel = Channel(channel_id, name, users)
        self._hook('on_channel_add', channel)

    def ev_channel_remove(self, event, channel_id):
        channel = self.channels[channel_id]
        del self.channels[channel_id]
        self._hook('on_channel_remove', channel)

    def ev_user_add(self, event, user_id, name):
        channel = self.channels[event.target_id]
        channel._users[user_id] = user = User(user_id, name)
        self._hook('on_user_add', channel, user)

    def ev_user_update(self, event, user_id, name):
        channel = self.channels[event.target_id]
        after = channel._users[user_id]
        before = after.copy()
        after._name = name
        self._hook('on_user_update', channel, before, after)

    def ev_user_remove(self, event, user_id):
        channel = self.channels[event.target_id]
        user = channel._users[user_id]
        del self.channels[event.target_id]._users[user_id]
        self._hook('on_user_remove', channel, user)

    def ev_shutdown(self, event):
        self.detach()

    def terminate(self):
        self._hook('on_terminate')

    def _hook(self, name, *args, **kwargs):
        handler = getattr(self, name, None)
        if handler is not None:
            handler(*args, **kwargs)

    def _dispatch(self, event):
        self._hook('on_event', event)
        handler = getattr(self, 'ev_{}'.format(event.name), None)
        if handler is not None:
            handler(event, *event.args, **event.kwargs)

    def send_event(self, source, target, name, *args, **kwargs):
        self._assert_registered()
        self._manager.events.put(Event(source, target, name, *args, **kwargs))
