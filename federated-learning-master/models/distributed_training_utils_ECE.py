import torch
import copy
import math
from torch import nn, autograd
import numpy as np
from torch.utils.data import DataLoader
from utils.dataset import Dataset
import torch.nn.functional as F

max_norm = 10

def add(target, source):
    for name in target:
        target[name].data += source[name].data.clone()


def add_mome(target, source, beta_):
    for name in target:
        target[name].data = (beta_ * target[name].data + source[name].data.clone())


def add_mome2(target, source1, source2, beta_1, beta_2):
    for name in target:
        target[name].data = beta_1 * source1[name].data.clone() + beta_2 * source2[name].data.clone()


def HD_products(target, source):
    for name in target:
        target[name].data = source[name].data.clone() * source[name].data.clone()

def HD_division(target, source1, source2, tau):
    for name in target:
        target[name].data = source1[name].data.clone() / (torch.sqrt(source2[name].data.clone()) + tau)



def add_momeyogi(target, source1, source2):
    for name in target:
        target[name].data = source2[name].data.clone() * torch.sign(source1[name].data.clone() - source2[name].data.clone())

def add_mome3(target, source1, source2, source3, beta_1, beta_2, beta_3):
    for name in target:
        target[name].data = beta_1 * source1[name].data.clone() + beta_2 * source2[name].data.clone() + beta_3 * source3[name].data.clone()

def add_2(target, source1, source2, beta_1, beta_2):
    for name in target:
        target[name].data += beta_1 * source1[name].data.clone() + beta_2 * source2[name].data.clone()

def scale(target, scaling):
    for name in target:
        target[name].data = scaling * target[name].data.clone()


def scale_ts(target, source, scaling):
    for name in target:
        target[name].data = scaling * source[name].data.clone()


def subtract(target, source):
    for name in target:
        target[name].data -= source[name].data.clone()


def subtract_(target, minuend, subtrahend):
    for name in target:
        target[name].data = minuend[name].data.clone() - subtrahend[name].data.clone()


def average(target, sources):
    for name in target:
        target[name].data = torch.mean(torch.stack([source[name].data for source in sources]), dim=0).clone()

def weighted_average(target, sources, weights):
    for name in target:
        summ = torch.sum(weights)
        n = len(sources)
        modify = [weight / summ * n for weight in weights]
        target[name].data = torch.mean(torch.stack([m * source[name].data for source, m in zip(sources, modify)]),
                                       dim=0).clone()


def computer_norm(source1, source2):
    diff_norm = 0

    for name in source1:
        diff_source = source1[name].data.clone() - source2[name].data.clone()
        diff_norm += torch.pow(torch.norm(diff_source),2)

    return (torch.pow(diff_norm, 0.5))

def majority_vote(target, sources, lr):
    for name in target:
        threshs = torch.stack([torch.max(source[name].data) for source in sources])
        mask = torch.stack([source[name].data.sign() for source in sources]).sum(dim=0).sign()
        target[name].data = (lr * mask).clone()


def get_mdl_params(model_list, n_par=None):
    if n_par == None:
        exp_mdl = model_list[0]
        n_par = 0
        for name, param in exp_mdl.named_parameters():
            n_par += len(param.data.reshape(-1))

    param_mat = np.zeros((len(model_list), n_par)).astype('float32')
    for i, mdl in enumerate(model_list):
        idx = 0
        for name, param in mdl.named_parameters():
            temp = param.data.cpu().numpy().reshape(-1)
            param_mat[i, idx:idx + len(temp)] = temp
            idx += len(temp)
    return np.copy(param_mat)


def get_other_params(model_list, n_par=None):
    if n_par == None:
        exp_mdl = model_list[0]
        n_par = 0
        for name in exp_mdl:
            n_par += len(exp_mdl[name].data.reshape(-1))

    param_mat = np.zeros((len(model_list), n_par)).astype('float32')
    for i, mdl in enumerate(model_list):
        idx = 0
        for name in mdl:
            temp = mdl[name].data.cpu().numpy().reshape(-1)
            param_mat[i, idx:idx + len(temp)] = temp
            idx += len(temp)
    return np.copy(param_mat)


class DistributedTrainingDevice(object):
    '''
  A distributed training device (Client or Server)
  data : a pytorch dataset consisting datapoints (x,y)
  model : a pytorch neural net f mapping x -> f(x)=y_
  hyperparameters : a python dict containing all hyperparameters
  '''

    def __init__(self, model, args):
        self.model = model
        self.args = args
        self.loss_func = nn.CrossEntropyLoss()

