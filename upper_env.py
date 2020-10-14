import copy
import json
import pickle
from collections import Counter, namedtuple, deque, OrderedDict
from itertools import product, zip_longest
from pathlib import Path
from pprint import pprint
from typing import Tuple, Dict, Union

import gym
import numpy as np
from colored import fg
from gym import spaces
from gym.utils import seeding

from enums import (
    Terrain,
    Other,
    Refined,
    InventoryItems,
    WorldObjects,
    Necessary,
    Interaction,
    Resource,
    Symbols,
    ResourceInteractions,
)
from lines import Subtask
from utils import RESET

Coord = Tuple[int, int]
ObjectMap = Dict[Coord, str]
Last = namedtuple("Last", "action active reward terminal selected")
Action = namedtuple("Action", "upper lower delta dg ptr")
CrossWater = Subtask(Interaction.CROSS, Terrain.WATER)
CrossMountain = Subtask(Interaction.CROSS, Terrain.MOUNTAIN)
Obs = namedtuple("Obs", "inventory lines mask obs")
assert tuple(Obs._fields) == tuple(sorted(Obs._fields))


def delete_nth(d, n):
    d.rotate(-n)
    d.popleft()
    d.rotate(n)


def subtasks():
    yield CrossWater
    yield CrossMountain
    for interaction in ResourceInteractions:
        for resource in Resource:
            yield Subtask(interaction, resource)


def lower_level_actions():
    yield Interaction.COLLECT
    for resource in Resource:
        yield resource  # REFINE
    for i in range(-1, 2):
        for j in range(-1, 2):
            if [i, j].count(0) == 1:
                yield np.array([i, j])


