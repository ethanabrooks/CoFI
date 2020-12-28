import itertools
import typing
from abc import abstractmethod, ABC, ABCMeta
from collections import Counter
from dataclasses import dataclass, astuple, field, asdict
from enum import unique, Enum, auto, EnumMeta
from functools import lru_cache
from typing import Tuple, Union, List, Generator, Dict, Generic, Optional, Iterable

import gym
import numpy as np
import torch
from colored import fg, sys
from gym import Space, spaces

from utils import RESET, get_max_shape

CoordType = Tuple[int, int]
IntGenerator = Generator[int, None, None]
BoolGenerator = Generator[bool, None, None]

WORLD_SIZE = None


def move_from(origin: CoordType, toward: CoordType) -> CoordType:
    origin = np.array(origin)
    i, j = np.array(origin) + np.clip(
        np.array(toward) - origin,
        -1,
        1,
    )
    return i, j


""" abstract classes """


class WorldObject:
    @property
    @abstractmethod
    def symbol(self):
        pass

    @abstractmethod
    def __eq__(self, other):
        pass


class ActionComponentMeta(type):
    pass


class ActionComponentEnumMeta(ActionComponentMeta, EnumMeta):
    pass


class ActionComponentABCMeta(ActionComponentMeta, ABCMeta):
    pass


class ActionComponent(metaclass=ActionComponentMeta):
    @staticmethod
    @abstractmethod
    def parse(n: int) -> "ActionComponent":
        pass

    @staticmethod
    @abstractmethod
    def space() -> spaces.Discrete:
        pass

    @abstractmethod
    def to_int(self) -> int:
        pass


ActionComponentGenerator = Generator[ActionComponent, None, None]


class Building(WorldObject, ActionComponent, ABC, metaclass=ActionComponentABCMeta):
    def __eq__(self, other):
        return type(self) == type(other)

    def __hash__(self):
        return hash(type)

    def __str__(self):
        return self.__class__.__name__

    @property
    @abstractmethod
    def cost(self) -> "Resources":
        pass

    def on(self, coord: "CoordType", building_positions: "BuildingPositions"):
        return self == building_positions.get(coord)

    @staticmethod
    def parse(n: int) -> ActionComponent:
        return Buildings[n]

    @staticmethod
    def space() -> spaces.Discrete:
        return spaces.Discrete(len(Buildings))

    @property
    @abstractmethod
    def symbol(self) -> str:
        pass

    def to_int(self) -> int:
        return Buildings.index(self)


class Assignment:
    @abstractmethod
    def execute(
        self,
        positions: "Positions",
        worker: "Worker",
        assignments: "Assignments",
        building_positions: "BuildingPositions",
        pending_positions: "BuildingPositions",
        resources: typing.Counter["Resource"],
        carrying: "Carrying",
    ) -> None:
        raise NotImplementedError


""" world objects"""


@unique
class Worker(WorldObject, ActionComponent, Enum, metaclass=ActionComponentEnumMeta):
    W1 = auto()
    W2 = auto()
    W3 = auto()
    W4 = auto()
    W5 = auto()
    W6 = auto()
    W7 = auto()
    W8 = auto()
    W9 = auto()
    W10 = auto()
    W11 = auto()
    W12 = auto()

    def __eq__(self, other):
        # noinspection PyArgumentList
        return Enum.__eq__(self, other)

    def __lt__(self, other):
        assert isinstance(other, Worker)
        # noinspection PyArgumentList
        return self.value < other.value

    def __hash__(self):
        # noinspection PyArgumentList
        return Enum.__hash__(self)

    def on(
        self,
        coord: "CoordType",
        positions: "Positions",
    ) -> bool:
        return positions[self] == coord

    @staticmethod
    def parse(n: int) -> "ActionComponent":
        return Worker(n)

    @staticmethod
    def space() -> spaces.Discrete:
        return spaces.Discrete(2)  # binary: in or out

    @property
    def symbol(self) -> str:
        return str(self.value)

    def to_int(self) -> int:
        return 0


WorkerGenerator = Generator[Worker, None, None]


