from rl_utils import hierarchical_parse_args

import ppo.agent
import ppo.arguments
from ppo.road_closures.agent import Agent
from ppo.road_closures.env import Env
from ppo.train import Train


def main(log_dir, baseline, seed, **kwargs):
    class _Train(Train):
        def build_agent(self, envs, debug=False, a_equals_p=False, **agent_args):
            if baseline == "default":
                return ppo.agent.Agent(
                    obs_shape=envs.observation_space.shape,
                    action_space=envs.action_space,
                    **agent_args,
                )
            elif baseline == "oh-et-al":
                raise NotImplementedError
            return Agent(
                observation_space=envs.observation_space,
                action_space=envs.action_space,
                debug=debug,
                baseline=baseline,
                a_equals_p=a_equals_p,
                **agent_args,
            )

        @staticmethod
        def make_env(seed, rank, evaluation, env_id, add_timestep, **env_args):
            return Env(**env_args, baseline=baseline == "default", seed=seed + rank)

    _Train(**kwargs, seed=seed, log_dir=log_dir).run()


def build_parser():
    parsers = ppo.arguments.build_parser()
    parser = parsers.main
    parser.add_argument("--no-tqdm", dest="use_tqdm", action="store_false")
    parser.add_argument("--time-limit", type=int, required=True)
    parser.add_argument("--eval-steps", type=int)
    parser.add_argument("--baseline", choices=["oh-et-al", "default", "no-attention"])
    parsers.env.add_argument("--n-states", type=int, required=True)
    parsers.env.add_argument("--flip-prob", type=float, required=True)
    parsers.agent.add_argument("--debug", action="store_true")
    parsers.agent.add_argument("--a-equals-p", action="store_true")
    return parser


if __name__ == "__main__":
    main(**hierarchical_parse_args(build_parser()))