import multiprocessing
import pickle
import sys
from dataclasses import dataclass
from multiprocessing import Queue
from pathlib import Path
from typing import Optional

import hydra
import numpy as np
from hydra.core.config_store import ConfigStore
from omegaconf import DictConfig

import data_types
import debug_env as _debug_env
import env
import osx_queue
import our_agent
import trainer
from aggregator import InfosAggregator
from common.vec_env import VecEnv, VecEnvWrapper
from config import BaseConfig
from data_types import CurriculumSetting
from utils import Discrete
from wrappers import VecPyTorch


@dataclass
class OurConfig(BaseConfig, env.EnvConfig):
    curriculum_level: int = 0
    curriculum_setting_load_path: Optional[str] = None
    curriculum_threshold: float = 0.9
    debug_env: bool = False
    default_initializer: bool = False
    failure_buffer_load_path: Optional[str] = None
    failure_buffer_size: int = 10000
    max_eval_lines: int = 50
    min_eval_lines: int = 1
    conv_hidden_size: int = 100
    debug: bool = False
    gate_coef: float = 0.01
    resources_hidden_size: int = 128
    kernel_size: int = 2
    lower_embed_size: int = 75
    max_curriculum_level: int = 10
    max_lines: int = 10
    min_lines: int = 1
    num_edges: int = 1
    no_pointer: bool = False
    no_roll: bool = False
    no_scan: bool = False
    olsk: bool = False
    stride: int = 1
    task_embed_size: int = 128
    transformer: bool = False


class CurriculumWrapper(VecEnvWrapper):
    def __init__(
        self,
        venv: VecEnv,
        curriculum_setting: CurriculumSetting,
        curriculum_threshold: float,
        log_dir: Path,
        max_curriculum_level: int,
    ):
        super().__init__(venv)
        self.max_curriculum_level = max_curriculum_level
        self.log_dir = log_dir
        self.mean_successes = 0.5
        self.curriculum_threshold = curriculum_threshold
        self.curriculum_iterator = self.curriculum_generator(curriculum_setting)
        next(self.curriculum_iterator)

    def reset(self):
        return self.venv.reset()

    def step_wait(self):
        return self.venv.step_wait()

    def preprocess(self, action):
        return self.venv.preprocess(action)

    def to(self, device):
        return self.venv.to(device)

    def curriculum_generator(self, setting: CurriculumSetting):
        while True:
            if setting.level == self.max_curriculum_level:
                yield setting
                continue
            if setting.n_lines_space.high < setting.max_lines:
                setting = setting.increment_max_lines().increment_level()
                yield setting
            setting = setting.increment_build_tree_depth().increment_level()
            yield setting

    def process_infos(self, infos: InfosAggregator):
        try:
            self.mean_successes += (
                0.1 * np.mean(infos.complete_episodes["success"])
                - 0.9 * self.mean_successes
            )
        except KeyError:
            pass
        if self.mean_successes >= self.curriculum_threshold:
            self.mean_successes = 0.5
            curriculum = next(self.curriculum_iterator)
            self.set_curriculum(curriculum)
            with Path(self.log_dir, "curriculum_setting.pkl").open("wb") as f:
                pickle.dump(curriculum, f)

    def set_curriculum(self, curriculum: CurriculumSetting):
        self.venv.set_curriculum(curriculum)


class Trainer(trainer.Trainer):
    @classmethod
    def args_to_methods(cls):
        mapping = super().args_to_methods()
        mapping["env_args"] += [
            env.Env.__init__,
            CurriculumWrapper.__init__,
            trainer.Trainer.make_vec_envs,
        ]
        mapping["agent_args"] += [our_agent.Agent.__init__]
        return mapping

    @staticmethod
    def build_agent(envs: VecPyTorch, **agent_args):
        return our_agent.Agent(
            observation_space=envs.observation_space,
            action_space=envs.action_space,
            **agent_args,
        )

    @classmethod
    def initial_curriculum(cls, min_lines, max_lines, debug_env):
        return CurriculumSetting(
            max_build_tree_depth=1000,
            max_lines=max_lines,
            n_lines_space=Discrete(min_lines, max_lines),
            level=0,
        )

    @staticmethod
    def make_env(
        rank: int,
        seed: int,
        debug_env=False,
        env_id=None,
        **kwargs,
    ):
        kwargs.update(rank=rank, random_seed=seed + rank)
        if debug_env:
            return _debug_env.Env(**kwargs)
        else:
            return env.Env(**kwargs)

    # noinspection PyMethodOverriding
    @classmethod
    def make_vec_envs(
        cls,
        curriculum_level: int,
        curriculum_setting_load_path: Optional[str],
        curriculum_threshold: float,
        debug_env: bool,
        evaluating: bool,
        failure_buffer_load_path: Path,
        failure_buffer_size: int,
        log_dir: Path,
        max_curriculum_level: int,
        max_eval_lines: int,
        max_lines: int,
        min_eval_lines: int,
        min_lines: int,
        world_size: int,
        **kwargs,
    ):
        data_types.WORLD_SIZE = world_size
        assert min_lines >= 1
        assert max_lines >= min_lines
        if curriculum_setting_load_path:
            with open(curriculum_setting_load_path, "rb") as f:
                curriculum_setting = pickle.load(f)
                print(
                    f"Loaded curriculum setting {curriculum_setting} "
                    f"from {curriculum_setting_load_path}"
                )
        elif evaluating:
            curriculum_setting = CurriculumSetting(
                max_build_tree_depth=100,
                max_lines=max_eval_lines,
                n_lines_space=Discrete(min_eval_lines, max_eval_lines),
                level=0,
            )

        else:
            curriculum_setting = cls.initial_curriculum(min_lines, max_lines, debug_env)

        kwargs.update(
            curriculum_setting=curriculum_setting,
            world_size=world_size,
        )

        if failure_buffer_load_path:
            with failure_buffer_load_path.open("rb") as f:
                failure_buffer = pickle.load(f)
                assert isinstance(failure_buffer, Queue)
                print(
                    f"Loaded failure buffer of length {failure_buffer.qsize()} "
                    f"from {failure_buffer_load_path}"
                )
        else:
            failure_buffer = Queue(maxsize=failure_buffer_size)
            try:
                failure_buffer.qsize()
            except NotImplementedError:
                failure_buffer = osx_queue.Queue()
        venv = super().make_vec_envs(
            evaluating=evaluating,
            non_pickle_args=dict(failure_buffer=failure_buffer),
            debug_env=debug_env,
            **kwargs,
        )
        venv = CurriculumWrapper(
            venv=venv,
            curriculum_setting=curriculum_setting,
            curriculum_threshold=curriculum_threshold,
            log_dir=log_dir,
            max_curriculum_level=0,
        )
        for _ in range(curriculum_level - curriculum_setting.level):
            curriculum_setting = next(venv.curriculum_iterator)
            venv.set_curriculum(curriculum_setting)
        print(f"starting at curriculum: {curriculum_setting}")
        with Path(log_dir, "curriculum_setting.pkl").open("wb") as f:
            pickle.dump(curriculum_setting, f)
        return venv


@hydra.main(config_name="config")
def app(cfg: DictConfig) -> None:
    Trainer.main(cfg)


if __name__ == "__main__":
    if sys.platform == "darwin":
        multiprocessing.set_start_method("fork")  # needed for osx_queue.Queue

    cs = ConfigStore.instance()
    cs.store(name="config", node=OurConfig)
    app()