@unique
class Resource(WorldObject, Assignment, Enum):
    MINERALS = auto()
    GAS = auto()

    def __hash__(self):
        return Enum.__hash__(self)

    def __eq__(self, other):
        return Enum.__eq__(self, other)

    def execute(
        self,
        positions: "Positions",
        worker: "Worker",
        assignments: "Assignments",
        building_positions: "BuildingPositions",
        pending_positions: "BuildingPositions",
        resources: typing.Counter["Resource"],
        carrying: "Carrying",
    ) -> None:
        worker_pos = positions[worker]

        if carrying[worker] is None:
            resource_pos = positions[self]
            positions[worker] = move_from(worker_pos, toward=resource_pos)
            worker_pos = positions[worker]
            if worker_pos == resource_pos:
                if self is Resource.GAS and not isinstance(
                    building_positions.get(positions[worker]), Assimilator
                ):
                    return  # no op on gas unless Assimilator
                carrying[worker] = self
        else:
            nexus_positions: List[CoordType] = [
                p for p, b in building_positions.items() if isinstance(b, Nexus)
            ]
            nexus = get_nearest(nexus_positions, to=worker_pos)
            positions[worker] = move_from(
                worker_pos,
                toward=nexus,
            )
            if positions[worker] == nexus:
                resource = carrying[worker]
                assert isinstance(resource, Resource)
                resources[resource] += 5
                carrying[worker] = None

    def on(
        self,
        coord: "CoordType",
        positions: "Positions",
    ) -> bool:
        return positions[self] == coord

    @property
    def symbol(self) -> str:
        if self is Resource.GAS:
            return fg("green") + "g" + RESET
        if self is Resource.MINERALS:
            return fg("blue") + "m" + RESET
        raise RuntimeError


@dataclass(frozen=True)
class Resources:
    minerals: int
    gas: int

    def __iter__(self):
        yield from [Resource.MINERALS] * self.minerals
        yield from [Resource.GAS] * self.gas


assert set(Resources(0, 0).__annotations__.keys()) == {
    r.lower() for r in Resource.__members__
}

""" action components """


@dataclass
class Coord(ActionComponent):
    i: int
    j: int

    @staticmethod
    def parse(n: int) -> "ActionComponent":
        assert isinstance(WORLD_SIZE, int)
        ij = np.unravel_index(n, (WORLD_SIZE, WORLD_SIZE))
        return Coord(*ij)

    @staticmethod
    def space() -> spaces.Discrete:
        assert isinstance(WORLD_SIZE, int)
        return spaces.Discrete(WORLD_SIZE ** 2)

    def to_int(self) -> int:
        return int(np.ravel_multi_index((self.i, self.j), (WORLD_SIZE, WORLD_SIZE)))

    @staticmethod
    def zeros() -> IntGenerator:
        yield 0
        yield 0


BuildingPositions = Dict[CoordType, Building]
Positions = Dict[Union[Resource, Worker], CoordType]
Carrying = Dict[Worker, Optional[Resource]]
Assignments = Dict[Worker, Assignment]


@dataclass(frozen=True)
class BuildOrder(Assignment):
    building: Building
    coord: CoordType

    def execute(
        self,
        positions: "Positions",
        worker: "Worker",
        assignments: "Assignments",
        building_positions: "BuildingPositions",
        pending_positions: "BuildingPositions",
        resources: typing.Counter["Resource"],
        carrying: "Carrying",
    ) -> None:
        if positions[worker] == self.coord:
            building_positions[self.coord] = self.building
            assignments[worker] = DoNothing()
        else:
            if self.coord not in pending_positions:
                pending_positions[self.coord] = self.building
                resources.subtract(self.building.cost)
            GoTo(self.coord).execute(
                positions=positions,
                worker=worker,
                assignments=assignments,
                building_positions=building_positions,
                pending_positions=pending_positions,
                resources=resources,
                carrying=carrying,
            )


@dataclass(frozen=True)
class GoTo(Assignment):
    coord: CoordType

    def execute(
        self, positions: "Positions", worker: "Worker", assignments, *args, **kwargs
    ) -> None:
        positions[worker] = move_from(positions[worker], toward=self.coord)


