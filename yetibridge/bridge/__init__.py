from .. import BaseEvent

class BaseBridge:
    def __init__(self, config):
        self.config = config
        self.imposters = {}

    def register(self, manager):
        if hasattr(self, "_manager"):
            raise ValueError("Bridge already registered!")

        self._manager = manager
        self.init()

    def dispatch(self, event):
        handler = getattr(self, 'ev_{}'.format(event.name), None)
        if handler is not None:
            handler(event, *event.args, **event.kwargs)

    def send_event(self, name, *args, **kwargs):
        if not self.registered:
            raise ValueError("Bridge not registered!")
        self._manager.events.put(BaseEvent(id(self), name, *args, **kwargs))
