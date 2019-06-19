# stdlib

# noinspection PyUnresolvedReferences
from collections import ChainMap
from pathlib import Path
from pprint import pprint

import torch
from gym.wrappers import TimeLimit
from rl_utils import hierarchical_parse_args

import gridworld_env
from gridworld_env.subtasks_gridworld import SubtasksGridWorld, get_task_space
from ppo.arguments import build_parser, get_args
from ppo.student import SubtasksStudent
from ppo.subtasks import SubtasksAgent
from ppo.teacher import SubtasksTeacher
from ppo.train import Train
from ppo.wrappers import SubtasksWrapper, VecNormalize


def cli():
    Train(**get_args())


def class_parser(string):
    return dict(SubtasksGridWorld=SubtasksGridWorld)[string]


def make_subtasks_env(env_id, **kwargs):
    def helper(seed, rank, class_, max_episode_steps, **_kwargs):
        if rank == 1:
            print('Environment args:')
            pprint(_kwargs)
        env = SubtasksWrapper(class_parser(class_)(**_kwargs))
        env.seed(seed + rank)
        print('Environment seed:', seed + rank)
        if max_episode_steps is not None:
            env = TimeLimit(env, max_episode_steps=int(max_episode_steps))
        return env

    gridworld_args = gridworld_env.get_args(env_id)
    kwargs.update(add_timestep=None)
    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    return helper(**ChainMap(
        kwargs, gridworld_args
    ))  # combines kwargs and gridworld_args with preference for kwargs


def train_skill_cli(student):
    parser = build_parser()
    task_parser = parser.add_argument_group('task_args')
    task_parser.add_argument('--task-types', nargs='*')
    task_parser.add_argument('--max-task-count', type=int, required=True)
    task_parser.add_argument('--object-types', nargs='*')
    task_parser.add_argument('--n-subtasks', type=int, required=True)
    parser.add_argument('--n-objects', type=int, required=True)
    parser.add_argument('--max-episode-steps', type=int)
    if student:
        parser.add_argument('--embedding-dim', type=int, required=True)
        parser.add_argument('--tau-diss', type=float, required=True)
        parser.add_argument('--tau-diff', type=float, required=True)
        parser.add_argument('--xi', type=float, required=True)
    kwargs = hierarchical_parse_args(parser)

    def train(task_args,
              n_objects,
              max_episode_steps,
              embedding_dim=None,
              tau_diss=None,
              tau_diff=None,
              xi=None,
              **_kwargs):
        class TrainSkill(Train):
            @staticmethod
            def make_env(env_id, seed, rank, add_timestep):
                return make_subtasks_env(
                    env_id=env_id,
                    rank=rank,
                    seed=seed,
                    n_objects=n_objects,
                    max_episode_steps=max_episode_steps,
                    **task_args)

            @staticmethod
            def build_agent(envs, **agent_args):
                agent_args = dict(
                    obs_shape=envs.observation_space.shape,
                    action_space=envs.action_space,
                    task_space=get_task_space(**task_args),
                    **agent_args)
                if student:
                    return SubtasksStudent(
                        **agent_args,
                        embedding_dim=embedding_dim,
                        xi=xi,
                        tau_diff=tau_diff,
                        tau_diss=tau_diss)
                else:
                    return SubtasksTeacher(**agent_args)

        TrainSkill(**_kwargs)

    train(**kwargs)


def train_teacher_cli():
    train_skill_cli(student=False)


def train_student_cli():
    train_skill_cli(student=True)


def teach_cli():
    parser = build_parser()
    parser.add_argument('--agent-load-path', type=Path)
    task_parser = parser.add_argument_group('task_args')
    task_parser.add_argument('--task-types', nargs='*')
    task_parser.add_argument('--max-task-count', type=int, required=True)
    task_parser.add_argument('--object-types', nargs='*')
    task_parser.add_argument('--n-subtasks', type=int, required=True)
    subtasks_parser = parser.add_argument_group('subtasks_args')
    subtasks_parser.add_argument(
        '--subtasks-hidden-size', type=int, required=True)
    subtasks_parser.add_argument(
        '--subtasks-entropy-coef', type=float, default=0.01)
    subtasks_parser.add_argument('--alpha', type=float, default=0.03)
    subtasks_parser.add_argument('--zeta', type=float, default=.0001)
    subtasks_parser.add_argument('--subtasks-recurrent', action='store_true')
    subtasks_parser.add_argument('--hard-update', action='store_true')
    subtasks_parser.add_argument(
        '--multiplicative-interaction', action='store_true')
    parser.add_argument('--n-objects', type=int, required=True)
    parser.add_argument('--max-episode-steps', type=int)

    def train(env_id, task_args, ppo_args, agent_load_path, subtasks_args,
              n_objects, max_episode_steps, **kwargs):
        task_space = get_task_space(**task_args)

        class TrainSubtasks(Train):
            @staticmethod
            def make_env(**_kwargs):
                return make_subtasks_env(
                    max_episode_steps=max_episode_steps,
                    n_objects=n_objects,
                    **_kwargs,
                    **task_args)

            # noinspection PyMethodOverriding
            @staticmethod
            def build_agent(envs, **agent_args):
                agent = None
                if agent_load_path:
                    agent = SubtasksTeacher(
                        obs_shape=envs.observation_space.shape,
                        action_space=envs.action_space,
                        task_space=task_space,
                        **agent_args)

                    state_dict = torch.load(agent_load_path)
                    agent.load_state_dict(state_dict['agent'])
                    if isinstance(envs.venv, VecNormalize):
                        envs.venv.load_state_dict(state_dict['vec_normalize'])
                    print(f'Loaded teacher parameters from {agent_load_path}.')

                _subtasks_args = {
                    k.replace('subtasks_', ''): v
                    for k, v in subtasks_args.items()
                }

                return SubtasksAgent(
                    obs_shape=envs.observation_space.shape,
                    action_space=envs.action_space,
                    task_space=task_space,
                    agent=agent,
                    **_subtasks_args)

        # ppo_args.update(aux_loss_only=True)
        TrainSubtasks(env_id=env_id, ppo_args=ppo_args, **kwargs)

    train(**(hierarchical_parse_args(parser)))


if __name__ == "__main__":
    train_teacher_cli()