class DoNothing(Assignment):
    def execute(self, *args, **kwargs) -> None:
        pass


Command = Union[BuildOrder, Resource]

O = typing.TypeVar("O", torch.Tensor, np.ndarray, int, gym.Space)


@dataclass(frozen=True)
class Obs(typing.Generic[O]):
    action_mask: O
    gate_openers: O
    line_mask: O
    lines: O
    obs: O
    partial_action: O
    ptr: O
    resources: O


X = typing.TypeVar("X")


@dataclass(frozen=True)
class RawAction:
    delta: Union[np.ndarray, torch.Tensor, X]
    dg: Union[np.ndarray, torch.Tensor, X]
    ptr: Union[np.ndarray, torch.Tensor, X]
    a: Union[np.ndarray, torch.Tensor, X]

    @staticmethod
    def parse(*xs) -> "RawAction":
        delta, dg, ptr, *a = xs
        if a == [None]:
            a = None
        return RawAction(delta, dg, ptr, a)

    def flatten(self) -> Generator[any, None, None]:
        yield from astuple(self)


@dataclass(frozen=True)
class CompoundAction:
    @classmethod
    @abstractmethod
    def _building_active(cls) -> bool:
        pass

    @staticmethod
    @abstractmethod
    def _gate_openers() -> Generator[List[int], None, None]:
        pass

    @classmethod
    @abstractmethod
    def _coord_active(cls) -> bool:
        pass

    def _get_building(self) -> Optional[Building]:
        try:
            # noinspection PyUnresolvedReferences
            return self.building
        except AttributeError:
            return None

    def _get_coord(self) -> Optional[Coord]:
        try:
            # noinspection PyUnresolvedReferences
            return self.coord
        except AttributeError:
            return None

    @classmethod
    def mask(cls) -> np.ndarray:
        def unpadded_generator() -> Generator[List[bool], None, None]:
            for _ in Worker:
                yield [
                    cls._worker_active(),  # worker active: mask no-op
                    *[not cls._worker_active() for _ in range(2)],
                ]
            yield [
                cls._coord_active()
                or cls._building_active(),  # mask if either is active
                *[not cls._coord_active() for _ in range(Coord.space().n)],
                *[not cls._building_active() for _ in range(Building.space().n)],
            ]

        unpadded = [*unpadded_generator()]
        size = max([len(m) for m in unpadded])
        padded = [
            np.pad(
                m, pad_width=[(0, size - len(m))], mode="constant", constant_values=True
            )
            for m in unpadded
        ]
        return np.stack(padded)

    @staticmethod
    @abstractmethod
    def _parse_string(s: str) -> ActionComponentGenerator:
        pass

    @staticmethod
    @abstractmethod
    def _prompt() -> str:
        pass

    def to_ints(self) -> IntGenerator:
        workers = {*self.get_workers()}
        for w in Worker:
            yield int(w in workers)
        building = self._get_building()
        coord = self._get_coord()
        yield 0 if building is None else building.to_int()
        yield 0 if coord is None else coord.to_int()

    @staticmethod
    @abstractmethod
    def _update(a: ActionComponent) -> "CompoundAction":
        pass

    @classmethod
    @abstractmethod
    def _worker_active(cls) -> bool:
        pass

    @abstractmethod
    def assignment(self, positions: Positions) -> Optional[Assignment]:
        pass

    @staticmethod
    def subclasses():
        yield NoWorkersAction
        yield WorkersAction
        yield BuildingAction
        yield CoordAction
        yield BuildingCoordAction

    @classmethod
    @lru_cache
    def gate_openers(cls) -> List[List[int]]:
        def contextualize(partial_opener) -> IntGenerator:
            opener_iter = iter(partial_opener)

            for _ in Worker:
                yield 1 + next(opener_iter) if cls._worker_active() else 0
            yield (
                (1 + next(opener_iter))
                if cls._building_active() or cls._coord_active()
                else 0
            )

        return [list(contextualize(o)) for o in cls._gate_openers()]

    def from_input(self) -> ActionComponentGenerator:
        while True:
            try:
                return self._parse_string(input(self._prompt() + "\n"))
            except ValueError as e:
                print(e)

    def get_workers(self) -> WorkerGenerator:
        try:
            # noinspection PyUnresolvedReferences
            yield from self.workers
        except AttributeError:
            pass

    @classmethod
    def input_space(cls) -> spaces.MultiDiscrete:
        def sizes_gen():
            for _ in Worker:
                yield 3  # no-op, choose, don't choose
            yield Coord.space().n + len(Buildings) + 1  # +1 for no-op

        sizes = [*sizes_gen()]
        return spaces.MultiDiscrete([max(sizes)] * len(sizes))

    @classmethod
    def representation_space(cls) -> spaces.MultiDiscrete:
        return spaces.MultiDiscrete(
            [*(2 for _ in Worker), len(Buildings), Coord.space().n]
        )

    def update(
        self, *components: Union[np.ndarray, Iterable[ActionComponent]]
    ) -> "CompoundAction":
        def components_gen():
            try:
                array = np.array(components) - 1
            except ValueError:
                for component in components:
                    assert isinstance(component, ActionComponent)
                    yield component
                return
            *worker_component, target_component = array
            # -1 to remove no-op
            if self._worker_active():
                for i, w in enumerate(worker_component, 1):
                    if w:
                        yield Worker.parse(i)
            if self._coord_active() and Coord.space().contains(target_component):
                yield Coord.parse(target_component)
            target_component -= Coord.space().n
            if self._building_active() and Building.space().contains(target_component):
                yield Building.parse(target_component)

        return self._update(*components_gen())

    @abstractmethod
    def valid(
        self,
        resources: typing.Counter[Resource],
        dependencies: Dict[Building, Building],
        building_positions: BuildingPositions,
        pending_positions: BuildingPositions,
        positions: Positions,
    ) -> bool:
        pass


