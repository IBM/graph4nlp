import torch
import torch.nn as nn
import torch.nn.functional as F
import dgl.function as fn
from dgl.nn.pytorch import SAGEConv
from dgl.utils import expand_as_pair
from base import GNNLayerBase, GNNBase
from dgl.utils import expand_as_pair,check_eq_shape

class GraphSAGE(GNNBase):
    r"""Multi-layered `GraphSAGE Network <https://arxiv.org/pdf/1706.02216.pdf>`__
    Support both unidirectional (i.e., regular) and bidirectional (i.e., `bi_sep` and `bi_fuse`) versions.

    .. math::
        h_{\mathcal{N}(i)}^{(l+1)} & = \mathrm{aggregate}
        \left(\{h_{j}^{l}, \forall j \in \mathcal{N}(i) \}\right)

        h_{i}^{(l+1)} & = \sigma \left(W \cdot \mathrm{concat}
        (h_{i}^{l}, h_{\mathcal{N}(i)}^{l+1} + b) \right)

        h_{i}^{(l+1)} & = \mathrm{norm}(h_{i}^{l})

    Parameters
    ----------
    num_layers: int
        Number of GraphSAGE layers.
    input_size : int, or pair of ints
        Input feature size.
        If the layer is to be applied to a unidirectional bipartite graph, ``input_size``
        specifies the input feature size on both the source and destination nodes.  If
        a scalar is given, the source and destination node feature size would take the
        same value.
        
        If aggregator type is ``gcn``, the feature size of source and destination nodes
        are required to be the same.
    hidden_size: int list of int
        Hidden layer size.
        If a scalar is given, the sizes of all the hidden layers are the same.
        If a list of scalar is given, each element in the list is the size of each hidden layer.
        Example: [100,50]
    output_size : int
        Output feature size.
    direction_option: str
        Whether use unidirectional (i.e., regular) or bidirectional (i.e., `bi_sep` and `bi_fuse`) versions.
    feat_drop : float, optional
        Dropout rate on feature, defaults: ``0``.
    aggregator_type : str
        Aggregator type to use (``mean``, ``gcn``, ``pool``, ``lstm``).     
    bias : bool
        If True, adds a learnable bias to the output. Default: ``True``.
    norm : callable activation function/layer or None, optional
        If not None, applies normalization to the updated node features.
    activation : callable activation function/layer or None, optional
        If not None, applies an activation function to the updated node features.
        Default: ``None``.
    """
    def __init__(self,
                num_layers,
                input_size,
                hidden_size,
                output_size,
                aggregator_type,
                direction_option='uni',
                feat_drop=0.,
                bias=True,
                norm=None,
                activation=None):
        super(GraphSAGE, self).__init__()
        self.num_layers = num_layers
        self.direction_option = direction_option
        self.GraphSAGE_layers = nn.ModuleList()
        if self.direction_option == 'bi_sep':
               output_size=int(output_size/2)
               
        #transform the hidden size format
        if self.num_layers>1 and type(hidden_size) is int:
            hidden_size=[hidden_size for i in range(self.num_layers-1)]
            
               
        if self.num_layers>1:       
            # input projection
            self.GraphSAGE_layers.append(GraphSAGELayer(input_size,
                                            hidden_size[0],
                                            aggregator_type,
                                            direction_option=self.direction_option,
                                            feat_drop=feat_drop,
                                            bias=True,
                                            norm=None,
                                            activation=None))
        # hidden layers
        for l in range(1, self.num_layers - 1):
            # due to multi-head, the input_size = hidden_size * num_heads
            self.GraphSAGE_layers.append(GraphSAGELayer(hidden_size[l - 1],
                                            hidden_size[l],
                                            aggregator_type,
                                            direction_option=self.direction_option,
                                            feat_drop=feat_drop,
                                            bias=True,
                                            norm=None,
                                            activation=None))
        # output projection
        self.GraphSAGE_layers.append(GraphSAGELayer(hidden_size[-1] if self.num_layers > 1 else input_size,
                                        output_size,
                                        aggregator_type,
                                        direction_option=self.direction_option,
                                        feat_drop=feat_drop,
                                        bias=True,
                                        norm=None,
                                        activation=None))
       
    def forward(self, graph):
        r"""Compute GraphSAGE layer.

        Parameters
        ----------
        graph : GraphData
            The graph with node feature stored in the feature field named as 
            "node_feat".
            The node features are used for message passing.
 
        Returns
        -------
        graph : GraphData
            The graph with generated node embedding stored in the feature field
            named as "node_emb".
        """        
        
        h=graph.ndata['node_feat'] #get the node feature tensor from graph
        

        # output projection
        if self.num_layers>1:          
          for l in range(0,self.num_layers - 1):
              h = self.GraphSAGE_layers[l](graph, h)
            
        logits = self.GraphSAGE_layers[-1](graph, h)

        if self.direction_option == 'bi_sep':
            logits = torch.cat(logits, -1)

        else:
            logits = logits
            
        graph.ndata['node_emb']=logits

        return graph
    
    

