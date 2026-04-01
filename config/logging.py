class SafeContextFilter:
    """
    Ensure optional log context fields exist so formatters don't error.
    """

    def filter(self, record):
        if not hasattr(record, "event"):
            record.event = ""
        if not hasattr(record, "request_id"):
            record.request_id = ""
        return True
