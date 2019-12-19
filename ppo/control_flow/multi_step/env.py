from collections import OrderedDict

import numpy as np
from gym import spaces
from rl_utils import hierarchical_parse_args

import ppo.control_flow.env
from ppo import keyboard_control
from ppo.control_flow.env import build_parser, State
from ppo.control_flow.lines import While, EndWhile, Subtask, Padding
from ppo.control_flow.env import Obs


class Env(ppo.control_flow.env.Env):
    targets = ["pig", "sheep", "cat", "greenbot"]
    non_targets = ["ice", "agent"]
    interactions = ["visit", "pickup", "transform"]

    def __init__(self, world_size, num_subtasks, **kwargs):
        assert num_subtasks == len(self.targets) * len(self.interactions)
        super().__init__(num_subtasks=num_subtasks, **kwargs)
        self.world_size = world_size
        self.world_shape = (
            len(self.targets + self.non_targets) + 1,  # last channel for condition
            self.world_size,
            self.world_size,
        )
        self.action_space = spaces.MultiDiscrete(
            np.array([self.num_subtasks + 1, 2 * self.n_lines, 2, 2])
        )
        self.observation_space.spaces.update(
            obs=spaces.Box(low=0, high=1, shape=self.world_shape),
            lines=spaces.MultiDiscrete(
                np.array([[len(self.line_types), num_subtasks]] * self.n_lines)
            ),
        )

    def print_obs(self, obs):
        condition = obs[-1].mean()
        obs = obs[:-1].transpose(1, 2, 0).astype(int)
        grid_size = obs.astype(int).sum(-1).max()  # max objects per grid
        chars = [" "] + [o for o, *_ in self.targets + self.non_targets]
        for i, row in enumerate(obs):
            string = ""
            for j, col in enumerate(row):
                number = col * (1 + np.arange(col.size))
                crop = sorted(number, reverse=True)[:grid_size]
                string += "".join(chars[x] for x in crop) + "|"
            print(string)
            print("-" * len(string))
        print("Condition:", condition)

    def format_line(self, line):
        if type(line) is Subtask:
            return [self.line_types.index(Subtask), line.id]
        else:
            return [self.line_types.index(line), 0]

    def state_generator(self, lines) -> State:
        assert self.max_nesting_depth == 1
        objects = self.targets + self.non_targets
        ice = objects.index("ice")
        agent_pos = self.random.randint(0, self.world_size, size=2)
        agent_id = objects.index("agent")

        def build_world(condition_bit):
            world = np.zeros(self.world_shape)
            for o, p in object_pos + [(agent_id, agent_pos)]:
                world[tuple((o, *p))] = 1
            world[-1] = condition_bit
            return world

        state_iterator = super().state_generator(lines)
        ids = [self.unravel_id(line.id) for line in lines if type(line) is Subtask]
        positions = self.random.randint(0, self.world_size, size=(len(ids), 2))
        object_pos = [(o, tuple(pos)) for (i, o), pos in zip(ids, positions)]
        state = next(state_iterator)
        while True:
            subtask_id = yield state._replace(obs=build_world(state.condition))
            ac, ob = self.unravel_id(subtask_id)

            def pair():
                return ob, tuple(agent_pos)

            def on_object():
                return pair() in object_pos  # standing on the desired object

            correct_id = subtask_id == lines[state.curr].id
            interaction = self.interactions[ac]
            if on_object() and interaction in ("pickup", "transform"):
                object_pos.remove(pair())
                if interaction == "transform":
                    object_pos.append((ice, tuple(agent_pos)))
                state = next(state_iterator)
            else:
                candidates = [np.array(p) for o, p in object_pos if o == ob]
                if candidates:
                    nearest = min(candidates, key=lambda k: np.sum(agent_pos - k))
                    agent_pos += np.clip(nearest - agent_pos, -1, 1)
                    if on_object() and interaction == "visit":
                        state = next(state_iterator)
                elif correct_id:
                    # subtask is impossible
                    state = next(state_iterator)

    def unravel_id(self, subtask_id):
        i = subtask_id // len(self.targets)
        o = subtask_id % len(self.targets)
        return i, o


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser = build_parser(parser)
    parser.add_argument("--world-size", default=4, type=int)
    parser.add_argument("--seed", default=0, type=int)
    args = hierarchical_parse_args(parser)

    def action_fn(string):
        try:
            return int(string), 0
        except ValueError:
            return

    keyboard_control.run(Env(**args, baseline=False), action_fn=action_fn)
