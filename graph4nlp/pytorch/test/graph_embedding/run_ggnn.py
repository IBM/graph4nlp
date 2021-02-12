import argparse
import numpy as np
import networkx as nx
import time
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.backends.cudnn as cudnn
import dgl
from dgl import DGLGraph
from dgl.data import register_data_args, load_data

from .utils import EarlyStopping
# from utils import EarlyStopping
from ...modules.graph_embedding.ggnn import GGNN
# from graph4nlp.pytorch.modules.graph_embedding.ggnn import GGNN
# from graph4nlp.pytorch.test.graph_embedding.utils import EarlyStopping


def accuracy(logits, labels):
    _, indices = torch.max(logits, dim=1)
    correct = torch.sum(indices == labels)
    return correct.item() * 1.0 / len(labels)

def evaluate(model, g, labels, mask):
    model.eval()
    with torch.no_grad():
        logits = model(g)
        logits = logits[mask]
        labels = labels[mask]
        return accuracy(logits, labels)

class GNNClassifier(nn.Module):
    def __init__(self,
                num_layers,
                input_size,
                output_size,
                n_class,
                direction_option):
        super(GNNClassifier, self).__init__()
        self.direction_option = direction_option
        self.model = GGNN(num_layers, input_size, output_size, direction_option=direction_option)

        if self.direction_option == 'bi_sep':
            self.fc = nn.Linear(2 * output_size, n_class)
        else:
            self.fc = nn.Linear(output_size, n_class)

    def forward(self, graph):
        graph = self.model(graph)
        logits = graph.ndata['node_emb']
        logits = self.fc(F.elu(logits))

        return logits

def prepare_dgl_graph_data(args):
    data = load_data(args)
    features = torch.FloatTensor(data.features)
    labels = torch.LongTensor(data.labels)
    if hasattr(torch, 'BoolTensor'):
        train_mask = torch.BoolTensor(data.train_mask)
        val_mask = torch.BoolTensor(data.val_mask)
        test_mask = torch.BoolTensor(data.test_mask)
    else:
        train_mask = torch.ByteTensor(data.train_mask)
        val_mask = torch.ByteTensor(data.val_mask)
        test_mask = torch.ByteTensor(data.test_mask)

    num_feats = features.shape[1]
    n_classes = data.num_labels
    n_edges = data.graph.number_of_edges()
    print("""----Data statistics------'
      #Edges %d
      #Classes %d
      #Train samples %d
      #Val samples %d
      #Test samples %d""" %
          (n_edges, n_classes,
           train_mask.int().sum().item(),
           val_mask.int().sum().item(),
           test_mask.int().sum().item()))

    g = data.graph
    # add self loop
    g.remove_edges_from(nx.selfloop_edges(g))
    g = DGLGraph(g)
    g.add_edges(g.nodes(), g.nodes())
    n_edges = g.number_of_edges()

    data = {'features': features,
            'graph': g,
            'train_mask': train_mask,
            'val_mask': val_mask,
            'test_mask': test_mask,
            'labels': labels,
            'num_feats': num_feats,
            'n_classes': n_classes,
            'n_edges': n_edges}

    return data

def prepare_ogbn_graph_data(args):
    from ogb.nodeproppred import DglNodePropPredDataset

    dataset = DglNodePropPredDataset(name=args.dataset)

    split_idx = dataset.get_idx_split()
    train_idx, val_idx, test_idx = torch.LongTensor(split_idx['train']), torch.LongTensor(split_idx['valid']), torch.LongTensor(split_idx['test'])
    g, labels = dataset[0] # graph: dgl graph object, label: torch tensor of shape (num_nodes, num_tasks)
    features = torch.Tensor(g.ndata['feat'])
    labels = torch.LongTensor(labels).squeeze(-1)

    # add self loop
    # no duplicate self loop will be added for nodes already having self loops
    new_g = dgl.transform.add_self_loop(g)


    # edge_index = data[0]['edge_index']
    # adj = to_undirected(edge_index, num_nodes=data[0]['num_nodes'])
    # assert adj.diagonal().sum() == 0 and adj.max() <= 1 and (adj != adj.transpose()).sum() == 0

    num_feats = features.shape[1]
    n_classes = labels.max().item() + 1
    n_edges = new_g.number_of_edges()
    print("""----Data statistics------'
      #Edges %d
      #Classes %d
      #Train samples %d
      #Val samples %d
      #Test samples %d""" %
          (n_edges, n_classes,
           train_idx.shape[0],
           val_idx.shape[0],
           test_idx.shape[0]))

    data = {'features': features,
            'graph': new_g,
            'train_mask': train_idx,
            'val_mask': val_idx,
            'test_mask': test_idx,
            'labels': labels,
            'num_feats': num_feats,
            'n_classes': n_classes,
            'n_edges': n_edges}

    return data

