#!/usr/bin/env python
"""
title           :train_vae.py
description     :Contains the main trainign loop and test time evaluation of the model.
author          :Yordan Hristov <yordan.hristov@ed.ac.uk
date            :10/2018
python_version  :2.7.16
==============================================================================
"""

# Misc
import argparse
import os
import cv2
import numpy as np
from scipy.stats import multivariate_normal
from scipy.stats import norm
import matplotlib
matplotlib.use('agg')
import matplotlib.pyplot as plt
import subprocess
import shutil
import json

# Chaier
import chainer
from chainer import training
from chainer.training import extensions
from chainer.dataset import concat_examples
from chainer.backends.cuda import to_cpu
import chainer.functions as F
from chainer import serializers

# Sibling Modules
import net_100x100 as net
import data_generator
from config_parser import ConfigParser
from utils import *


def main():
    parser = argparse.ArgumentParser(description='Chainer example: VAE')
    parser.add_argument('--gpu', default=0, type=int,
                        help='GPU ID (negative value indicates CPU)')
    parser.add_argument('--out', '-o', default='result/',
                        help='Directory to output the result')
    parser.add_argument('--config', default='config/',
                        help='Directory to load the config from')
    parser.add_argument('--epoch_labelled', '-e', default=100, type=int,
                        help='Number of epochs to learn only with labelled data')
    parser.add_argument('--epoch_unlabelled', '-u', default=100, type=int,
                    help='Number of epochs to learn with labelled and unlabelled data')
    parser.add_argument('--dimz', '-z', default=8, type=int,
                        help='Dimention of encoded vector')
    parser.add_argument('--batchsize', '-batch', type=int, default=32,
                        help='Learning minibatch size')
    parser.add_argument('--beta', '-b', default=1,
                        help='Beta coefficient for the KL loss')
    parser.add_argument('--gamma', '-g', default=1,
                        help='Gamma coefficient for the classification loss')
    parser.add_argument('--alpha', '-a', default=1, 
                        help='Alpha coefficient for the reconstruction loss')
    parser.add_argument('--freq', '-f', default=40, 
                    help='Frequency at which snapshots of the model are saved.')
    parser.add_argument('--mode', default="supervised", 
                    help='Mode of training - weakly supervised or unsupervised')
    parser.add_argument('--augment_counter', type=int, default=0, 
                    help='Number ot times to augment the train data')
    parser.add_argument('--model', default="full", 
                    help='Model to be trained')
    args = parser.parse_args()

    args.out = args.out + args.model

    print('\n###############################################')
    print('# GPU: \t\t\t{}'.format(args.gpu))
    print('# dim z: \t\t{}'.format(args.dimz))
    print('# Minibatch-size: \t{}'.format(args.batchsize))
    print('# Epochs Labelled: \t{}'.format(args.epoch_labelled))
    print('# Epochs Unabelled: \t{}'.format(args.epoch_unlabelled))
    print('# Beta: \t\t{}'.format(args.beta))
    print('# Gamma: \t\t{}'.format(args.gamma))
    print('# Frequency: \t\t{}'.format(args.freq))
    print('# Out Folder: \t\t{}'.format(args.out))
    print('###############################################\n')

    stats = {'train_loss': [], 'train_accs': [], 'valid_loss': [], 'valid_rec_loss': [], 'valid_label_loss': [],\
         'valid_label_acc': [], 'valid_kl': [], 'train_kl': []}

    models_folder = os.path.join(args.out, "models")
    # manifold_gif = os.path.join(args.out, "gifs/manifold_gif")
    # scatter_gif = os.path.join(args.out, "gifs/scatter_gif")
    # scatter_folder = os.path.join(args.out, "scatter")
    # eval_folder = os.path.join(args.out, "eval")
    # shutil.rmtree(os.path.join(args.out, "models"))
    # os.mkdir(os.path.join(args.out, "models"))

    if args.mode == "unsupervised":
        ignore = ["unseen"]
    else:
        ignore = ["unseen", "unlabelled"]

    generator = data_generator.DataGenerator(augment_counter=args.augment_counter)
    train_b0, train_b1, train_labels, train_concat, train_vectors, test_b0, test_b1, test_labels, test_concat, test_vectors, unseen_b0, unseen_b1,\
    unseen_labels, groups = generator.generate_dataset(ignore=ignore, args=args)

    # test_unseen = np.append(test, unseen, axis=0)
    # test_unseen_labels = np.append(test_labels, unseen_labels, axis=0)

    data_dimensions = train_b0.shape
    print('\n###############################################')
    print("DATA_LOADED")
    print("# Training Branch 0: \t\t{0}".format(train_b0.shape))
    print("# Training Branch 1: \t\t{0}".format(train_b1.shape))
    print("# Training labels: \t{0}".format(set(train_labels)))
    print("# Training labels: \t{0}".format(train_labels.shape))
    print("# Training concat: \t{0}".format(len(train_concat)))
    print("# Training vectors: \t{0}".format(train_vectors.shape))
    print("# Testing Branch 0: \t\t{0}".format(test_b0.shape))
    print("# Testing Branch 1: \t\t{0}".format(test_b1.shape))
    print("# Testing labels: \t{0}".format(set(test_labels)))
    print("# Testing concat: \t{0}".format(len(test_concat)))
    print("# Testing labels: \t{0}".format(test_labels.shape))
    print("# Testing vectors: \t{0}".format(test_vectors.shape))
    print("# Unseen Branch 0: \t\t{0}".format(unseen_b0.shape))
    print("# Unseen Branch 1: \t\t{0}".format(unseen_b1.shape))
    print("# Unseen labels: \t{0}".format(set(unseen_labels)))

    print("\n# Groups: \t{0}".format(groups))
    print('###############################################\n')

    train_iter = chainer.iterators.SerialIterator(train_concat, args.batchsize)
    test_iter = chainer.iterators.SerialIterator(test_concat, args.batchsize,
                                                 repeat=False, shuffle=False)

    if args.model == "full" or args.model == "var_classifier":
        model = net.Conv_Siam_VAE(train_b0.shape[1], train_b1.shape[1], n_latent=args.dimz, groups=groups, alpha=args.alpha, beta=args.beta, gamma=args.gamma)
    elif args.model == "classifier":
        model = net.Conv_Siam_Classifier(train_b0.shape[1], train_b1.shape[1], n_latent=args.dimz, groups=groups, alpha=args.alpha, beta=args.beta, gamma=args.gamma)
    elif args.model == "beta_vae":
        model = net.Conv_Siam_BetaVAE(train_b0.shape[1], train_b1.shape[1], n_latent=args.dimz, groups=groups, alpha=args.alpha, beta=args.beta, gamma=args.gamma)
    elif args.model == "autoencoder":
        model = net.Conv_Siam_AE(train_b0.shape[1], train_b1.shape[1], n_latent=args.dimz, groups=groups, alpha=args.alpha, beta=args.beta, gamma=args.gamma)


    # vs = model.get_latent(test_b0[:8], test_b0[:8])
    # vs = model(test_b0[:8], test_b1[:8])
    # import chainer.computational_graph as c
    # g = c.build_computational_graph(vs)
    # with open('./result/file.dot', 'w') as o:
    #     o.write(g.dump())
    # exit()




    if args.gpu >= 0:
        # Make a specified GPU current
        chainer.cuda.get_device_from_id(args.gpu).use()
        model.to_gpu()

    # Setup an optimizer
    optimizer = chainer.optimizers.Adam()
    # optimizer = chainer.optimizers.RMSprop()
    optimizer.setup(model)
    optimizer.add_hook(chainer.optimizer_hooks.WeightDecay(0.0005))

    lf = model.get_loss_func()
    no_std = 1

    config_parser = ConfigParser(os.path.join(args.config, "config.json"))
    n_groups = len(groups.keys())
    
    stats, model, optimizer, _ = training_loop(model=model, optimizer=optimizer, stats=stats, 
                                                           epochs=args.epoch_labelled, train_iter=train_iter, 
                                                           test_iter=test_iter, lf=lf, models_folder=models_folder, 
                                                           mode="supervised", args=args)

    print("Save Model\n")
    serializers.save_npz(os.path.join(models_folder, 'final.model'), model)

    print("Save Optimizer\n")
    serializers.save_npz(os.path.join(models_folder, 'final.state'), optimizer)

    exit()  

    # print("Clear Images from Last experiment\n")
    # clear_last_results(folder_name=args.out)

