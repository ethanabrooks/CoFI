import copy

from hyperopt import hp

default = {
    "break_on_fail": False,
    "clip_param": 0.2,
    "conv_hidden_size": 64,
    "cuda": True,
    "cuda_deterministic": False,
    "debug": True,
    "entropy_coef": 0.01,
    "env_id": "control-flow",
    "eps": 1e-5,
    "eval_condition_size": False,
    "eval_interval": 100,
    "eval_steps": 500,
    "failure_buffer_size": 500,
    "fuzz": False,
    "gamma": 0.99,
    "gate_coef": 0.01,
    "hidden_size": 256,
    "inventory_hidden_size": 128,
    "kernel_size": 1,
    "learning_rate": 0.003,
    "load_path": None,
    "log_interval": 10,
    "long_jump": False,
    "lower_embed_size": 128,
    "lower_level": None,
    "lower_level_config": None,
    "lower_level_load_path": None,
    "max_eval_lines": 50,
    "max_failure_sample_prob": 0.4,
    "max_grad_norm": 0.5,
    "max_lines": 10,
    "max_loops": 3,
    "max_nesting_depth": 1,
    "max_while_loops": 15,
    "max_world_resamples": 50,
    "min_eval_lines": 1,
    "min_lines": 1,
    "name": "debug_env/debug_search",
    "no_eval": False,
    "no_op_coef": 0,
    "no_op_limit": 40,
    "no_pointer": False,
    "no_roll": False,
    "no_scan": False,
    "normalize": False,
    "num_batch": 1,
    "num_edges": 2,
    "num_iterations": 200,
    "num_layers": 0,
    "num_processes": 150,
    "olsk": False,
    "one_condition": False,
    "ppo_epoch": 3,
    "recurrent": False,
    "reject_while_prob": 0.6,
    "render": False,
    "render_eval": False,
    "save_interval": None,
    "seed": 0,
    "single_control_flow_type": False,
    "stride": 1,
    "subtasks_only": False,
    "synchronous": False,
    "task_embed_size": 64,
    "tau": 0.95,
    "time_to_waste": 0,
    "train_steps": 30,
    "transformer": False,
    "use_gae": False,
    "value_loss_coef": 0.5,
    "world_size": 1,
}

search = copy.deepcopy(default)
search.update(
    conv_hidden_size=hp.choice("conv_hidden_size", [32, 64, 128]),
    entropy_coef=hp.choice("entropy_coef", [0.01, 0.015, 0.02]),
    gate_coef=hp.choice("gate_coef", [0, 0.01, 0.05]),
    hidden_size=hp.choice("hidden_size", [128, 256, 512]),
    inventory_hidden_size=hp.choice("inventory_hidden_size", [64, 128, 256]),
    kernel_size=hp.choice("kernel_size", [1, 2, 3]),
    learning_rate=hp.choice("learning_rate", [0.002, 0.003, 0.004]),
    lower_embed_size=hp.choice("lower_embed_size", [32, 64, 128]),
    max_failure_sample_prob=hp.choice("max_failure_sample_prob", [0.2, 0.3, 0.4]),
    max_while_loops=hp.choice("max_while_loops", [5, 10, 15]),
    no_op_limit=hp.choice("no_op_limit", [20, 30, 40]),
    num_batch=hp.choice("num_batch", [1, 2]),
    num_edges=hp.choice("num_edges", [2, 4, 6]),
    num_processes=hp.choice("num_processes", [50, 100, 150]),
    ppo_epoch=hp.choice("ppo_epoch", [1, 2, 3]),
    reject_while_prob=hp.choice("reject_while_prob", [0.5, 0.6]),
    stride=hp.choice("stride", [1, 2, 3]),
    task_embed_size=hp.choice("task_embed_size", [32, 64, 128]),
    train_steps=hp.choice("train_steps", [20, 25, 30]),
)

debug_search = copy.deepcopy(search)
debug_search.update(
    kernel_size=1,
    stride=1,
    world_size=1,
)
debug_default = copy.deepcopy(default)
debug_default.update(
    kernel_size=1,
    stride=1,
    world_size=1,
)
configs = dict(
    search=search,
    debug_search=debug_search,
    default=default,
    debug_default=debug_default,
)