def main(args, seed):
    # load and preprocess dataset
    if args.dataset.startswith('ogbn'):
        # Open Graph Benchmark datasets
        data = prepare_ogbn_graph_data(args)
    else:
        # DGL datasets
        data = prepare_dgl_graph_data(args)

    features, g, train_mask, val_mask, test_mask, labels, num_feats, n_classes, n_edges\
                             = data['features'], data['graph'], data['train_mask'], \
                             data['val_mask'], data['test_mask'], data['labels'], \
                             data['num_feats'], data['n_classes'], data['n_edges']


    # Configure
    np.random.seed(seed)
    torch.manual_seed(seed)

    if not args.no_cuda and torch.cuda.is_available():
        print('[ Using CUDA ]')
        device = torch.device('cuda' if args.gpu < 0 else 'cuda:%d' % args.gpu)
        cudnn.benchmark = True
        torch.cuda.manual_seed(seed)
    else:
        device = torch.device('cpu')

    features = features.to(device)
    labels = labels.to(device)
    train_mask = train_mask.to(device)
    val_mask = val_mask.to(device)
    test_mask = test_mask.to(device)

    g.ndata['node_feat'] = features

    # create model
    model = GNNClassifier(args.num_layers,
                          num_feats,
                          args.num_hidden,
                          n_classes,
                          args.direction_option)


    print(model)
    model.to(device)

    if args.early_stop:
        stopper = EarlyStopping('{}.{}'.format(args.save_model_path, seed), patience=args.patience)

    loss_fcn = torch.nn.CrossEntropyLoss()

    # use optimizer
    optimizer = torch.optim.Adam(
        model.parameters(), lr=args.lr, weight_decay=args.weight_decay)

    # initialize graph
    dur = []
    for epoch in range(args.epochs):
        model.train()
        if epoch >= 3:
            t0 = time.time()
        # forward
        logits = model(g)
        loss = loss_fcn(logits[train_mask], labels[train_mask])

        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        if epoch >= 3:
            dur.append(time.time() - t0)

        train_acc = accuracy(logits[train_mask], labels[train_mask])

        if args.fastmode:
            val_acc = accuracy(logits[val_mask], labels[val_mask])
        else:
            val_acc = evaluate(model, g, labels, val_mask)
            if args.early_stop:
                if stopper.step(val_acc, model):
                    break

        print("Epoch {:05d} | Time(s) {:.4f} | Loss {:.4f} | TrainAcc {:.4f} |"
              " ValAcc {:.4f} | ETputs(KTEPS) {:.2f}".
              format(epoch, np.mean(dur), loss.item(), train_acc,
                     val_acc, n_edges / np.mean(dur) / 1000))

    print()
    if args.early_stop:
        model = stopper.load_checkpoint(model)
    acc = evaluate(model, g, labels, test_mask)
    print("Test Accuracy {:.4f}".format(acc))

    return acc


if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='GGNN')
    register_data_args(parser)
    parser.add_argument("--num-runs", type=int, default=5,
                        help="number of runs")
    parser.add_argument("--no-cuda", action="store_true", default=False,
                        help="use CPU")
    parser.add_argument("--gpu", type=int, default=-1,
                        help="which GPU to use.")
    parser.add_argument("--epochs", type=int, default=200,
                        help="number of training epochs")
    parser.add_argument("--direction-option", type=str, default='uni',
                        help="direction type (`uni`, `bi_fuse`, `bi_sep`)")
    parser.add_argument("--num-heads", type=int, default=8,
                        help="number of hidden attention heads")
    parser.add_argument("--num-out-heads", type=int, default=1,
                        help="number of output attention heads")
    parser.add_argument("--num-layers", type=int, default=2,
                        help="number of hidden layers")
    parser.add_argument("--num-hidden", type=int, default=1433,
                        help="number of hidden units")
    parser.add_argument("--residual", action="store_true", default=False,
                        help="use residual connection")
    parser.add_argument("--in-drop", type=float, default=.6,
                        help="input feature dropout")
    parser.add_argument("--attn-drop", type=float, default=.6,
                        help="attention dropout")
    parser.add_argument("--lr", type=float, default=0.005,
                        help="learning rate")
    parser.add_argument('--weight-decay', type=float, default=5e-4,
                        help="weight decay")
    parser.add_argument('--negative-slope', type=float, default=0.2,
                        help="the negative slope of leaky relu")
    parser.add_argument('--early-stop', action='store_true', default=False,
                        help="indicates whether to use early stop or not")
    parser.add_argument("--patience", type=int, default=100,
                        help="early stopping patience")
    parser.add_argument('--fastmode', action="store_true", default=False,
                        help="skip re-evaluate the validation set")
    parser.add_argument('--save-model-path', type=str, default="checkpoint",
                        help="path to the best saved model")
    args = parser.parse_args()
    args.save_model_path = '{}_{}_{}_{}'.format(args.save_model_path, args.dataset, 'ggnn', args.direction_option)
    print(args)

    np.random.seed(123)
    scores = []
    for _ in range(args.num_runs):
        seed = np.random.randint(10000)
        scores.append(main(args, seed))

    print("\nTest Accuracy ({} runs): mean {:.4f}, std {:.4f}".format(args.num_runs, np.mean(scores), np.std(scores)))


