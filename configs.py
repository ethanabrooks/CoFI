import copy

from hyperopt import hp

default = {
    "clip_param": 0.2,
    "cuda": True,
    "cuda_deterministic": False,
    "entropy_coef": 0.015,
    "eps": 1e-05,
    "eval_interval": None,
    "eval_steps": None,
    "gamma": 0.99,
    "hidden_size": 256,
    "learning_rate": 0.004,
    "load_path": None,
    "log_interval": 20000,
    "max_grad_norm": 0.5,
    "no_eval": False,
    "normalize": False,
    "num_batch": 2,
    "num_frames": 30000000,
    "num_layers": 1,
    "num_processes": 150,
    "ppo_epoch": 1,
    "recurrent": False,
    "render": False,
    "render_eval": False,
    "save_interval": 20000,
    "seed": 0,
    "synchronous": False,
    "tau": 0.95,
    "train_steps": 25,
    "use_gae": False,
    "value_loss_coef": 0.5,
}

search = copy.deepcopy(default)
search.update(
    entropy_coef=hp.choice("entropy_coef", [0.01, 0.015, 0.02]),
    hidden_size=hp.choice("hidden_size", [128, 256, 512]),
    learning_rate=hp.choice("learning_rate", [0.002, 0.003, 0.004]),
    num_batch=hp.choice("num_batch", [1, 2]),
    num_processes=hp.choice("num_processes", [50, 100, 150]),
    ppo_epoch=hp.choice("ppo_epoch", [1, 2, 3]),
    train_steps=hp.choice("train_steps", [20, 25, 30]),
    use_gae=hp.choice("use_gae", [True, False]),
)


starcraft_default = {
    "break_on_fail": False,
    "clip_param": 0.2,
    "control_flow_types": None,
    "conv_hidden_size": 128,
    "cuda": True,
    "cuda_deterministic": False,
    "debug": False,
    "debug_env": True,
    "entropy_coef": 0.015,
    "env_id": "control-flow",
    "eps": 1e-5,
    "eval_condition_size": False,
    "eval_interval": 20,
    "eval_steps": 500,
    "failure_buffer_size": 500,
    "gamma": 0.99,
    "gate_coef": 0,
    "hidden_size": 512,
    "resources_hidden_size": 256,
    "kernel_size": 1,
    "learning_rate": 0.002,
    "load_path": None,
    "log_dir": "/home/ethanbro/ppo/.runs/logdir/control-flow/debug-version/search",
    "log_interval": 10,
    "long_jump": False,
    "max_eval_lines": 50,
    "max_failure_sample_prob": 0.2,
    "max_grad_norm": 0.5,
    "max_lines": 10,
    "max_loops": 3,
    "max_nesting_depth": 1,
    "max_while_loops": 10,
    "max_world_resamples": 50,
    "min_eval_lines": 1,
    "min_lines": 1,
    "no_eval": False,
    "no_op_coef": 0,
    "no_op_limit": 40,
    "no_pointer": False,
    "no_roll": False,
    "no_scan": False,
    "normalize": False,
    "num_batch": 1,
    "num_edges": 4,
    "num_frames": 2000,
    "num_layers": 0,
    "num_processes": 150,
    "olsk": False,
    "one_condition": False,
    "ppo_epoch": 2,
    "recurrent": False,
    "reject_while_prob": 0.6,
    "render": False,
    "render_eval": False,
    "save_interval": 20,
    "seed": 0,
    "single_control_flow_type": False,
    "stride": 1,
    "subtasks_only": False,
    "synchronous": False,
    "task_embed_size": 128,
    "tau": 0.95,
    "term_on": None,
    "time_to_waste": 0,
    "train_steps": 25,
    "transformer": False,
    "use_gae": False,
    "use_water": True,
    "value_loss_coef": 0.5,
    "world_size": 1,
}

search_upper = copy.deepcopy(starcraft_default)
search_upper.update(
    conv_hidden_size=hp.choice("conv_hidden_size", [32, 64]),
    entropy_coef=hp.choice("entropy_coef", [0.01, 0.015]),
    hidden_size=hp.choice("hidden_size", [512, 1024]),
    resources_hidden_size=hp.choice("resources_hidden_size", [256, 512]),
    learning_rate=hp.choice("learning_rate", [0.002, 0.0025, 0.003]),
    num_batch=hp.choice("num_batch", [1, 2]),
    num_edges=hp.choice("num_edges", [2, 4, 6]),
    ppo_epoch=hp.choice("ppo_epoch", [2, 3, 4]),
    tgt_success_rate=hp.choice("tgt_success_rate", [0.8, 0.9]),
    task_embed_size=hp.choice("task_embed_size", [64, 128]),
    train_steps=hp.choice("train_steps", [30, 35, 40]),
)


search_debug = copy.deepcopy(search_upper)
search_debug.update(
    kernel_size=1,
    stride=1,
    world_size=1,
)
debug_default = copy.deepcopy(starcraft_default)
debug_default.update(
    kernel_size=1,
    stride=1,
    world_size=1,
)
configs = dict(
    search_upper=search_upper,
    search_debug=search_debug,
    starcraft_default=starcraft_default,
    debug_default=debug_default,
    search=search,
)