class GraphSAGELayer(GNNLayerBase):
    r"""A unified wrapper for `GraphSAGE Network <https://arxiv.org/pdf/1706.02216.pdf>`__
    Support both unidirectional (i.e., regular) and bidirectional (i.e., `bi_sep` and `bi_fuse`) versions.

    .. math::
        h_{\mathcal{N}(i)}^{(l+1)} & = \mathrm{aggregate}
        \left(\{h_{j}^{l}, \forall j \in \mathcal{N}(i) \}\right)

        h_{i}^{(l+1)} & = \sigma \left(W \cdot \mathrm{concat}
        (h_{i}^{l}, h_{\mathcal{N}(i)}^{l+1} + b) \right)

        h_{i}^{(l+1)} & = \mathrm{norm}(h_{i}^{l})


    Parameters
    ----------
    input_size : int, or pair of ints
        Input feature size.
        If the layer is to be applied to a unidirectional bipartite graph, ``input_size``
        specifies the input feature size on both the source and destination nodes.  If
        a scalar is given, the source and destination node feature size would take the
        same value.
    output_size : int
        Output feature size.
    direction_option: str
        Whether use unidirectional (i.e., regular) or bidirectional (i.e., `bi_sep` and `bi_fuse`) versions.
    feat_drop : float, optional
        Dropout rate on feature, defaults: ``0``.
    aggregator_type : str
        Aggregator type to use (``mean``, ``gcn``, ``pool``, ``lstm``).     
    bias : bool
        If True, adds a learnable bias to the output. Default: ``True``.
    norm : callable activation function/layer or None, optional
        If not None, applies normalization to the updated node features.
    activation : callable activation function/layer or None, optional
        If not None, applies an activation function to the updated node features.
        Default: ``None``.
    """
    def __init__(self,
                input_size,
                output_size,
                aggregator_type,
                direction_option='uni',
                feat_drop=0.,
                bias=True,
                norm=None,
                activation=None):
        super(GraphSAGELayer, self).__init__()
        if direction_option == 'uni':
            self.model = UniGraphSAGELayerConv(input_size,
                                        output_size,
                                        aggregator_type,
                                        feat_drop=feat_drop,
                                        bias=bias,
                                        norm=norm,
                                        activation=activation)

        elif direction_option == 'bi_sep':
            self.model = BiSepGraphSAGELayerConv(input_size,
                                        output_size,
                                        aggregator_type,
                                        feat_drop=feat_drop,
                                        bias=bias,
                                        norm=norm,
                                        activation=activation)

        elif direction_option == 'bi_fuse':
            self.model = BiFuseGraphSAGELayerConv(input_size,
                                        output_size,
                                        aggregator_type,
                                        feat_drop=feat_drop,
                                        bias=bias,
                                        norm=norm,
                                        activation=activation)

        else:
            raise RuntimeError('Unknown `direction_option` value: {}'.format(direction_option))

    def forward(self, graph, feat):
        return self.model(graph, feat)