# import time
# import numpy as np
# import torch
# import torch.nn as nn
# import torch.nn.functional as F
# from dgl import DGLGraph
# from dgl.data import citation_graph as citegrh
# from dgl.nn.pytorch.conv import GatedGraphConv
#
# from ...modules.graph_embedding.ggnn import GGNN
# # from graph4nlp.pytorch.modules.graph_embedding.ggnn import GGNN
#
# def load_cora_data():
#     data = citegrh.load_cora()
#     features = torch.FloatTensor(data.features)
#     labels = torch.LongTensor(data.labels)
#     mask = torch.BoolTensor(data.train_mask)
#     graph = DGLGraph(data.graph)
#     return graph, features, labels, mask, data.num_labels, data.val_mask, data.test_mask
#
#
# def accuracy(logits, labels):
#     _, indices = torch.max(logits, dim=1)
#     correct = torch.sum(indices == labels)
#     return correct.item() * 1.0 / len(labels)
#
# def evaluate(model, g, features, labels, mask):
#     model.eval()
#     with torch.no_grad():
#         logits = model(g, features)
#         logits = logits[mask]
#         labels = labels[mask]
#         return accuracy(logits, labels)
#
#
# class GNNClassifier(nn.Module):
#     def __init__(self,
#                 num_layers,
#                 input_size,
#                 output_size,
#                 n_class,
#                 direction_option):
#         super(GNNClassifier, self).__init__()
#         self.direction_option = direction_option
#         self.model = GGNN(num_layers, input_size, output_size, direction_option=direction_option)
#         # self.model = GatedGraphConv(input_size, output_size,n_steps=num_layers,n_etypes=1)
#
#         if self.direction_option == 'bi_sep':
#             self.fc = nn.Linear(2 * output_size, n_class)
#         else:
#             self.fc = nn.Linear(output_size, n_class)
#
#     def forward(self, graph, features):
#         etypes = torch.zeros(graph.number_of_edges())
#
#         logits = self.model(graph, features)
#         # logits = self.model(graph, features, etypes)
#         if self.direction_option == 'bi_sep':
#             logits = self.fc(F.elu(logits))
#         else:
#             logits = self.fc(F.elu(logits))
#
#         return logits
#
# if __name__ == '__main__':
#     graph, features, labels, mask, num_labels, val_mask, test_mask = load_cora_data()
#
#     # features = torch.zeros((features.size()[0], 100))
#
#     num_layers = 3
#     input_size = features.size()[1]
#     print(input_size)
#     output_size = features.size()[1]
#     direction_option = 'bi_sep' # 'uni', 'bi_sep', 'bi_fuse'
#     num_epochs = 100
#
#     classifier = GNNClassifier(num_layers,
#             input_size,
#             output_size,
#             num_labels,
#             direction_option)
#
#     # create optimizer
#     optimizer = torch.optim.Adam(classifier.parameters(), lr=1e-3)
#
#     # main loop
#     dur = []
#     for epoch in range(num_epochs):
#         t0 = time.time()
#         logits = classifier(graph, features)
#         assert logits.shape[-1] == num_labels
#
#         logp = F.log_softmax(logits, 1)
#         loss = F.nll_loss(logp[mask], labels[mask])
#
#         optimizer.zero_grad()
#         loss.backward()
#         optimizer.step()
#
#         dur.append(time.time() - t0)
#
#         train_acc = accuracy(logits[mask], labels[mask])
#         val_acc = evaluate(classifier, graph, features, labels, val_mask)
#
#         print("train_acc = "+str(train_acc))
#         print("val_acc = "+str(val_acc))
#
#         print("Epoch {} | Loss {:.4f} | Time(s) {:.2f}".format(
#             epoch, loss.item(), np.mean(dur)))