class Client(DistributedTrainingDevice):

    def __init__(self, model, args, trn_x, trn_y, dataset_name, id_num=0):
        super().__init__(model, args)

        self.trn_gen = DataLoader(Dataset(trn_x, trn_y, train=True, dataset_name=dataset_name),
                                  batch_size=self.args.local_bs, shuffle=True)
        self.id = id_num
        self.local_epoch = int(np.ceil(trn_x.shape[0] / self.args.local_bs))
        # Parameters
        self.W = {name: value for name, value in self.model.named_parameters()}
        self.W_old = {name: torch.zeros(value.shape).to(self.args.device) for name, value in self.W.items()}
        self.dW = {name: torch.zeros(value.shape).to(self.args.device) for name, value in self.W.items()}
        self.prior_buffer = {name: torch.zeros(value.shape).to(self.args.device) for name, value in self.W.items()}
        self.alpha = self.args.alpha
        self.state_params_diff = 0.0
        self.train_loss = 0.0
        self.n_par = get_mdl_params([self.model]).shape[1]

    def synchronize_with_server(self, server):
        # W_client = W_server
        self.model = copy.deepcopy(server.model)
        self.W = {name: value for name, value in self.model.named_parameters()}

    def gaussian_noise(self, data_):
        # works with integers as well as tuples
        Gaussian_ = {name: torch.randn_like(value).to(self.args.device) for name, value in data_.items()}
        return Gaussian_

    def train_cnn(self, server, m, iter):

        self.model.train()

        if self.args.method == 'fedciw':
            optimizer = torch.optim.SGD(self.model.parameters(), lr=self.args.lr, momentum=self.args.momentum,
                                        weight_decay = self.args.weigh_delay)
            self.variance_prior = 1 / m * self.args.local_ep * self.local_epoch * self.args.noise_scale

        elif self.args.method == 'fedavg':
            optimizer = torch.optim.SGD(self.model.parameters(), lr=self.args.lr, momentum=self.args.momentum,
                                        weight_decay=self.args.weigh_delay)
        # train and update
        epoch_loss = []


        for j in range(self.args.local_ep):
            trn_gen_iter = self.trn_gen.__iter__()
            batch_loss = []
            for i in range(self.local_epoch):

                images, labels = trn_gen_iter.__next__()
                images, labels = images.to(self.args.device), labels.to(self.args.device)

                optimizer.zero_grad()
                log_probs = self.model(images)
                loss_f_i = self.loss_func(log_probs, labels.reshape(-1).long())

                if self.args.method == 'fedciw':
                    loss = loss_f_i
                elif self.args.method == 'fedavg':
                    loss = loss_f_i
                else:
                    exit('Error: unrecognized parameter')

                loss.backward()

                torch.nn.utils.clip_grad_norm_(parameters=self.model.parameters(), max_norm=max_norm)

                if self.args.method == 'fedciw':
                    self.gradient = {name: value.grad for name, value in self.model.named_parameters()}

                    add_mome2(target=self.prior_buffer, source1 = self.W, source2 = server.W, beta_1 = 1, beta_2 = -1)
                    self.variance_prior = 1/m * self.args.local_ep * self.local_epoch * self.args.noise_scale
                    scale(target= self.prior_buffer, scaling = self.args.alpha / self.variance_prior)
                    add_mome2(target=self.W, source1=self.W, source2=self.prior_buffer, beta_1=1,
                              beta_2= - self.args.lr)

                    add_mome2(target=self.W, source1=self.W, source2=self.gradient, beta_1=1, beta_2=- self.args.lr)

                    gaussian_sample = self.gaussian_noise(self.gradient)
                    add_mome2(target=self.W, source1=self.W, source2=gaussian_sample, beta_1 = 1, beta_2 = self.args.noise_scale)

                elif self.args.method == 'fedavg':
                    self.gradient = {name: value.grad for name, value in self.model.named_parameters()}
                    add_mome2(target=self.W, source1=self.W, source2=self.gradient, beta_1=1, beta_2 = - self.args.lr)

                else:
                    exit('Error: unrecognized parameter')

                batch_loss.append(loss.item())

            epoch_loss.append(sum(batch_loss) / len(batch_loss))

        return sum(epoch_loss) / len(epoch_loss)

    def compute_weight_update(self, server, m, iter):

        # Training mode
        self.model.train()

        # W_old = W
        self.W_old = copy.deepcopy(self.W)

        # W = SGD(W, D)
        self.train_loss = self.train_cnn(server, m, iter)

        # dW = W - W_old
        subtract_(target=self.dW, minuend=self.W, subtrahend=self.W_old)