########################################
########### RESULTS ANALYSIS ###########
########################################

    model.to_cpu()
    latent_stats = {str(key) : {} for key in groups.keys()}

    # print("Plottong Loss Curves\n")
    # plot_loss_curves(stats=stats, args=args)

    print("Saving Reconstruction Arrays\n")
    no_images = 10
    train_ind = np.linspace(0, len(train_b0) - 1, no_images, dtype=int)
    result = model(train_b0[train_ind], train_b1[train_ind])

    gt_b0 = np.swapaxes(train_b0[train_ind], 1, 3)
    gt_b1 = np.swapaxes(train_b1[train_ind], 1, 3)

    rec_b0 = np.swapaxes(result[0].data, 1, 3)
    rec_b1 = np.swapaxes(result[1].data, 1, 3)

    output = {"gt_b0": gt_b0, "gt_b1": gt_b1, 'rec_b0': rec_b0, 'rec_b1': rec_b1}
    np.savez(os.path.join(args.out, "reconstruction_arrays/train" + ".npz"), **output)

    axis_ranges = [-15, 15]
    pairs = [(0,1)]
    # pairs = list(itertools.combinations(range(len(groups)), 2))

    for group_key in groups:

        tmp = {'mu': None, 'cov': None}

        indecies = [i for i, x in enumerate(test_labels) if x in groups[group_key]]
        filtered_data_b0 = test_b0.take(indecies, axis=0)
        # filtered_data_b0 = filtered_data_b0[::len(filtered_data_b0) / 100 + 1]
        filtered_data_b1 = test_b1.take(indecies, axis=0)
        # filtered_data_b1 = filtered_data_b1[::len(filtered_data_b1) / 100 + 1]
        
        latent = model.get_latent(filtered_data_b0, filtered_data_b1).data
        # latent = latent.reshape(latent.shape[:-1])
        
        tmp['mu'] = np.mean(latent, axis=1)
        tmp['cov'] = np.cov(latent, rowvar=0)

        print("Saving the latent stats for group: {0}\n".format(str(group_key)))
        path = osp.join('result', 'stats', str(group_key) + '_' + 'stats.npz')
        np.savez(path, **tmp)


        for label in groups[group_key]:

            latent_stats[str(group_key)][label] = {'mu': None, 'std': None}
            
            print("Visualising label:\t{0}, Group:\t{1}".format(label, group_key))

            # indecies = [i for i, x in enumerate(train_labels) if x == label]
            # filtered_data_b0 = train_b0.take(indecies, axis=0)
            # filtered_data_b0 = filtered_data_b0[::len(filtered_data_b0) / 100 + 1]
            # filtered_data_b1 = train_b1.take(indecies, axis=0)
            # filtered_data_b1 = filtered_data_b1[::len(filtered_data_b1) / 100 + 1]
            # print(filtered_data_b0.shape)

            # latent = np.array(model.get_latent(filtered_data_b0, filtered_data_b1))
            # for pair in pairs:
            #     plt.scatter(latent[pair[0], :], latent[pair[1], :], c='red', label=label, alpha=0.75)
            #     plt.grid()

            #     # major axes
            #     plt.plot([axis_ranges[0], axis_ranges[1]], [0,0], 'k')
            #     plt.plot([0,0], [axis_ranges[0], axis_ranges[1]], 'k')

            #     # plt.xlim(axis_ranges[0], axis_ranges[1])
            #     # plt.ylim(axis_ranges[0], axis_ranges[1])

            #     plt.xlabel("Z_" + str(pair[0]))
            #     plt.ylabel("Z_" + str(pair[1]))
                
            #     plt.legend(loc='upper left', bbox_to_anchor=(1, 1), fontsize=14)
            #     plt.savefig("result/scatter/train_group_" + str(group_key) + "_" + label + "_Z_" + str(pair[0]) + "_Z_" + str(pair[1]), bbox_inches="tight")
            #     plt.close()


            indecies = [i for i, x in enumerate(test_labels) if x == label]
            filtered_data_b0 = test_b0.take(indecies, axis=0)
            # filtered_data_b0 = filtered_data_b0[::len(filtered_data_b0) / 100 + 1]
            filtered_data_b1 = test_b1.take(indecies, axis=0)
            # filtered_data_b1 = filtered_data_b1[::len(filtered_data_b1) / 100 + 1]
            print(filtered_data_b0.shape)

            latent = model.get_latent(filtered_data_b0, filtered_data_b1).data
            # latent = latent.reshape(latent.shape[:-1])

            # calculate the latent_stats for the cluster corresponding to label
            latent_stats[str(group_key)][label]['mu'] = np.mean(latent[group_key])
            latent_stats[str(group_key)][label]['std'] = np.cov(latent[group_key])

            for pair in pairs:
                plt.scatter(latent[:, pair[0]], latent[:, pair[1]], c='red', label=label, alpha=0.75)
                plt.grid()

                # major axes
                plt.plot([axis_ranges[0], axis_ranges[1]], [0,0], 'k')
                plt.plot([0,0], [axis_ranges[0], axis_ranges[1]], 'k')

                # plt.xlim(axis_ranges[0], axis_ranges[1])
                # plt.ylim(axis_ranges[0], axis_ranges[1])

                plt.xlabel("Z_" + str(pair[0]))
                plt.ylabel("Z_" + str(pair[1]))
                
                plt.legend(loc='upper left', bbox_to_anchor=(1, 1), fontsize=14)
                plt.savefig("result/scatter/test_group_" + str(group_key) + "_" + label + "_Z_" + str(pair[0]) + "_Z_" + str(pair[1]), bbox_inches="tight")
                plt.close()

                print("Saving the latent stats for group: {0}, label: {1}\n".format(str(group_key), label))
                path = osp.join('result', 'stats', str(group_key) + '_' + label + '_' + 'stats.npz')
                np.savez(path, **latent_stats[str(group_key)][label])

    # print("Saving the latent clusters' latent_stats\n")
    # fileOut = open("result/scatter/latent_stats.json", "w")
    # json.dump(latent_stats, fileOut)
    # fileOut.close()



