from typing import Literal, Optional

import torch
import torch.nn as nn
from torch import Tensor

from pygegnn import (
    DataKeys,
    AtomicNum2Node,
    EGNNConv,
    Node2Property,
)


class EGNN(nn.Module):
    def __init__(
        self,
        node_dim: int,
        edge_dim: int,
        n_conv_layer: int,
        out_dim: int = 1,
        hidden_dim: int = DataKeys.Hidden_layer,
        aggr: Literal["add", "mean"] = "add",
        residual: bool = True,
        edge_attr_dim: Optional[int] = None,
        share_weight: bool = False,
        swish_beta: Optional[float] = 1.0,
        max_z: Optional[int] = None,
    ):
        super().__init__()
        self.node_initialize = AtomicNum2Node(embedding_dim=node_dim, max_num=max_z)
        if share_weight:
            self.convs = nn.ModuleList(
                [
                    EGNNConv(
                        x_dim=node_dim,
                        edge_dim=edge_dim,
                        edge_attr_dim=edge_attr_dim,
                        node_hidden=hidden_dim,
                        edge_hidden=hidden_dim,
                        beta=swish_beta,
                        aggr=aggr,
                        residual=residual,
                    )
                    * n_conv_layer
                ]
            )
        else:
            self.convs = nn.ModuleList(
                [
                    EGNNConv(
                        x_dim=node_dim,
                        edge_dim=edge_dim,
                        edge_attr_dim=edge_attr_dim,
                        node_hidden=hidden_dim,
                        edge_hidden=hidden_dim,
                        beta=swish_beta,
                        aggr=aggr,
                        residual=residual,
                    )
                    for _ in range(n_conv_layer)
                ]
            )
        self.output = Node2Property(
            in_dim=node_dim,
            hidden_dim=hidden_dim,
            out_dim=out_dim,
            beta=swish_beta,
            aggr=aggr,
        )

    def calc_atomic_distances(self, data) -> Tensor:
        if data.get(DataKeys.Batch) is not None:
            batch = data[DataKeys.Batch]
        else:
            batch = data[DataKeys.Position].new_zeros(
                data[DataKeys.Position].shape[0], dtype=torch.long
            )

        edge_src, edge_dst = data[DataKeys.Edge_index][0], data[DataKeys.Edge_index][1]
        edge_batch = batch[edge_src]
        edge_vec = (
            data[DataKeys.Position][edge_dst]
            - data[DataKeys.Position][edge_src]
            + torch.einsum(
                "ni,nij->nj",
                data[DataKeys.Edge_shift],
                data[DataKeys.Lattice][edge_batch],
            )
        )
        return torch.norm(edge_vec, dim=1)

    def forward(self, data_batch) -> Tensor:
        batch = data_batch[DataKeys.Batch]
        atomic_numbers = data_batch[DataKeys.Atomic_num]
        edge_index = data_batch[DataKeys.Edge_index]
        edge_attr = data_batch.get(DataKeys.Edge_attr, None)
        # calc distances
        distances = self.calc_atomic_distances(data_batch)
        # initial embedding
        x = self.node_initialize(atomic_numbers)
        # convolution
        for conv in self.convs:
            x = conv(x, distances, edge_index, edge_attr)
        # read out property
        x = self.output(x, batch)
        return x