class UniGraphSAGELayerConv(GNNLayerBase):
    r"""GraphSAGE layer from paper `Inductive Representation Learning on
    Large Graphs <https://arxiv.org/pdf/1706.02216.pdf>`__.

    .. math::
        h_{\mathcal{N}(i)}^{(l+1)} & = \mathrm{aggregate}
        \left(\{h_{j}^{l}, \forall j \in \mathcal{N}(i) \}\right)

        h_{i}^{(l+1)} & = \sigma \left(W \cdot \mathrm{concat}
        (h_{i}^{l}, h_{\mathcal{N}(i)}^{l+1} + b) \right)

        h_{i}^{(l+1)} & = \mathrm{norm}(h_{i}^{l})

    Parameters
    ----------
    input_size : int, or pair of ints
        Input feature size.

        If the layer is to be applied on a unidirectional bipartite graph, ``in_feats``
        specifies the input feature size on both the source and destination nodes.  If
        a scalar is given, the source and destination node feature size would take the
        same value.

        If aggregator type is ``gcn``, the feature size of source and destination nodes
        are required to be the same.
    out_size : int
        Output feature size.
    feat_drop : float
        Dropout rate on features, default: ``0``.
    aggregator_type : str
        Aggregator type to use (``mean``, ``gcn``, ``pool``, ``lstm``).
    bias : bool
        If True, adds a learnable bias to the output. Default: ``True``.
    norm : callable activation function/layer or None, optional
        If not None, applies normalization to the updated node features.
    activation : callable activation function/layer or None, optional
        If not None, applies an activation function to the updated node features.
        Default: ``None``.
    """
    def __init__(self,
                 input_size,
                 output_size,
                 aggregator_type,
                 feat_drop=0.,
                 bias=True,
                 norm=None,
                 activation=None):
        super(UniGraphSAGELayerConv, self).__init__()
        self.model = SAGEConv(input_size, output_size, aggregator_type, feat_drop,
                            bias, norm, activation)

    def forward(self, graph, feat):
        return self.model(graph, feat)
    