def training_loop(model=None, optimizer=None, stats=None, epochs=None, train_iter=None, test_iter=None, lf=None, 
                  models_folder=None, epochs_so_far=0, mode=None, args=None):

    train_losses = []
    train_accs = []
    train_kl = []

    while train_iter.epoch < epochs:
        # ------------ One epoch of the training loop ------------
        # ---------- One iteration of the training loop ----------
        train_batch = train_iter.next()

        image_train = concat_examples(train_batch, 0)

        # Calculate the loss with softmax_cross_entropy
        train_loss, train_rec_loss, train_label_loss, acc, t_kl, = model.get_loss_func()(image_train)
        train_losses.append(train_loss.array)
        train_kl.append(t_kl.array)
        if type(acc) != int:
            train_accs.append(acc.array)
        model.cleargrads()
        train_loss.backward()

        # Update all the trainable paremters
        optimizer.update()


        if train_iter.epoch % int(args.freq) == 0:
            serializers.save_npz(os.path.join(models_folder ,str(train_iter.epoch + epochs_so_far) + '.model'), model)

        # --------------------- iteration until here --------------------- 

        if train_iter.is_new_epoch:

            test_losses = []
            test_accs = []
            test_rec_losses = []
            test_label_losses = []
            test_kl = []

            test_accs_1 = []
            test_accs_2 = []
            while True:

                test_batch = test_iter.next()

                image_test = concat_examples(test_batch, 0)

                loss, rec_loss, label_loss, label_acc, kl = model.get_loss_func()(image_test)

                test_losses.append(loss.array)
                test_rec_losses.append(rec_loss.array)
                if type(label_loss) != int:
                    test_label_losses.append(label_loss.array)
                if type(label_acc) != int:
                    test_accs.append(label_acc.array)
                test_kl.append(kl.array)

                if test_iter.is_new_epoch:
                    test_iter.epoch = 0
                    test_iter.current_position = 0
                    test_iter.is_new_epoch = False
                    test_iter._pushed_position = None
                    break

            stats['train_loss'].append(np.mean(to_cpu(train_losses)))
            stats['train_accs'].append(np.mean(to_cpu(train_accs)))
            stats['valid_loss'].append(np.mean(to_cpu(test_losses)))
            stats['valid_rec_loss'].append(np.mean(to_cpu(test_rec_losses)))
            stats['valid_label_loss'].append(np.mean(to_cpu(test_label_losses)))
            stats['valid_label_acc'].append(np.mean(to_cpu(test_accs)))

            stats['valid_kl'].append(np.mean(to_cpu(test_kl)))
            stats['train_kl'].append(np.mean(to_cpu(train_kl)))
    
            print(("Epoch: {0} \t T_Loss: {1} \t V_Loss: {2} \t V_Rec_Loss: {3} \t V_Label_Loss: {4} \t " + \
                  "T_KL: {6} \t V_KL: {7} \t T_Acc: {8} \t V_Acc: {5}").format(train_iter.epoch, 
                                                                round(stats['train_loss'][-1], 2),
                                                                round(stats['valid_loss'][-1], 2),
                                                                round(stats['valid_rec_loss'][-1], 2),
                                                                round(stats['valid_label_loss'][-1], 2),
                                                                round(stats['valid_label_acc'][-1], 2),
                                                                # round(stats['valid_label_acc_1'][-1], 2),
                                                                # round(stats['valid_label_acc_2'][-1], 2),
                                                                round(stats['train_kl'][-1], 2),
                                                                round(stats['valid_kl'][-1], 2),
                                                                round(stats['train_accs'][-1], 2)))
            train_losses = []
            train_accs = []
            train_kl = []
    return stats, model, optimizer, epochs


if __name__ == '__main__':
    main()