class WorkerActive(CompoundAction, ABC):
    @classmethod
    def _building_active(cls) -> bool:
        return False

    @classmethod
    def _coord_active(cls) -> bool:
        return False

    @classmethod
    def _worker_active(cls) -> bool:
        return True


class BuildingCoordActive(CompoundAction, ABC):
    @classmethod
    def _building_active(cls) -> bool:
        return True

    @classmethod
    def _coord_active(cls) -> bool:
        return True

    @classmethod
    def _worker_active(cls) -> bool:
        return False


class CoordActive(CompoundAction, ABC):
    @classmethod
    def _building_active(cls) -> bool:
        return False

    @classmethod
    def _coord_active(cls) -> bool:
        return True

    @classmethod
    def _worker_active(cls) -> bool:
        return False


class CoordCanOpenGate(CompoundAction, ABC):
    @staticmethod
    def _gate_openers() -> Generator[List[int], None, None]:
        assert isinstance(WORLD_SIZE, int)
        coords = [*zip(*itertools.product(range(WORLD_SIZE), range(WORLD_SIZE)))]
        for index in np.ravel_multi_index(coords, (WORLD_SIZE, WORLD_SIZE)):
            yield [index]


@dataclass(frozen=True)
class NoWorkersAction(WorkerActive):
    @staticmethod
    def _gate_openers() -> Generator[List[int], None, None]:
        # selecting no workers is a no-op that allows gate to open
        yield [0] * len(Worker)

    @staticmethod
    def _parse_string(s: str) -> ActionComponentGenerator:
        for i in s.split():
            yield Worker(int(i))

    @staticmethod
    def _prompt() -> str:
        return "Workers:"

    def _update(
        self, *workers: ActionComponent
    ) -> Union["WorkersAction", "NoWorkersAction"]:
        workers = [*workers]
        if not workers:
            return NoWorkersAction()
        return WorkersAction(workers)

    def assignment(self, positions: Positions) -> Optional[Assignment]:
        return DoNothing()

    def valid(
        self,
        resources: typing.Counter[Resource],
        dependencies: Dict[Building, Building],
        building_positions: BuildingPositions,
        pending_positions: BuildingPositions,
        positions: Positions,
    ) -> bool:
        return True


