""" Locking stats object for use between threads """

import threading
from dataclasses import dataclass, field

@dataclass
class StatsData:
    """ Stats dataclass for passing metrics between threads """
    data: dict = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def update(self, key, data):
        """ Update a value with a given key """
        with self.lock:
            self.data[key] = data

    def increment(self, key):
        """ Increment a value by one """
        with self.lock:
            if key not in self.data:
                self.data[key] = 0
            self.data[key] = self.data[key] + 1

    def decrement(self, key):
        """ Decrement a value by one """
        with self.lock:
            if key not in self.data:
                self.data[key] = 0
            self.data[key] = self.data[key] - 1

    def snapshot(self):
        """ Get a snapshot of our data """
        with self.lock:
            return dict(self.data)
