"""
Simple Log
Licensed under MIT
Copyright (c) 2013 Isaac Muse <isaacmuse@gmail.com>

Not thread safe, probably need to fix that
"""
ALL = 0
DEBUG = 10
INFO = 20
WARNING = 30
ERROR = 40
CRITICAL = 50

class Log(object):
    def __init__(self, filename, format="%(message)s", level=ERROR, filemode="w"):
        if filemode == "w":
            with open(filename, "w") as f:
                pass
        self.filename = filename
        self.level = level
        self.format = format

    def set_level(self, level):
        self.level = int(level)

    def formater(self, lvl, format, msg):
        return format % {
            "loglevel": lvl,
            "message": msg
        }

    def debug(self, msg, format="%(loglevel)s: %(message)s\n"):
        if self.level <= DEBUG:
            self._log(self.formater("DEBUG: ", format, msg))

    def info(self, msg, format="%(loglevel)s: %(message)s\n"):
        if self.level <= INFO:
            self._log(self.formater("INFO: ", format, msg))

    def warning(self, msg, format="%(loglevel)s: %(message)s\n"):
        if self.level <= WARNING:
            self._log(self.formater("WARNING: ", format, msg))

    def error(self, msg, format="%(loglevel)s: %(message)s\n"):
        if self.level <= ERROR:
            self._log(self.formater("ERROR: ", format, msg))

    def critical(self, msg, format="%(loglevel)s: %(message)s\n"):
        if self.level <= CRITICAL:
            self._log(self.formater("CRITICAL: ", format, msg))

    def _log(self, msg):
        with open(self.filename, "a") as f:
            f.write((self.format % {"message": msg}))
