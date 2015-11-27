from .. import BaseEvent

class BaseBridge:
    def __init__(self, config):
        self.config = config
        self.imposters = {}

    def register(self, manager):
        assert not self.is_registered, \
            "this '%s' is already registered!" % self.__class__

        self._manager = manager
        self._hook('on_register')

    def deregister(self):
        assert self.is_registered, \
            "this '%s' is not registered!" % self.__class__

        self._hook('on_deregister')
        self.send_event('bridge_detach')
        del self._manager

    @property
    def is_registered(self):
        return hasattr(self, "_manager")

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

    def send_event(self, name, *args, **kwargs):
        assert self.is_registered, \
            "this '%s' is not registered!" % self.__class__
        self._manager.events.put(BaseEvent(id(self), name, *args, **kwargs))