class Server(DistributedTrainingDevice):

    def __init__(self, model, args):
        super().__init__(model, args)

        # Parameters
        self.W = {name: value for name, value in self.model.named_parameters()}
        self.dW = {name: torch.zeros(value.shape).to(self.args.device) for name, value in self.W.items()}
        self.mome = {name: torch.zeros(value.shape).to(self.args.device) for name, value in self.W.items()}

        self.local_epoch = 0

    def aggregate_weight_updates(self, clients, iter, aggregation="mean"):

        # dW = aggregate(dW_i, i=1,..,n)
        if aggregation == "mean":
            average(target=self.dW, sources=[client.dW for client in clients])
        elif aggregation == "weighted_mean":
            weighted_average(target=self.dW, sources=[client.dW for client in clients], weights=[client.size for client in clients])

    def computer_weight_update_down_dw(self, clients, iter):

        # Warning: Note that K is different for unbalanced dataset
        self.local_epoch = clients[0].local_epoch

        if self.args.method == 'fedciw':
            add_mome2(target=self.mome, source1=self.mome, source2=self.dW, beta_1=self.args.beta_,
                      beta_2= 1 - self.args.beta_)

            #scale(target=self.mome, scaling = 1 / (1-self.args.beta_**(iter+1)) )

            add_mome2(target=self.W, source1=self.W, source2=self.mome, beta_1=1,
                      beta_2=self.args.globallr)

        elif self.args.method == 'fedavg':
            add_mome2(target=self.mome, source1=self.mome, source2=self.dW, beta_1=self.args.beta_,
                      beta_2=1 - self.args.beta_)

            #scale(target=self.mome, scaling=1 / (1 - self.args.beta_ ** (iter + 1)))

            add_mome2(target=self.W, source1=self.W, source2=self.mome, beta_1=1, beta_2=self.args.globallr)

        else:
            exit('Error: unrecognized parameter')
    @torch.no_grad()
    def evaluate(self, data_x, data_y, dataset_name):
        self.model.eval()
        # testing
        test_loss = 0
        acc_overall = 0
        n_tst = data_x.shape[0]
        log_probs_all = np.zeros([1,n_tst], dtype = float)
        target_all = np.zeros([1,n_tst], dtype = int)

        iter_n = int(np.ceil(n_tst / self.args.bs))

        tst_gen = DataLoader(Dataset(data_x, data_y, dataset_name=dataset_name), batch_size=self.args.bs, shuffle=False)
        tst_gen_iter = tst_gen.__iter__()
        for i in range(int(np.ceil(n_tst / self.args.bs))):
            data, target = tst_gen_iter.__next__()
            data, target = data.to(self.args.device), target.to(self.args.device)
            log_probs = self.model(data)
            # sum up batch loss
            test_loss += nn.CrossEntropyLoss(reduction='sum')(log_probs, target.reshape(-1).long()).item()
            # get the index of the max log-probability
            log_probs_softmax = F.softmax(log_probs, dim=1)
            log_probs = log_probs.cpu().detach().numpy()
            log_probs_i = np.argmax(log_probs, axis=1).reshape(-1)
            target = target.cpu().numpy().reshape(-1).astype(np.int32)
            batch_correct = np.sum(log_probs_i == target)
            acc_overall += batch_correct
            '''
            y_pred = log_probs.data.max(1, keepdim=True)[1]
            correct += y_pred.eq(target.data.view_as(y_pred)).long().cpu().sum()
            '''
            log_probs_softmax = log_probs_softmax.cpu().detach().numpy()
            log_probs_all[:, i * self.args.bs:(i+1) *self.args.bs] = np.max(log_probs_softmax, axis=1)
            target_all[:, i * self.args.bs:(i + 1) * self.args.bs] = (log_probs_i == target).astype(int)

            test_loss /= n_tst

        log_probs_all = np.squeeze(log_probs_all)
        target_all = np.squeeze(target_all)

        sorted_indices = np.argsort(log_probs_all)
        log_probs_all_c = log_probs_all[sorted_indices]
        target_all_c = target_all[sorted_indices]

        split_logc = np.array_split(log_probs_all_c, self.args.bin_n)
        split_tar = np.array_split(target_all_c, self.args.bin_n)
        result = [np.mean(group_A) - np.mean(group_B) for group_A, group_B in zip(split_logc, split_tar)]


        accuracy = 100.00 * acc_overall / n_tst
        return accuracy, test_loss, result, split_logc