def parse_coord(s):
    i, j = map(int, s.split())
    assert 0 <= i < WORLD_SIZE
    assert 0 <= j < WORLD_SIZE
    return Coord(i, j)


@dataclass(frozen=True)
class WorkersAction(BuildingCoordActive, CoordCanOpenGate):
    workers: List[Worker]

    @classmethod
    def _worker_active(cls) -> bool:
        return False

    @staticmethod
    def _parse_string(s: str) -> ActionComponentGenerator:
        try:
            yield Buildings[int(s)]
        except ValueError:
            yield parse_coord(s)

    @staticmethod
    def _prompt() -> str:
        return "\n".join(
            [f"({i}) {b}" for i, b in enumerate(Buildings)] + ["Coord or Building"]
        )

    def _update(self, *a: ActionComponent) -> "CompoundAction":
        (a,) = a  # accepts only one argument
        if isinstance(a, Coord):
            return CoordAction(workers=self.workers, coord=a)
        elif isinstance(a, Building):
            return BuildingAction(workers=self.workers, building=a)
        else:
            raise RuntimeError

    def assignment(self, positions: Positions) -> Optional[Assignment]:
        return None

    def valid(self, *args, **kwargs) -> bool:
        return True


@dataclass(frozen=True)
class CoordAction(NoWorkersAction):
    workers: List[Worker]
    coord: Coord

    def assignment(self, positions: Positions) -> Optional[Assignment]:
        i, j = astuple(self.coord)
        for resource in Resource:
            if resource.on((i, j), positions):
                return resource
        return GoTo((i, j))

    def valid(self, *args, **kwargs) -> bool:
        return True


@dataclass(frozen=True)
class BuildingAction(CoordActive, CoordCanOpenGate):
    workers: List[Worker]
    building: Building

    @staticmethod
    def _parse_string(s: str) -> ActionComponentGenerator:
        i, j = map(int, s.split())
        yield Coord.parse(int(np.ravel_multi_index((i, j), (WORLD_SIZE, WORLD_SIZE))))

    @staticmethod
    def _prompt() -> str:
        return "Coord"

    def _update(self, *a: ActionComponent) -> "CompoundAction":
        (a,) = a
        assert isinstance(a, Coord)
        return BuildingCoordAction(
            workers=self.workers, building=self.building, coord=a
        )

    @classmethod
    def _worker_active(cls) -> bool:
        return False

    def assignment(self, positions: Positions) -> Optional[Assignment]:
        return None

    def valid(
        self,
        resources: typing.Counter[Resource],
        dependencies: Dict[Building, Building],
        building_positions: BuildingPositions,
        *args,
        **kwargs,
    ) -> bool:
        dependency = dependencies[self.building]
        dependency_met = dependency in [*building_positions.values(), None]
        insufficient_resources = Counter(self.building.cost) - resources
        return dependency_met and not insufficient_resources


@dataclass(frozen=True)
class BuildingCoordAction(NoWorkersAction):
    workers: List[Worker]
    building: Building
    coord: Coord

    def assignment(self, positions: Positions) -> Assignment:
        i, j = astuple(self.coord)
        on_gas = Resource.GAS.on((i, j), positions)
        assimilator = isinstance(self.building, Assimilator)
        assert (on_gas and assimilator) or (not on_gas and not assimilator)
        assert not Resource.MINERALS.on((i, j), positions)
        return BuildOrder(self.building, (i, j))

    def valid(
        self,
        resources: typing.Counter[Resource],
        dependencies: Dict[Building, Building],
        building_positions: BuildingPositions,
        pending_positions: BuildingPositions,
        positions: Positions,
    ) -> bool:
        coord = astuple(self.coord)
        if coord in {**building_positions, **pending_positions}:
            return False
        if isinstance(self.building, Assimilator):
            return coord == positions[Resource.GAS]
        else:
            return coord not in (
                positions[Resource.GAS],
                positions[Resource.MINERALS],
            )


