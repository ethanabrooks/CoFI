from collections import Hashable
from contextlib import contextmanager
from dataclasses import dataclass, replace

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from gym import spaces

from agents import AgentOutputs
from data_types import RecurrentState, RawAction
from distributions import FixedCategorical
from env import Obs
from layers import MultiEmbeddingBag, IntEncoding
from transformer import TransformerModel
from utils import astuple, init


def optimal_padding(h, kernel, stride):
    n = np.ceil((h - kernel) / stride + 1)
    return int(np.ceil((stride * (n - 1) + kernel - h) / 2))


def conv_output_dimension(h, padding, kernel, stride, dilation=1):
    return int(1 + (h + 2 * padding - dilation * (kernel - 1) - 1) / stride)


def get_obs_sections(obs_spaces):
    return [int(np.prod(s.shape)) for s in astuple(obs_spaces)]


def gate(g, new, old):
    old = torch.zeros_like(new).scatter(1, old.unsqueeze(1), 1)
    return FixedCategorical(probs=g * new + (1 - g) * old)


@dataclass
class Agent(nn.Module):
    entropy_coef: float
    action_space: spaces.MultiDiscrete
    conv_hidden_size: int
    debug: bool
    hidden_size: int
    kernel_size: int
    lower_embed_size: int
    max_eval_lines: int
    next_actions_embed_size: int
    no_pointer: bool
    no_roll: bool
    no_scan: bool
    num_edges: int
    observation_space: spaces.Dict
    olsk: bool
    resources_hidden_size: int
    stride: int
    task_embed_size: int
    transformer: bool

    def __hash__(self):
        return hash(tuple(x for x in astuple(self) if isinstance(x, Hashable)))

    def __post_init__(self):
        super().__init__()
        self.obs_spaces = Obs(**self.observation_space.spaces)
        self.action_size = self.action_space.nvec.size

        self.obs_sections = get_obs_sections(self.obs_spaces)
        self.eval_lines = self.max_eval_lines
        self.train_lines = len(self.obs_spaces.lines.nvec)

        action_nvec = RawAction(*map(int, self.action_space.nvec))

        self.embed_task = MultiEmbeddingBag(
            self.obs_spaces.lines.nvec[0], embedding_dim=self.task_embed_size
        )
        self.embed_lower = MultiEmbeddingBag(
            self.obs_spaces.partial_action.nvec,
            embedding_dim=self.lower_embed_size,
        )
        self.embed_next_action = nn.Embedding(
            self.obs_spaces.next_actions.nvec[0],
            embedding_dim=self.next_actions_embed_size,
        )
        self.task_encoder = (
            TransformerModel(
                ntoken=self.num_edges * self.d_space(),
                ninp=self.task_embed_size,
                nhid=self.task_embed_size,
            )
            if self.transformer
            else nn.GRU(
                self.task_embed_size,
                self.task_embed_size,
                bidirectional=True,
                batch_first=True,
            )
        )

        init_ = lambda m: init(
            m, nn.init.orthogonal_, lambda x: nn.init.constant_(x, 0), gain=0.01
        )  # TODO: try init
        self.actor = init_(nn.Linear(self.hidden_size, action_nvec.a))
        self.register_buffer("ones", torch.ones(1, dtype=torch.long))

        d, h, w = self.obs_spaces.obs.shape
        self.obs_dim = d
        self.kernel_size = min(d, self.kernel_size)
        self.padding = optimal_padding(h, self.kernel_size, self.stride) + 1
        self.embed_resources = nn.Sequential(
            IntEncoding(self.resources_hidden_size),
            nn.Flatten(),
            init_(
                nn.Linear(2 * self.resources_hidden_size, self.resources_hidden_size)
            ),
            nn.ReLU(),
        )
        m_size = (
            2 * self.task_embed_size + self.hidden_size
            if self.no_pointer
            else self.task_embed_size
        )
        zeta1_input_size = (
            m_size
            + self.conv_hidden_size
            + self.resources_hidden_size
            + self.lower_embed_size
            + self.next_actions_embed_size * len(self.obs_spaces.next_actions.nvec)
        )
        self.zeta1 = init_(nn.Linear(zeta1_input_size, self.hidden_size))
        if self.olsk:
            assert self.num_edges == 3
            self.upsilon = nn.GRUCell(zeta1_input_size, self.hidden_size)
            self.beta = init_(nn.Linear(self.hidden_size, self.num_edges))
        elif self.no_pointer:
            self.upsilon = nn.GRUCell(zeta1_input_size, self.hidden_size)
            self.beta = init_(nn.Linear(self.hidden_size, self.d_space()))
        else:
            self.upsilon = init_(nn.Linear(zeta1_input_size, self.num_edges))
            in_size = (2 if self.no_roll or self.no_scan else 1) * self.task_embed_size
            out_size = (
                self.num_edges * self.d_space() if self.no_scan else self.num_edges
            )
            self.beta = nn.Sequential(init_(nn.Linear(in_size, out_size)))
        self.d_gate = init_(nn.Linear(zeta1_input_size, 2))

        conv_out = conv_output_dimension(h, self.padding, self.kernel_size, self.stride)
        self.conv = nn.Sequential(
            nn.Conv2d(
                d,
                self.conv_hidden_size,
                kernel_size=self.kernel_size,
                stride=self.stride,
                padding=self.padding,
            ),
            nn.ReLU(),
            nn.Flatten(),
            init_(
                nn.Linear(conv_out ** 2 * self.conv_hidden_size, self.conv_hidden_size)
            ),
        )
        self.conv_bias = nn.Parameter(torch.zeros(self.conv_hidden_size))
        self.critic = init_(nn.Linear(self.hidden_size, 1))
        self.state_sizes = RecurrentState(
            a=1,
            a_probs=action_nvec.a,
            d=1,
            d_probs=(self.d_space()),
            h=self.hidden_size,
            p=1,
            v=1,
            dg_probs=2,
            dg=1,
        )

    def d_space(self):
        if self.olsk:
            return 3
        elif self.transformer or self.no_scan or self.no_pointer:
            return 2 * self.eval_lines
        else:
            return 2 * self.train_lines

    # PyAttributeOutsideInit
    @contextmanager
    def evaluating(self, eval_obs_space):
        obs_spaces = self.obs_spaces
        obs_sections = self.obs_sections
        state_sizes = self.state_sizes
        train_lines = self.train_lines
        self.obs_spaces = eval_obs_space.spaces
        self.obs_sections = get_obs_sections(Obs(**self.obs_spaces))
        self.train_lines = len(self.obs_spaces["lines"].nvec)
        # noinspection PyProtectedMember
        self.state_sizes = replace(self.state_sizes, d_probs=self.d_space())
        self.obs_spaces = Obs(**self.obs_spaces)
        yield self
        self.obs_spaces = obs_spaces
        self.obs_sections = obs_sections
        self.state_sizes = state_sizes
        self.train_lines = train_lines

    # noinspection PyMethodOverriding
    def forward(
        self, inputs, rnn_hxs, masks, deterministic=False, action=None, **kwargs
    ):

        N, dim = inputs.shape

        # parse non-action inputs
        state = Obs(*torch.split(inputs, self.obs_sections, dim=-1))
        state = replace(state, obs=state.obs.view(N, *self.obs_spaces.obs.shape))
        lines = state.lines.view(N, *self.obs_spaces.lines.shape).long()

        # build memory
        nl = len(self.obs_spaces.lines.nvec)
        assert nl == 1
        M = self.embed_task(lines.view(-1, self.obs_spaces.lines.nvec[0].size)).view(
            N, self.task_embed_size
        )

        h1 = self.conv(state.obs)
        resources = self.embed_resources(state.resources)
        next_actions = self.embed_next_action(state.next_actions.long()).view(N, -1)
        embedded_lower = self.embed_lower(
            state.partial_action.long()
        )  # +1 to deal with negatives
        zeta1_input = torch.cat(
            [M, h1, resources, embedded_lower, next_actions], dim=-1
        )
        z1 = F.relu(self.zeta1(zeta1_input))

        value = self.critic(z1)

        a_logits = self.actor(z1) - state.action_mask * 1e10
        dist = FixedCategorical(logits=a_logits)

        if action is None:
            action = dist.sample()
        else:
            action = RawAction(*action.unbind(-1)).a.unsqueeze(-1)

        action_log_probs = dist.log_probs(action)
        entropy = dist.entropy().mean()
        action = RawAction(
            delta=torch.zeros_like(action),
            dg=torch.zeros_like(action),
            ptr=torch.zeros_like(action),
            a=action,
        )
        return AgentOutputs(
            value=value,
            action=torch.cat(astuple(action), dim=-1),
            action_log_probs=action_log_probs,
            aux_loss=-self.entropy_coef * entropy,
            dist=dist,
            rnn_hxs=rnn_hxs,
            log=dict(entropy=entropy),
        )

    def get_value(self, inputs, rnn_hxs, masks):
        return self.forward(inputs, rnn_hxs, masks).value

    @property
    def is_recurrent(self):
        return False

    def parse_hidden(self, hx: torch.Tensor) -> RecurrentState:
        state_sizes = astuple(self.state_sizes)
        return RecurrentState(*torch.split(hx, state_sizes, dim=-1))

    def print(self, *args, **kwargs):
        args = [
            torch.round(100 * a)
            if type(a) is torch.Tensor and a.dtype == torch.float
            else a
            for a in args
        ]
        if self.debug:
            print(*args, **kwargs)

    @property
    def recurrent_hidden_state_size(self):
        return 1