class Env(gym.Env):
    def __init__(
        self,
        bandit_prob: float,
        break_on_fail: bool,
        bridge_failure_prob: float,
        failure_buffer_load_path: Path,
        failure_buffer_size: int,
        map_discovery_prob: float,
        max_eval_lines: int,
        max_lines: int,
        min_eval_lines: int,
        min_lines: int,
        no_op_limit: int,
        rank: int,
        room_side: int,
        seed: int,
        tgt_success_rate: int,
        windfall_prob: float,
        evaluating=False,
    ):
        self.windfall_prob = windfall_prob
        self.bandit_prob = bandit_prob
        self.map_discovery_prob = map_discovery_prob
        self.bridge_failure_prob = bridge_failure_prob
        self.counts = None
        self.tgt_success_rate = tgt_success_rate

        self.subtasks = list(subtasks())
        self.block_subtasks = [
            s for s in self.subtasks if s.interaction in ResourceInteractions
        ]
        num_subtasks = len(self.subtasks)
        self.min_eval_lines = min_eval_lines
        self.max_eval_lines = max_eval_lines
        self.rank = rank
        self.break_on_fail = break_on_fail
        self.no_op_limit = no_op_limit
        self.num_subtasks = num_subtasks
        self.i = 0
        self.success_avg = 0.5
        self.alpha = 0.05

        self.min_lines = min_lines
        self.max_lines = max_lines
        if evaluating:
            self.n_lines = max_eval_lines
        else:
            self.n_lines = max_lines
        self.n_lines += 1
        self.random, self.seed = seeding.np_random(seed)
        self.failure_buffer = deque(maxlen=failure_buffer_size)
        if failure_buffer_load_path:
            with failure_buffer_load_path.open("rb") as f:
                self.failure_buffer.extend(pickle.load(f))
                print(
                    f"Loaded failure buffer of length {len(self.failure_buffer)} from {failure_buffer_load_path}"
                )
        self.non_failure_random = self.random.get_state()
        self.evaluating = evaluating
        self.h, self.w = self.room_shape = np.array([room_side, room_side])
        self.room_size = int(self.room_shape.prod())
        self.chunk_size = self.room_size - self.h - 1
        self.limina = [Terrain.WATER] + [Terrain.MOUNTAIN] * (self.h - 1)
        self.iterator = None
        self.render_thunk = None

        self.lower_level_actions = list(lower_level_actions())
        self.action_space = spaces.MultiDiscrete(
            np.array(
                Action(
                    upper=num_subtasks + 1,
                    delta=2 * self.n_lines,
                    dg=2,
                    lower=len(self.lower_level_actions),
                    ptr=self.n_lines,
                )
            )
        )
        self.line_space = [1 + len(Interaction), 2 + len(Resource)]
        lines_space = spaces.MultiDiscrete(np.array([self.line_space] * self.n_lines))
        mask_space = spaces.MultiDiscrete(2 * np.ones(self.n_lines))

        self.room_space = spaces.Box(
            low=np.zeros_like(self.room_shape, dtype=np.float32),
            high=(self.room_shape - 1).astype(np.float32),
        )

        inventory_space = spaces.MultiBinary(len(InventoryItems))
        shape = (len(Resource) + len(Terrain) + 1, *self.room_shape)
        obs_space = spaces.Box(
            low=np.zeros(shape, dtype=np.float32),
            high=np.ones(shape, dtype=np.float32),
        )
        self.observation_space = spaces.Dict(
            Obs(
                inventory=inventory_space,
                lines=lines_space,
                mask=mask_space,
                obs=obs_space,
            )._asdict()
        )

    def reset(self):
        self.i += 1
        self.iterator = self.failure_buffer_wrapper(self.srti_generator())
        s, r, t, i = next(self.iterator)
        return s

    def step(self, action: Union[np.ndarray, Action]):
        action = Action(*action)
        return self.iterator.send(
            action._replace(lower=self.lower_level_actions[int(action.lower)])
        )

    def failure_buffer_wrapper(self, iterator):
        if self.evaluating or len(self.failure_buffer) == 0:
            buf = False
        else:
            use_failure_prob = 1 - self.tgt_success_rate / self.success_avg
            use_failure_prob = max(use_failure_prob, 0)
            buf = self.random.random() < use_failure_prob
        use_failure_buf = buf
        if use_failure_buf:
            i = self.random.choice(len(self.failure_buffer))
            self.random.set_state(self.failure_buffer[i])
            delete_nth(self.failure_buffer, i)
        else:
            self.random.set_state(self.non_failure_random)
        initial_random = self.random.get_state()
        action = None
        render_thunk = lambda: None

        def render():
            render_thunk()
            if use_failure_buf:
                print(fg("red"), "Used failure buffer", RESET)
            else:
                print(fg("blue"), "Did not use failure buffer", RESET)

        while True:
            s, r, t, i = iterator.send(action)
            render_thunk = self.render_thunk
            self.render_thunk = render
            if not use_failure_buf:
                i.update(reward_without_failure_buf=r)
            if t:
                success = i["success"]
                if not use_failure_buf:
                    i.update(success_without_failure_buf=float(success))
                self.success_avg += self.alpha * (success - self.success_avg)

                i.update(
                    use_failure_buf=use_failure_buf,
                )
                if not self.evaluating:
                    i.update(failure_buffer=list(self.failure_buffer)[:2])

                if not success:
                    self.failure_buffer.append(initial_random)

            if t:
                self.non_failure_random = self.random.get_state()
            action = yield s, r, t, i

    @staticmethod
    def get_lines(*blocks):
        for block in blocks:
            for subtask in block:
                yield subtask
            yield CrossWater

    def srti_generator(self):
        blocks = self.build_blocks()
        rooms = self.build_rooms(*blocks)
        assert len(rooms) == len(blocks)

        lines = list(self.get_lines(*blocks))
        obs_iterator = self.obs_generator(*lines)
        reward_iterator = self.reward_generator()
        done_iterator = self.done_generator(*lines)
        info_iterator = self.info_generator(lines, rooms)
        state_iterator = self.state_generator(*blocks)
        next(obs_iterator)
        next(reward_iterator)
        next(done_iterator)
        next(info_iterator)
        action = None

        def no_op():
            return action is not None and action.upper == len(self.subtasks)

        def render():
            if t:
                print(fg("green") if i["success"] else fg("red"))
            render_r()
            render_t()
            render_i()
            render_state()
            print("Action:", end=" ")
            if action is None:
                print(None)
            elif no_op():
                print("No op")
            else:
                # noinspection PyProtectedMember
                print(action._replace(upper=str(self.subtasks[int(action.upper)])))
            render_s()
            print(RESET)

        while True:
            if no_op():
                continue
            state, render_state = state_iterator.send(action)
            s, render_s = obs_iterator.send(state)
            r, render_r = reward_iterator.send(state)
            t, render_t = done_iterator.send(dict(state))
            i, render_i = info_iterator.send(dict(state, done=t))

            if self.break_on_fail and t and not i["success"]:
                import ipdb

                ipdb.set_trace()

            self.render_thunk = render

            action = yield s, r, t, i

    def state_generator(self, *blocks):
        rooms = self.build_rooms(*blocks)
        assert len(rooms) == len(blocks)
        rooms_iter = iter(rooms)
        blocks_iter = iter(blocks)

        def next_required():
            block = next(blocks_iter, None)
            if block is not None:
                for subtask in block:
                    if subtask.interaction == Interaction.COLLECT:
                        yield subtask.resource
                    elif subtask.interaction == Interaction.REFINE:
                        yield Refined(subtask.resource.value)
                    else:
                        assert subtask.interaction == Interaction.BUILD

        required = Counter(next_required())
        objects = dict(next(rooms_iter))
        agent_pos = int(self.random.choice(self.h)), int(self.random.choice(self.w - 1))
        build_supplies = Counter()
        inventory = self.initialize_inventory()
        success = False
        action = None
        subtasks_completed = set()
        room_complete = False
        should_cross_mountain = False

        while True:
            self.make_feasible(objects)

            state = dict(
                inventory=inventory,
                agent_pos=agent_pos,
                objects=objects,
                action=action,
                success=success,
                subtasks_completed=subtasks_completed,
                room_complete=room_complete,
                required=required,
                should_cross_mountain=should_cross_mountain,
            )

            def render():
                print("Inventory:")
                pprint(inventory)
                print("Required:")
                pprint(required)

            self.render_thunk = render
            # for name, space in self.observation_space.spaces.items():
            #     if not space.contains(s[name]):
            #         import ipdb
            #
            #         ipdb.set_trace()
            #         space.contains(s[name])
            action = yield state, render
            subtasks_completed = set()
            room_complete = False
            if self.random.random() < self.bandit_prob:
                possessions = [k for k, v in build_supplies.items() if v > 0]
                if possessions:
                    robbed = self.random.choice(possessions)
                    build_supplies[robbed] -= 1

            standing_on = objects.get(tuple(agent_pos), None)
            if isinstance(action.lower, np.ndarray):
                new_pos = agent_pos + action.lower
                moving_into = objects.get(tuple(new_pos), None)

                if moving_into == Terrain.WATER:
                    for item in inventory:
                        if isinstance(item, Resource):
                            subtasks_completed.add(Subtask(Interaction.COLLECT, item))
                        if isinstance(item, Refined):
                            subtasks_completed.add(Subtask(Interaction.REFINE, item))
                    build_supplies.update(inventory)
                    inventory = set()

                def next_room():
                    h, w = new_pos
                    return w == self.w

                def valid_new_pos():
                    if not self.room_space.contains(new_pos):
                        return next_room()
                    if moving_into == Terrain.WALL:
                        return False
                    if moving_into == Terrain.WATER:
                        return not (required - build_supplies)
                        # inventory dominates required
                    if moving_into == Terrain.MOUNTAIN:
                        return Other.MAP in inventory
                    return True

                if valid_new_pos():
                    if moving_into == Terrain.WATER:
                        build_supplies -= required  # build bridge
                        if self.random.random() > self.bridge_failure_prob:
                            agent_pos = new_pos  # check for "flash flood"
                        subtasks_completed.add(CrossWater)
                        # else bridge failed
                    else:
                        agent_pos = new_pos % np.array(self.room_shape)
                        if moving_into == Terrain.MOUNTAIN:
                            inventory.remove(Other.MAP)
                            subtasks_completed.add(CrossWater)
                        if next_room():
                            room = next(rooms_iter, None)
                            room_complete = True
                            subtask_complete = True
                            should_cross_mountain = False
                            if room is None:
                                success = True
                            else:
                                objects = dict(room)
                            required = Counter(next_required())
            elif action.lower == Interaction.COLLECT:
                if standing_on in list(Resource):
                    inventory.add(standing_on)
                    del objects[tuple(agent_pos)]
                    if self.random.random() < self.map_discovery_prob:
                        should_cross_mountain = True
                        inventory.add(Other.MAP)
            elif isinstance(action.lower, Resource):
                if standing_on == Terrain.FACTORY:
                    if action.lower in inventory:
                        inventory.add(Refined(action.lower.value))
            else:
                raise NotImplementedError

    @staticmethod
    def initialize_inventory():
        return set()

    def obs_generator(self, *lines):
        state = yield
        inventory = state["inventory"]
        padded = list(lines) + [None] * (self.n_lines - len(lines))

        def build_array(agent_pos, objects, **_):
            room = np.zeros((len(WorldObjects), *self.room_shape))
            for p, o in list(objects.items()):
                p = np.array(p)
                room[(WorldObjects.index(o), *p)] = 1
            room[(WorldObjects.index(Other.AGENT), *agent_pos)] = 1
            return room

        def render(action, **_):
            for i, line in enumerate(lines):
                agent_ptr = None if action is None else action.ptr
                # if i == ptr == agent_ptr:
                #     pre = "+ "
                # elif i == ptr:
                #     pre = "| "
                if i == agent_ptr:
                    pre = "- "
                else:
                    pre = "  "
                index = [(s.interaction, s.resource) for s in self.subtasks].index(
                    (line.interaction, line.resource)
                )
                print("{:2}{}{} ({}) {}".format(i, pre, " ", index, str(line)))
            print("Obs:")
            for string in self.room_strings(array):
                print(string, end="")

        while True:
            array = build_array(**state)
            obs = OrderedDict(
                Obs(
                    obs=array,
                    lines=[self.preprocess_line(l) for l in padded],
                    mask=[p is None for p in padded],
                    inventory=self.inventory_representation(inventory),
                )._asdict()
            )
            state = yield obs, lambda: render(**state)  # perform time-step
            inventory = state["inventory"]

    @staticmethod
    def reward_generator():
        reward = -0.1
        while True:
            yield reward, lambda: print("Reward:", reward)

    def no_op_remaining_generator(self):
        no_ops_remaining = self.no_op_limit
        while True:
            action = yield no_ops_remaining
            if action == len(self.subtasks):
                no_ops_remaining -= 1
            no_ops_remaining -= 1

    def done_generator(self, *lines):
        state = yield
        time_remaining = len(lines) * self.time_per_subtask()

        while True:
            done = state["success"]
            if not self.evaluating:
                time_remaining -= 1
                done |= time_remaining == 0
            state = yield done, lambda: print("Time remaining:", time_remaining)

    def info_generator(self, lines, rooms):
        state = yield
        info = dict(len_failure_buffer=len(self.failure_buffer))
        rooms_complete = 0

        def update_info(success, done, **_):
            if done:
                info.update(
                    instruction_len=len(lines),
                    len_failure_buffer=len(self.failure_buffer),
                    rooms_complete=rooms_complete,
                    progress=rooms_complete / len(rooms),
                    success=float(success),
                )

        while True:
            rooms_complete += int(state["room_complete"])
            update_info(**state)
            # line_specific_info = {
            #     f"{k}_{10 * (len(blocks) // 10)}": v for k, v in info.items()
            # }
            state = yield info, lambda: None
            info = {}

    def time_per_subtask(self):
        return 2 * (self.room_shape.sum() - 1)

    @staticmethod
    def preprocess_line(line):
        if isinstance(line, Subtask):
            if line.resource is None:
                resource_code = len(Resource)
            else:
                resource_code = line.resource.value
            return [line.interaction.value, resource_code]
        elif line is None:
            return [0, 0]
        else:
            raise RuntimeError

    def room_strings(self, room):
        for i, row in enumerate(room.transpose((1, 2, 0)).astype(int)):
            for j, channel in enumerate(row):
                (nonzero,) = channel.nonzero()
                assert len(nonzero) <= 2
                for _, i in zip_longest(range(2), nonzero):
                    if i is None:
                        yield " "
                    else:
                        world_obj = WorldObjects[i]
                        yield Symbols[world_obj]
                yield RESET
                yield "|"
            yield "\n" + "-" * 3 * self.w + "\n"

    def make_feasible(self, objects):
        counts = Counter(objects.values())
        if any(counts[o] == 0 for o in Necessary):

            def get_free_space():
                for i in range(self.h):
                    for j in range(self.w):
                        maybe_object = objects.get((i, j), None)
                        if maybe_object is None or (
                            maybe_object not in self.limina and counts[maybe_object] > 1
                        ):
                            yield i, j

            free_space = list(get_free_space())
            assert free_space

            for o in Necessary:
                if counts[o] == 0:
                    coord = free_space[self.random.choice(len(free_space))]
                    objects[coord] = o
                    counts = Counter(objects.values())
                    free_space = list(get_free_space())

    def build_rooms(self, *blocks):
        n_rooms = len(blocks)
        assert n_rooms > 0
        h, w = self.room_shape
        coordinates = list(product(range(h), range(w - 1)))

        def get_objects():
            max_objects = len(coordinates)
            num_objects = self.random.choice(max_objects)
            h, w = self.room_shape
            positions = [
                coordinates[i]
                for i in self.random.choice(len(coordinates), size=num_objects)
            ] + [(i, w - 1) for i in range(h)]
            limina = copy.deepcopy(self.limina)
            self.random.shuffle(limina)
            assert limina.count(Terrain.WATER) == 1
            world_objects = (
                list(self.random.choice(Necessary, size=num_objects)) + limina
            )
            assert len(positions) == len(world_objects)
            return list(zip(positions, world_objects))

        rooms = [get_objects() for _ in range(n_rooms)]
        return rooms

    def build_blocks(self):
        n_lines = (
            self.random.random_integers(self.min_eval_lines, self.max_eval_lines)
            if self.evaluating
            else self.random.random_integers(self.min_lines, self.max_lines)
        )

        def get_blocks():
            i = n_lines
            while i > 0:
                size = self.random.choice(self.chunk_size)
                block = self.random.choice(self.block_subtasks, size=size)
                block = block[: i - 1]  # for CrossWater
                yield block
                i -= len(block) + 1  # for CrossWater

        blocks = list(get_blocks())
        return blocks

    @staticmethod
    def inventory_representation(inventory):
        return np.array([int(i in inventory) for i in InventoryItems])

    def seed(self, seed=None):
        assert self.seed == seed

    def render(self, mode="human", pause=True):
        self.render_thunk()
        if pause:
            input("pause")

    def main(self, lower_level_config, lower_level_load_path):
        import lower_env
        from lower_agent import Agent
        import torch
        import time

        lower_level_params = dict(
            hidden_size=128,
            kernel_size=1,
            num_conv_layers=1,
            stride=1,
            recurrent=False,
            concat=False,
        )
        if lower_level_config:
            with open(lower_level_config) as f:
                params = json.load(f)
                lower_level_params = {
                    k: v for k, v in params.items() if k in lower_level_params.keys()
                }
        lower_level = Agent(
            obs_spaces=lower_env.Env.observation_space_from_upper(
                self.observation_space
            ),
            entropy_coef=0,
            action_space=spaces.Discrete(Action(*self.action_space.nvec).lower),
            num_layers=1,
            **lower_level_params,
        )
        state_dict = torch.load(lower_level_load_path, map_location="cpu")
        lower_level.load_state_dict(state_dict["agent"])
        print(f"Loaded lower_level from {lower_level_load_path}.")
        subtask_list = list(subtasks())

        def action_fn(string):
            try:
                return int(string)
            except ValueError:
                return

        s = self.reset()
        while True:
            s = Obs(**s)
            self.render(pause=False)
            upper = None
            while upper is None:
                for i, subtask in enumerate(subtasks()):
                    print(i, str(subtask))
                upper = action_fn(input("act:"))
            lower = lower_level(
                lower_env.Obs(
                    inventory=torch.from_numpy(s.inventory).float().unsqueeze(0),
                    obs=torch.from_numpy(s.obs).float().unsqueeze(0),
                    line=torch.Tensor(self.preprocess_line(subtask_list[upper]))
                    .float()
                    .unsqueeze(0),
                ),
                None,
                None,
            ).action
            print(lower)
            action = Action(upper=upper, lower=lower, delta=0, dg=0, ptr=0)

            s, r, t, i = self.step(action)
            print("reward", r)
            if t:
                self.render(pause=False)
                print("resetting")
                time.sleep(0.5)
                self.reset()
                print()

    @classmethod
    def add_arguments(cls, p):
        p.add_argument("--min-lines", type=int)
        p.add_argument("--max-lines", type=int)
        p.add_argument("--no-op-limit", type=int)
        p.add_argument("--break-on-fail", action="store_true")
        p.add_argument("--tgt-success-rate", type=float)
        p.add_argument("--failure-buffer-size", type=int)
        p.add_argument("--room-side", type=int)
        p.add_argument("--bridge-failure-prob", type=float)
        p.add_argument("--map-discovery-prob", type=float)
        p.add_argument("--bandit-prob", type=float)
        p.add_argument("--windfall-prob", type=float)
        p.add_argument("--failure-buffer-load-path", type=Path, default=None)


def main(lower_level_load_path, lower_level_config, **kwargs):
    Env(rank=0, min_eval_lines=0, max_eval_lines=10, **kwargs).main(
        lower_level_load_path=lower_level_load_path,
        lower_level_config=lower_level_config,
    )


if __name__ == "__main__":
    import argparse

    PARSER = argparse.ArgumentParser()
    Env.add_arguments(PARSER)
    PARSER.add_argument("--seed", default=0, type=int)
    PARSER.add_argument("--lower-level-config", default="lower.json")
    PARSER.add_argument("--lower-level-load-path", default="lower.pt")
    main(**vars(PARSER.parse_args()))