

class ShortTermMessage(object):
    """
    A message that is stored in a short term cache.
    """
    def __init__(self, message_id, user, channel, text, timestamp):
        self.message_id = message_id
        self.user = user
        self.channel = channel
        self.text = text
        self.timestamp = timestamp