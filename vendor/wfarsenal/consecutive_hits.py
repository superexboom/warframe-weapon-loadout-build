"""Consecutive hit damage with independent, suspended form snapshots."""
from dataclasses import dataclass
import math


@dataclass
class ConsecutiveHits:
    per_hit: float
    maximum: int
    duration: float
    hits: float = 0.
    expires: float = -math.inf
    other: tuple = (0.,0.)

    def shot(self,time,hits):
        if time>=self.expires:
            self.hits=0.
        if hits<=0:
            self.hits=0.
            self.expires=-math.inf
            return 1.
        self.hits+=hits
        self.expires=time+self.duration
        return 1.+self.per_hit*min(self.maximum,max(self.hits-1.,0.))

    def swap(self,time):
        saved=(self.hits,max(self.expires-time,0.))
        self.hits,remaining=self.other
        self.expires=time+remaining if remaining else -math.inf
        self.other=saved
