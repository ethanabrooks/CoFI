from dataclasses import dataclass
import torch.nn.functional as F

import torch
import torch.nn as nn

import cofi_s


@dataclass
class Agent(cofi_s.Agent):
    def __hash__(self):
        return self.hash()

    def build_beta(self):
        return nn.Sequential(
            self.init_(
                nn.Linear(
                    self.instruction_embed_size * 2,  # biGRU
                    self.delta_size,
                )
            )
        )

    @property
    def max_backward_jump(self):
        return self.eval_lines

    @property
    def max_forward_jump(self):
        return self.eval_lines - 1

    def build_upsilon(self):
        return None

    def get_delta_probs(self, G, P, z):
        N = G.size(0)
        g = G.reshape(N, 2 * self.instruction_embed_size)
        return torch.softmax(self.beta(g), dim=-1)

    def get_G(self, rolled):
        _, G = self.encode_G(rolled)
        return G.transpose(0, 1)

    def get_instruction_mask(self, N, instruction_mask):
        instruction_mask = super().get_instruction_mask(N, instruction_mask)
        instruction_mask = F.pad(
            instruction_mask,
            (0, self.delta_size - instruction_mask.size(-1)),
            value=1,
        )
        return instruction_mask

    def get_P(self, *args, **kwargs):
        return None

    def get_g(self, G, R, p):
        N = G.size(0)
        return G.reshape(N, 2 * self.instruction_embed_size)