class BiSepGraphSAGELayerConv(GNNLayerBase):
    r"""Bidirection version GraphSAGE layer from paper `Inductive Representation Learning on
    Large Graphs <https://arxiv.org/pdf/1706.02216.pdf>`__.

    .. math::
        h_{\mathcal{N}(i)}^{(l+1)} & = \mathrm{aggregate}
        \left(\{h_{j}^{l}, \forall j \in \mathcal{N}(i) \}\right)

        h_{i}^{(l+1)} & = \sigma \left(W \cdot \mathrm{concat}
        (h_{i}^{l}, h_{\mathcal{N}(i)}^{l+1} + b) \right)

        h_{i}^{(l+1)} & = \mathrm{norm}(h_{i}^{l})

    Parameters
    ----------
    input_size : int, or pair of ints
        Input feature size.

        If the layer is to be applied on a unidirectional bipartite graph, ``in_feats``
        specifies the input feature size on both the source and destination nodes.  If
        a scalar is given, the source and destination node feature size would take the
        same value.

        If aggregator type is ``gcn``, the feature size of source and destination nodes
        are required to be the same.
    output_size : int
        Output feature size.
    feat_drop : float
        Dropout rate on features, default: ``0``.
    aggregator_type : str
        Aggregator type to use (``mean``, ``gcn``, ``pool``, ``lstm``).
    bias : bool
        If True, adds a learnable bias to the output. Default: ``True``.
    norm : callable activation function/layer or None, optional
        If not None, applies normalization to the updated node features.
    activation : callable activation function/layer or None, optional
        If not None, applies an activation function to the updated node features.
        Default: ``None``.
    """

    def __init__(self, input_size,output_size,aggregator_type,
                 feat_drop=0.,
                 bias=True,
                 norm=None,
                 activation=None):
        super(BiSepGraphSAGELayerConv, self).__init__()

        self._in_src_size, self._in_dst_size = expand_as_pair(input_size)
        self._output_size = output_size
        self._aggre_type = aggregator_type
        self.norm = norm
        self.feat_drop = nn.Dropout(feat_drop)
        self.activation = activation
        # aggregator type: mean/pool/lstm/gcn
        if aggregator_type == 'pool': #aggreagator different for two direction's network
                self.fc_pool_fw = nn.Linear(self._in_src_size, self._in_src_size)
                self.fc_pool_bw = nn.Linear(self._in_src_size, self._in_src_size)
        if aggregator_type == 'lstm':
                self.lstm_fw = nn.LSTM(self._in_src_size, self._in_src_size, batch_first=True)
                self.lstm_bw = nn.LSTM(self._in_src_size, self._in_src_size, batch_first=True)       
        if aggregator_type != 'gcn':
                self.fc_self_fw = nn.Linear(self._in_dst_size, output_size, bias=bias)
                self.fc_self_bw = nn.Linear(self._in_dst_size, output_size, bias=bias)               
        
        self.fc_neigh_fw = nn.Linear(self._in_src_size, output_size, bias=bias)
        self.fc_neigh_bw = nn.Linear(self._in_src_size, output_size, bias=bias)
        
        self.reset_parameters()


    def reset_parameters(self):
        """Reinitialize learnable parameters."""
        gain_fw = nn.init.calculate_gain('relu')
        gain_bw = nn.init.calculate_gain('relu')
        if self._aggre_type == 'pool':
            nn.init.xavier_uniform_(self.fc_pool_fw.weight, gain=gain_fw)
            nn.init.xavier_uniform_(self.fc_pool_bw.weight, gain=gain_bw)
        if self._aggre_type == 'lstm':
            self.lstm_fw.reset_parameters()
            self.lstm_bw.reset_parameters()
        if self._aggre_type != 'gcn':
            nn.init.xavier_uniform_(self.fc_self_fw.weight, gain=gain_fw)
            nn.init.xavier_uniform_(self.fc_neigh_bw.weight, gain=gain_bw)

    def _lstm_reducer_fw(self, nodes):
        """LSTM reducer
        NOTE(zihao): lstm reducer with default schedule (degree bucketing)
        is slow, we could accelerate this with degree padding in the future.
        """
        m = nodes.mailbox['m']  # (B, L, D)
        batch_size = m.shape[0]
        h = (m.new_zeros((1, batch_size, self._in_src_size)),
             m.new_zeros((1, batch_size, self._in_src_size)))
        _, (rst, _) = self.lstm_fw(m, h)        
        return {'neigh': rst.squeeze(0)}
    
    def _lstm_reducer_bw(self, nodes):
        """LSTM reducer
        NOTE(zihao): lstm reducer with default schedule (degree bucketing)
        is slow, we could accelerate this with degree padding in the future.
        """
        m = nodes.mailbox['m']  # (B, L, D)
        batch_size = m.shape[0]
        h = (m.new_zeros((1, batch_size, self._in_src_size)),
             m.new_zeros((1, batch_size, self._in_src_size)))
        _, (rst, _) = self.lstm_bw(m, h)        
        return {'neigh': rst.squeeze(0)}  
    
    def message_reduce(self,graph,direction,feat):
       if isinstance(feat, tuple):
        feat_src = self.feat_drop(feat[0])
        feat_dst = self.feat_drop(feat[1])
       else:
        feat_src = feat_dst = self.feat_drop(feat)

       h_self = feat_dst

       if self._aggre_type == 'mean':
         graph.srcdata['h'] = feat_src
         graph.update_all(fn.copy_src('h', 'm'), fn.mean('m', 'neigh'))
         h_neigh = graph.dstdata['neigh']
       elif self._aggre_type == 'gcn':
         check_eq_shape(feat)
         graph.srcdata['h'] = feat_src
         graph.dstdata['h'] = feat_dst  # same as above if homogeneous
         graph.update_all(fn.copy_src('h', 'm'), fn.sum('m', 'neigh'))
         # divide in_degrees
         degs = graph.in_degrees().to(feat_dst)
         h_neigh = (graph.dstdata['neigh'] + graph.dstdata['h']) / (degs.unsqueeze(-1) + 1)
       elif self._aggre_type == 'pool':
         if direction=='fw':
             graph.srcdata['h'] = F.relu(self.fc_pool_fw(feat_src))
         elif direction=='bw':
             graph.srcdata['h'] = F.relu(self.fc_pool_bw(feat_src))  
         graph.update_all(fn.copy_src('h', 'm'), fn.max('m', 'neigh'))
         h_neigh = graph.dstdata['neigh']
       elif self._aggre_type == 'lstm':
         graph.srcdata['h'] = feat_src
         if direction=='fw':
           graph.update_all(fn.copy_src('h', 'm'), self._lstm_reducer_fw)
         elif direction=='bw':
           graph.update_all(fn.copy_src('h', 'm'), self._lstm_reducer_bw)
           
         h_neigh = graph.dstdata['neigh']
       else:
        raise KeyError('Aggregator type {} not recognized.'.format(self._aggre_type))

       return h_neigh,h_self    

    def forward(self,graph,feat):
        r"""
        Compute node embeddings from both directions in bidirection seperated GraphSAGE

        Parameters
        ----------
        graph : DGLGraph
            The graph.
        feat_fw : torch.Tensor or pair of torch.Tensor
        feat_bw: torch.Tensor or pair of torch.Tensor
            If a torch.Tensor is given, the input feature of shape :math:`(N, D_{in})` where
            :math:`D_{in}` is size of input feature, :math:`N` is the number of nodes.
            If a pair of torch.Tensor is given, the pair must contain two tensors of shape
            :math:`(N_{in}, D_{in_{src}})` and :math:`(N_{out}, D_{in_{dst}})`.
        
        Returns
        -------
        The output feature of shape :math:`(N, D_{out})` where :math:`D_{out}`
        is size of output feature.       
        """
        if isinstance(feat,list):   #judge whether the the input is the initial node feature or the two outputs from the last BisepGraphSAGELayer
           feat_fw, feat_bw = feat 
        else:
           feat_fw = feat
           feat_bw = feat
           
        self.forward_graph = graph
        self.backward_graph = graph.reverse()
        f_graph = self.forward_graph.local_var()
        b_graph = self.forward_graph.local_var()

 

        # update node part:
        h_neigh_fw,h_self_fw = self.message_reduce(f_graph,'fw',feat_fw)
        h_neigh_bw,h_self_bw = self.message_reduce(b_graph,'bw',feat_bw)
    
        # GraphSAGE GCN does not require fc_self.
    
        
        if self._aggre_type == 'gcn':
            rst_fw = self.fc_neigh_fw(h_neigh_fw)
            rst_bw = self.fc_neigh_bw(h_neigh_bw)  
        else:
            rst_fw = self.fc_self_fw(h_self_fw) + self.fc_neigh_fw(h_neigh_fw)
            rst_bw = self.fc_self_bw(h_self_bw) + self.fc_neigh_bw(h_neigh_bw)
    
        # activation
        if self.activation is not None:
            rst_fw = self.activation(rst_fw)
            rst_bw = self.activation(rst_bw)
            # normalization
        if self.norm is not None:
            rst_fw = self.norm(rst_fw)
            rst_bw = self.norm(rst_bw)
            
        return [rst_fw,rst_bw]


