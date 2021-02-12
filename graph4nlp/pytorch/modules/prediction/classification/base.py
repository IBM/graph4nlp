from __future__ import absolute_import
from torch import nn


class ClassifierBase(nn.Module):

    def __init__(self):
        super(ClassifierBase, self).__init__()

    def forward(self, node_emb):
        raise NotImplementedError()


class ClassifierLayerBase(nn.Module):

    def __init__(self):
        super(ClassifierLayerBase, self).__init__()

    def forward(self, node_emb):
        raise NotImplementedError()


class NodeClassifierBase(ClassifierBase):

    def __init__(self):
        super(NodeClassifierBase, self).__init__()

    def forward(self, node_emb, node_idx=None):
        raise NotImplementedError()


class NodeClassifierLayerBase(ClassifierLayerBase):

    def __init__(self):
        super(NodeClassifierLayerBase, self).__init__()

    def forward(self, node_emb, node_idx=None):

        raise NotImplementedError()


class KGCompletionBase(nn.Module):

    def __init__(self):
        super(KGCompletionBase, self).__init__()

    def forward(self, node_emb, rel_emb, list_e_r_pair_idx=None, list_e_e_pair_idx=None):
        # Cannot inherit from the base class ClassifierLayerBase and
        # ClassifierBase because the forward(...) arguments are inconsistent.
        # rel_emb cannot be `None`
        raise NotImplementedError()


class KGCompletionLayerBase(nn.Module):

    def __init__(self):
        super(KGCompletionLayerBase, self).__init__()

    def forward(self, node_emb, rel_emb, list_e_r_pair_idx=None, list_e_e_pair_idx=None):
        raise NotImplementedError()


class LinkPredictionBase(ClassifierBase):

    def __init__(self):
        super(LinkPredictionBase, self).__init__()

    def forward(self, node_emb, node_idx=None):
        raise NotImplementedError()


class LinkPredictionLayerBase(ClassifierLayerBase):

    def __init__(self):
        super(LinkPredictionLayerBase, self).__init__()

    def forward(self, node_emb, node_idx=None):

        raise NotImplementedError()