# from dgl.nn.pytorch import GatedGraphConv
# import torch.nn as nn
# import torch.nn.functional as F
# import dgl
# import torch
# from dgl.data import MiniGCDataset
# import torch.optim as optim
# from torch.utils.data import DataLoader
# import pickle as pkl
# from ...modules.graph_embedding.ggnn import GGNN
# import os
#
# dgl.random.seed(123)
# torch.manual_seed(123)
# torch.cuda.manual_seed(123)
# torch.backends.cudnn.deterministic = True
#
# def collate(samples):
#     # The input `samples` is a list of pairs
#     #  (graph, label).
#     graphs, labels = map(list, zip(*samples))
#     batched_graph = dgl.batch(graphs)
#     return batched_graph, torch.tensor(labels)
#
#
# class Classifier(nn.Module):
#     def __init__(self, in_dim, hidden_dim, n_classes, direction_option):
#         super(Classifier, self).__init__()
#
#         if direction_option=='bi_fuse':
#             self.encoder = GGNN(2, in_dim, hidden_dim, direction_option='bi_fuse')
#             self.classify = nn.Linear(hidden_dim, n_classes)
#         elif direction_option=='bi_sep':
#             self.encoder = GGNN(2, in_dim, hidden_dim, direction_option='bi_sep')
#             self.classify = nn.Linear(hidden_dim * 2, n_classes)
#         else:
#             self.encoder = GGNN(2, in_dim, hidden_dim, direction_option='uni')
#             self.classify = nn.Linear(hidden_dim, n_classes)
#
#
#     def forward(self, g, node_feats):
#         h = self.encoder(g, node_feats)
#         g.ndata['h'] = h
#         # Calculate graph representation by averaging all the node representations.
#         hg = dgl.mean_nodes(g, 'h')
#         return self.classify(hg)
#
#
# if __name__ == '__main__':
#     # Create training and test sets.
#     # trainset = MiniGCDataset(320, 10, 20)
#     # testset = MiniGCDataset(80, 10, 20)
#     # Use PyTorch's DataLoader and the collate function
#     # defined before.
#
#     # with open('train.pkl','wb') as f:
#     #     pkl.dump(trainset, f)
#     #
#     # with open('test.pkl','wb') as f:
#     #     pkl.dump(testset, f)
#
#     with open('graph4nlp/pytorch/test/graph_embedding/train.pkl','rb') as f:
#         trainset = pkl.load(f)
#
#     with open('graph4nlp/pytorch/test/graph_embedding/test.pkl','rb') as f:
#         testset = pkl.load(f)
#
#     data_loader = DataLoader(trainset, batch_size=8, shuffle=True,
#                              collate_fn=collate)
#
#     # Create model
#     model = Classifier(1, 256, trainset.num_classes, direction_option='uni')
#     loss_func = nn.CrossEntropyLoss()
#     optimizer = optim.Adam(model.parameters(), lr=0.001)
#     model.train()
#
#     epoch_losses = []
#     for epoch in range(30):
#         epoch_loss = 0
#         for iter, (bg, label) in enumerate(data_loader):
#             node_feats = bg.in_degrees().view(-1, 1).float()
#             prediction = model(bg, node_feats)
#             loss = loss_func(prediction, label)
#             optimizer.zero_grad()
#             loss.backward()
#             optimizer.step()
#             epoch_loss += loss.detach().item()
#         epoch_loss /= (iter + 1)
#         print('Epoch {}, loss {:.4f}'.format(epoch, epoch_loss))
#         epoch_losses.append(epoch_loss)
#
#     model.eval()
#     # Convert a list of tuples to two lists
#     test_X, test_Y = map(list, zip(*testset))
#     test_bg = dgl.batch(test_X)
#     test_Y = torch.tensor(test_Y).float().view(-1, 1)
#     test_node_feats = test_bg.in_degrees().view(-1, 1).float()
#     probs_Y = torch.softmax(model(test_bg, test_node_feats), 1)
#     sampled_Y = torch.multinomial(probs_Y, 1)
#     argmax_Y = torch.max(probs_Y, 1)[1].view(-1, 1)
#     print('Accuracy of sampled predictions on the test set: {:.4f}%'.format(
#         (test_Y == sampled_Y.float()).sum().item() / len(test_Y) * 100))
#     print('Accuracy of argmax predictions on the test set: {:4f}%'.format(
#         (test_Y == argmax_Y.float()).sum().item() / len(test_Y) * 100))