# Check that fields are alphabetical. Necessary because of the way
# that observation gets vectorized.
annotations = Obs.__annotations__
assert tuple(annotations) == tuple(sorted(annotations))


@dataclass(frozen=True)
class Line:
    required: bool
    building: Building


@dataclass
class State:
    action: CompoundAction
    building_positions: Dict[CoordType, Building]
    pointer: int
    positions: Dict[Union[Resource, Worker], CoordType]
    resources: typing.Counter[Resource]
    success: bool
    time_remaining: int


@dataclass
class RecurrentState(Generic[X]):
    a: X
    d: X
    h: X
    dg: X
    p: X
    v: X
    a_probs: X
    d_probs: X
    dg_probs: X


@dataclass
class ParsedInput(Generic[X]):
    obs: X
    actions: X


def get_nearest(
    candidate_positions: List[CoordType],
    to: CoordType,
) -> CoordType:
    nearest = np.argmin(
        np.max(
            np.abs(
                np.expand_dims(np.array(to), 0) - np.stack(candidate_positions),
            ),
            axis=-1,
        )
    )
    return candidate_positions[int(nearest)]


class Assimilator(Building):
    @property
    def cost(self) -> Resources:
        return Resources(minerals=75, gas=0)

    @property
    def symbol(self) -> str:
        return "A"


class CyberneticsCore(Building):
    @property
    def cost(self) -> Resources:
        return Resources(minerals=150, gas=0)

    @property
    def symbol(self) -> str:
        return "CC"


class DarkShrine(Building):
    @property
    def cost(self) -> Resources:
        return Resources(minerals=150, gas=150)

    @property
    def symbol(self) -> str:
        return "DS"


class FleetBeacon(Building):
    @property
    def cost(self) -> Resources:
        return Resources(minerals=300, gas=200)

    @property
    def symbol(self) -> str:
        return "FB"


class Forge(Building):
    @property
    def cost(self) -> Resources:
        return Resources(minerals=150, gas=0)

    @property
    def symbol(self) -> str:
        return "f"


class Gateway(Building):
    @property
    def cost(self) -> Resources:
        return Resources(minerals=150, gas=0)

    @property
    def symbol(self) -> str:
        return "GW"


class Nexus(Building):
    @property
    def cost(self) -> Resources:
        return Resources(minerals=400, gas=0)

    @property
    def symbol(self) -> str:
        return "N"


class PhotonCannon(Building):
    @property
    def cost(self) -> Resources:
        return Resources(minerals=150, gas=0)

    @property
    def symbol(self) -> str:
        return "PC"


class Pylon(Building):
    @property
    def cost(self) -> Resources:
        return Resources(minerals=100, gas=0)

    @property
    def symbol(self) -> str:
        return "P"


class RoboticsBay(Building):
    @property
    def cost(self) -> Resources:
        return Resources(minerals=200, gas=200)

    @property
    def symbol(self) -> str:
        return "RB"


class RoboticsFacility(Building):
    @property
    def cost(self) -> Resources:
        return Resources(minerals=200, gas=100)

    @property
    def symbol(self) -> str:
        return "RF"


class StarGate(Building):
    @property
    def cost(self) -> Resources:
        return Resources(minerals=150, gas=150)

    @property
    def symbol(self) -> str:
        return "SG"


class TemplarArchives(Building):
    @property
    def cost(self) -> Resources:
        return Resources(minerals=150, gas=200)

    @property
    def symbol(self) -> str:
        return "TA"


class TwilightCouncil(Building):
    @property
    def cost(self) -> Resources:
        return Resources(minerals=150, gas=100)

    @property
    def symbol(self) -> str:
        return "TC"


Buildings: List[Building] = [
    Assimilator(),
    CyberneticsCore(),
    DarkShrine(),
    FleetBeacon(),
    Forge(),
    Gateway(),
    Nexus(),
    PhotonCannon(),
    Pylon(),
    RoboticsBay(),
    RoboticsFacility(),
    StarGate(),
    TemplarArchives(),
    TwilightCouncil(),
]
WorldObjects = list(Buildings) + list(Resource) + list(Worker)