class BiFuseGraphSAGELayerConv(GNNLayerBase):
    r"""Bidirection version GraphSAGE layer from paper `Inductive Representation Learning on
    Large Graphs <https://arxiv.org/pdf/1706.02216.pdf>`__.

    .. math::
        h_{\mathcal{N}(i)}^{(l+1)} & = \mathrm{aggregate}
        \left(\{h_{j}^{l}, \forall j \in \mathcal{N}(i) \}\right)

        h_{i}^{(l+1)} & = \sigma \left(W \cdot \mathrm{concat}
        (h_{i}^{l}, h_{\mathcal{N}(i)}^{l+1} + b) \right)

        h_{i}^{(l+1)} & = \mathrm{norm}(h_{i}^{l})

    Parameters
    ----------
    input_size : int, or pair of ints
        Input feature size.

        If the layer is to be applied on a unidirectional bipartite graph, ``in_feats``
        specifies the input feature size on both the source and destination nodes.  If
        a scalar is given, the source and destination node feature size would take the
        same value.

        If aggregator type is ``gcn``, the feature size of source and destination nodes
        are required to be the same.
    output_size : int
        Output feature size.
    feat_drop : float
        Dropout rate on features, default: ``0``.
    aggregator_type : str
        Aggregator type to use (``mean``, ``gcn``, ``pool``, ``lstm``).
    bias : bool
        If True, adds a learnable bias to the output. Default: ``True``.
    norm : callable activation function/layer or None, optional
        If not None, applies normalization to the updated node features.
    activation : callable activation function/layer or None, optional
        If not None, applies an activation function to the updated node features.
        Default: ``None``.
    """

    def __init__(self, input_size,output_size,aggregator_type,
                 feat_drop=0.,
                 bias=True,
                 norm=None,
                 activation=None):
        super(BiFuseGraphSAGELayerConv, self).__init__()

        self._in_src_size, self._in_dst_size = expand_as_pair(input_size)
        self._output_size = output_size
        self._aggre_type = aggregator_type
        self.norm = norm
        self.feat_drop = nn.Dropout(feat_drop)
        self.activation = activation
        # aggregator type: mean/pool/lstm/gcn
        if aggregator_type == 'pool': #aggreagator different for two direction's network
                self.fc_pool_fw = nn.Linear(self._in_src_size, self._in_src_size)
                self.fc_pool_bw = nn.Linear(self._in_src_size, self._in_src_size)
        if aggregator_type == 'lstm':
                self.lstm_fw = nn.LSTM(self._in_src_size, self._in_src_size, batch_first=True)
                self.lstm_bw = nn.LSTM(self._in_src_size, self._in_src_size, batch_first=True)       
        if aggregator_type != 'gcn':
                self.fc_self_fw = nn.Linear(self._in_dst_size, output_size, bias=bias)
                self.fc_self_bw = nn.Linear(self._in_dst_size, output_size, bias=bias)               
        
        self.fc_neigh = nn.Linear(self._in_src_size, output_size, bias=bias)
        
        self.fuse_linear=nn.Linear(4*self._in_src_size, self._in_src_size, bias=bias)
        
        self.reset_parameters()


    def reset_parameters(self):
        """Reinitialize learnable parameters."""
        gain_fw = nn.init.calculate_gain('relu')
        gain_bw = nn.init.calculate_gain('relu')
        if self._aggre_type == 'pool':
            nn.init.xavier_uniform_(self.fc_pool_fw.weight, gain=gain_fw)
            nn.init.xavier_uniform_(self.fc_pool_bw.weight, gain=gain_bw)
        if self._aggre_type == 'lstm':
            self.lstm_fw.reset_parameters()
            self.lstm_bw.reset_parameters()
        if self._aggre_type != 'gcn':
            nn.init.xavier_uniform_(self.fc_self_fw.weight, gain=gain_fw)
            nn.init.xavier_uniform_(self.fc_self_bw.weight, gain=gain_bw)

    def _lstm_reducer_fw(self, nodes):
        """LSTM reducer
        NOTE(zihao): lstm reducer with default schedule (degree bucketing)
        is slow, we could accelerate this with degree padding in the future.
        """
        m = nodes.mailbox['m']  # (B, L, D)
        batch_size = m.shape[0]
        h = (m.new_zeros((1, batch_size, self._in_src_size)),
             m.new_zeros((1, batch_size, self._in_src_size)))
        _, (rst, _) = self.lstm_fw(m, h)        
        return {'neigh': rst.squeeze(0)}
    
    def _lstm_reducer_bw(self, nodes):
        """LSTM reducer
        NOTE(zihao): lstm reducer with default schedule (degree bucketing)
        is slow, we could accelerate this with degree padding in the future.
        """
        m = nodes.mailbox['m']  # (B, L, D)
        batch_size = m.shape[0]
        h = (m.new_zeros((1, batch_size, self._in_src_size)),
             m.new_zeros((1, batch_size, self._in_src_size)))
        _, (rst, _) = self.lstm_bw(m, h)        
        return {'neigh': rst.squeeze(0)}    

    def forward(self,graph,feat):
        r"""
        Compute node embeddings from both directions in bidirection seperated GraphSAGE

        Parameters
        ----------
        graph : DGLGraph
            The graph.
        feat_fw : torch.Tensor or pair of torch.Tensor
        feat_bw: torch.Tensor or pair of torch.Tensor
            If a torch.Tensor is given, the input feature of shape :math:`(N, D_{in})` where
            :math:`D_{in}` is size of input feature, :math:`N` is the number of nodes.
            If a pair of torch.Tensor is given, the pair must contain two tensors of shape
            :math:`(N_{in}, D_{in_{src}})` and :math:`(N_{out}, D_{in_{dst}})`.
        
        Returns
        -------
        The output feature of shape :math:`(N, D_{out})` where :math:`D_{out}`
        is size of output feature.       
        """
        if feat is list:   #judge whether the the input is the initial node feature or the two outputs from the last BisepGraphSAGELayer
           feat_fw, feat_bw = feat 
        else:
           feat_fw = feat
           feat_bw = feat
           
        self.forward_graph = graph
        self.backward_graph = graph.reverse()
        f_graph = self.forward_graph.local_var()
        b_graph = self.forward_graph.local_var()

        def fuse(self,forward_message,backward_message):
            cat=torch.cat([forward_message,backward_message],dim=1)
            sum=forward_message+backward_message
            diff=forward_message-backward_message
            if self.activation:
              z=self.activation(self.fuse_linear(torch.cat([cat,sum,diff],dim=1)))
            else:
              z=self.fuse_linear(torch.cat([cat,sum,diff],dim=1))
 
            return z*forward_message+(1-z)*backward_message
 
        def message_reduce(self,graph,direction):
           if isinstance(feat, tuple):
            feat_src = self.feat_drop(feat[0])
            feat_dst = self.feat_drop(feat[1])
           else:
            feat_src = feat_dst = self.feat_drop(feat)
    
           h_self = feat_dst
    
           if self._aggre_type == 'mean':
             graph.srcdata['h'] = feat_src
             graph.update_all(fn.copy_src('h', 'm'), fn.mean('m', 'neigh'))
             h_neigh = graph.dstdata['neigh']
           elif self._aggre_type == 'gcn':
             check_eq_shape(feat)
             graph.srcdata['h'] = feat_src
             graph.dstdata['h'] = feat_dst  # same as above if homogeneous
             graph.update_all(fn.copy_src('h', 'm'), fn.sum('m', 'neigh'))
             # divide in_degrees
             degs = graph.in_degrees().to(feat_dst)
             h_neigh = (graph.dstdata['neigh'] + graph.dstdata['h']) / (degs.unsqueeze(-1) + 1)
           elif self._aggre_type == 'pool':
             if direction=='fw':
                 graph.srcdata['h'] = F.relu(self.fc_pool_fw(feat_src))
             elif direction=='bw':
                 graph.srcdata['h'] = F.relu(self.fc_pool_bw(feat_src))  
             graph.update_all(fn.copy_src('h', 'm'), fn.max('m', 'neigh'))
             h_neigh = graph.dstdata['neigh']
           elif self._aggre_type == 'lstm':
             graph.srcdata['h'] = feat_src
             if direction=='fw':
               graph.update_all(fn.copy_src('h', 'm'), self._lstm_reducer_fw)
             elif direction=='bw':
               graph.update_all(fn.copy_src('h', 'm'), self._lstm_reducer_bw)
               
             h_neigh = graph.dstdata['neigh']
           else:
            raise KeyError('Aggregator type {} not recognized.'.format(self._aggre_type))
    
           return h_neigh,h_self
       
        # update node part:
        h_neigh_fw,h_self_fw = message_reduce(self,f_graph,'fw')
        h_neigh_bw,h_self_bw = message_reduce(self, b_graph,'bw')

        #fuse the two directions' information 
        h_neigh_fused=fuse(self,h_neigh_fw,h_neigh_bw)  
        # GraphSAGE GCN does not require fc_self.          
        if self._aggre_type == 'gcn':                       
            rst_fused = self.fc_neigh(h_neigh_fused)
        else:
            rst_fused = self.fc_self_fw(h_self_fw) + self.fc_neigh(h_neigh_fused)
    
        # activation
        if self.activation is not None:
            rst_fused = self.activation(rst_fused)
            # normalization
        if self.norm is not None:
            rst_fused = self.norm(rst_fused)
            
        return rst_fused


