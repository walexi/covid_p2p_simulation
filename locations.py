from collections import namedtuple, deque

from simpy import Interrupt
from simpy.core import Infinity

from base import Env
from config import TICK_MINUTE

LocationIO = namedtuple(
    "LocationIO",
    [
        "human_name",
        "location_name",
        "io_type",
        "timestamp",
        "human_is_infected",
        "num_infected_humans_at_location",
    ],
)


class Human(object):
    def __init__(self, env, name):
        self.env = env
        self.name = name
        # Infections
        self.infected = False
        self.infected_at = None
        self.disinfected_at = None
        # Locations
        self.location_history = deque(maxlen=2)
        self.location_entry_timestamp_history = deque(maxlen=2)

    @property
    def location(self):
        return self.location_history[-1]

    @property
    def previous_location(self):
        return self.location_history[-2]

    def at(self, location: "Location", duration, wait=None):
        if wait is not None:
            yield self.env.timeout(wait / TICK_MINUTE)
        location.enter(self)
        yield self.env.timeout(duration / TICK_MINUTE)
        location.exit(self)

    def expose(self, now):
        # TODO Exposed --> Infected transition
        return self.infect(now)

    def infect(self, now):
        assert now is not None
        if self.infected:
            # Nothing to do here
            return self
        self.infected_at = now
        self.infected = True
        return self

    def disinfect(self, now):
        assert now is not None
        if not self.infected:
            # Nothing to do here
            return self
        self.disinfected_at = now
        self.infected = False
        return self

    def __hash__(self):
        return hash(self.name)


class Location(object):
    """Locations are now processes."""

    def __init__(self, env: Env, name: str, verbose=False):
        # Meta data
        self.env = env
        self.name = name
        self.verbose = verbose
        self.now = self.env.timestamp
        # Infection book keeping
        self.last_contaminated = None
        # Entry and exit handling
        self.humans = dict()
        self.entry_queue = []
        self.exit_queue = []
        self.process = self.env.process(self.run())
        # Logging
        self.events = []

    def enter(self, human):
        self.entry_queue.append(human)
        self.process.interrupt()

    def exit(self, human):
        self.exit_queue.append(human)
        self.process.interrupt()

    def run(self):
        while True:
            try:
                # The location sleeps until interrupted
                yield self.env.timeout(Infinity)
            except Interrupt:
                # ^ Wakey wakey.
                # Check the time; we do it once because timedelta in self.env.timestamp
                # consumes a good chuck of the run-time.
                self.now = self.env.timestamp
                # Check who wants to enter
                while self.entry_queue:
                    self.register_human_entry(self.entry_queue.pop())
                # Who infects whom
                self.update_infections()
                # ... and who wants to exit
                while self.exit_queue:
                    self.register_human_exit(self.exit_queue.pop())
                # Back to slumber. We set self.now to None as a tripwire.
                self.now = None

    def update_infections(self):
        # FIXME This is a very naive model, but it'll be enough for now.
        # Infect everyone if anyone is infected in the location.
        if self.infected_human_count > 0:
            for human in self.humans:
                # If the human is already infected, this will not update
                # the infection time-stamp.
                human.expose(self.now)

    def register_human_entry(self, human: Human):
        if self.verbose:
            print(
                f"Human {human.name} ({'S' if not human.infected else 'I'}) "
                f"entered Location {self.name} at time {self.now} contaminated "
                f"with {self.infected_human_count} infected humans."
            )
        # Set location and timestamps of human
        human.location_history.append(self)
        human.location_entry_timestamp_history.append(self.now)
        # Add human
        self.humans[human] = {
            "was_infected_on_arrival": human.infected,
            "arrived_at": self.now,
        }
        # Record the human entering
        self.events.append(
            LocationIO(
                human_name=human.name,
                location_name=self.name,
                io_type="in",
                timestamp=self.now,
                human_is_infected=human.infected,
                num_infected_humans_at_location=self.infected_human_count,
            )
        )

    @property
    def infected_human_count(self):
        return sum([human.infected for human in self.humans])

    def register_human_exit(self, human: Human):
        # Record the human exiting
        self.events.append(
            LocationIO(
                human_name=human.name,
                location_name=self.name,
                io_type="out",
                timestamp=self.now,
                human_is_infected=human.infected,
                num_infected_humans_at_location=self.infected_human_count,
            )
        )
        del self.humans[human]
        if self.verbose:
            print(
                f"Human {human.name} ({'S' if not human.infected else 'I'}) "
                f"exited Location {self.name} at time {self.now} contaminated "
                f"with {self.infected_human_count} infected humans."
            )

    def __hash__(self):
        return hash(self.name)


if __name__ == "__main__":
    import datetime

    env = Env(datetime.datetime(2020, 2, 28, 0, 0))

    L = Location(env, "L", verbose=True)

    A = Human(env, "A")
    B = Human(env, "B")
    C = Human(env, "C").infect(L.now)
    D = Human(env, "D")
    E = Human(env, "E")
    F = Human(env, "F")
    G = Human(env, "G")

    env.process(A.at(L, duration=10, wait=0))
    env.process(B.at(L, duration=1, wait=2))
    env.process(C.at(L, duration=4, wait=3))
    env.process(D.at(L, duration=4, wait=4))
    env.process(E.at(L, duration=5, wait=9))
    env.process(F.at(L, duration=5, wait=15))
    env.process(G.at(L, duration=3, wait=16))

    env.run(100)
