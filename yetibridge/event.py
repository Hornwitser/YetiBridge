from .mixin import Manager, Bridge, Channel, User

class _TargetType:
    pass

class Target:
    Everything = _TargetType()
    Manager = _TargetType()
    AllBridges = _TargetType()
    AllChannels = _TargetType()
    AllUsers = _TargetType()

class Event:
    def __init__(self, source, target, name, *args, **kwargs):
        self.target_id = target if type(target) is int else id(target)
        self.source_id = source if type(source) is int else id(source)
        self.name = name
        self.args = args
        self.kwargs = kwargs

    def is_target(self, target):
        if isinstance(target, _TargetType):
            return self.target_id == id(target)
        elif self.target_id == id(Target.Everything):
            return True
        elif self.target_id == id(Target.Manager):
            return isinstance(target, Manager)
        elif self.target_id == id(Target.AllBridges):
            return isinstance(target, Bridge)
        elif self.target_id == id(Target.AllChannels):
            return isinstance(target, Channel)
        elif self.target_id == id(Target.AllUsers):
            return isinstance(target, User)
        else:
            return self.target_id == id(target)

    def __str__(self):
        return ('Event({}, {}, {}, *{}, **{})'
                ''.format(self.source_id, self.target_id,
                          self.name, self.args, self.kwargs))

# Some events
'user_add' # A user has joined in a channel
'user_update' # User details has been updated in a channel
'user_remove' # A user has left a channel
'user_join' # A user is joining a channel
'user_leave' # A user is leaving a channel
'message' # Message recieved from a bridged chat or a user
'command' # Command recieved from a bridged chat or a user
'exception' # Propogate an exception
'shutdown' # Global shutdown event, all brides are expected to detach
'broadcast' # Broadcast across the bridge
'detach' # Signals a bridge is detaching from the bridge manager
