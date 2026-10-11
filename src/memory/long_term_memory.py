

class LongTermMessage(object):
    """
    A long term message is a message that is stored in the database and not removed when it expires.
    """
    def __init__(self, db_id, channel, nick, hostmask, message, expiry, metadata=None):
        self.db_id = db_id
        self.channel = channel
        self.nick = nick
        self.hostmask = hostmask
        self.message = message
        self.expiry = expiry
        self.metadata = metadata or {}