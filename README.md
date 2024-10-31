# Improving Generalization in Federated Learning with Model-Data Mutual Information Regularization: A Posterior Inference Approach

This directory contains source code for evaluating federated learning with different optimizers on various models and tasks. The code was developed for a paper, "Improving Generalization in Federated Learning with Model-Data Mutual Information Regularization: A Posterior Inference Approach".

## Requirements

Some pip packages are required by this library, and may need to be installed. For more details, see `requirements.txt`. We recommend running `pip install --requirement "requirements.txt"`.

Below we give a summary of the datasets, tasks, and models used in this code.


Note that we put the dataset under the directory .\federated-learning-master\Folder

<!-- mdformat off(This table is sensitive to automatic formatting changes) -->

| Directory        | Model                               | Task Summary              |
|------------------|-------------------------------------|---------------------------|
| CIFAR-10         | CNN (with two convolutional layers) | Image classification      |
| CIFAR-100        | CNN (with two convolutional layers) | Image classification      |
| Shakespeare      | RNN with 2 LSTM layers              | Next-character prediction |

<!-- mdformat on -->


## Training
In this code, we compare optimization methods in our experiments. Those methods use vanilla SGD on clients. To recreate our experimental results for each optimizer, for example, for 100 clients and 5% participation rate, on the cifar100 data set with Dirichlet (0.2) split, run those commands for some methods:

**FedMDMI**:
```
python main_fed.py --seed 200 --gpu 1 --epochs 4000  --num_users 100 --frac 0.05 --dataset CIFAR100 --iid Dirichlet --rule_arg 0.2 --local_ep 5 --local_bs 100  --lr 0.1 --globallr 12 --weigh_delay 0 --lr_decay 0.999 --noise_scale -1 --alpha 0.000000001 --beta_ 0.9 --method fedciw --filepath fedciw_CIFAR100_lpha0000000001_0.2_gl12lr0.1_0.999.txt
```



## Other hyperparameters and reproducibility

All other hyperparameters are set by default to the values used in the `Experiment Details` of our Appendix. This includes the batch size, the number of clients per round, the number of client local updates, local learning rate, and model parameter flags. While they can be set for different behavior (such as varying the number of client local updates), they should not be changed if one wishes to reproduce the results from our paper. 

