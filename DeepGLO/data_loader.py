import torch, h5py
import numpy as np
from scipy.io import loadmat

import torch.nn as nn
import torch.optim as optim
import numpy as np

# import matplotlib
from torch.autograd import Variable
import itertools
from sklearn.preprocessing import normalize
import datetime
import json
import os, sys
import pandas as pd
import pyarrow.parquet as pq
from DeepGLO.Ftree import *


class data_loader(object):
    """
    Data Loader Class for DeepGLO
    """

    def __init__(
        self,
        Ymat,
        covariates=None,
        Ycov=None,
        vbsize=200,
        hbsize=100,
        end_index=20000,
        val_len=30,
        shuffle=False,
    ):
        """
        Argeuments:
        Ymat: time-series matrix n*T
        covariates: global covariates common for all time series r*T, where r is the number of covariates
        Ycov: per time-series covariates n*l*T, l such covariates per time-series
        All of the above arguments are numpy arrays
        vbsize: vertical batch size
        hbsize: horizontal batch size
        end_index: training and validation set is only from 0:end_index
        val_len: validation length. The last 'val_len' time-points for every time-series is the validation set
        shuffle: data is shuffles if True (this is deprecated and set to False)
        """
        n, T = Ymat.shape
        self.vindex = 0
        self.hindex = 0
        self.epoch = 0
        self.vbsize = vbsize
        self.hbsize = hbsize
        self.Ymat = Ymat
        self.val_len = val_len
        self.end_index = end_index
        self.val_index = np.random.randint(0, n - self.vbsize - 5)
        self.shuffle = shuffle
        self.I = np.array(range(n))
        self.covariates = covariates
        self.Ycov = Ycov

    def next_batch(self, option=1):
        """
        Arguments:
        option = 1 means data is returned as pytorch tensor of shape nd*cd*td where nd is vbsize, hb is hsize and cd is the number os channels (depends on covariates) 
        option = 0 is deprecated
        Returns:
        inp: input batch
        out: one shifted output batch
        vindex: strating vertical index of input batch
        hindex: starting horizontal index of input batch
        """
        n, T = self.Ymat.shape
        if self.hindex + self.hbsize + 1 >= self.end_index:
            pr_hindex = self.hindex
            self.hindex = 0
            if self.vindex + self.vbsize >= n:
                pr_vindex = self.vindex
                self.vindex = 0
                self.epoch = self.epoch + 1
                if self.shuffle:
                    I = np.random.choice(n, n, replace=False)
                    self.I = I
                    self.Ymat = self.Ymat[self.I, :]
            else:
                pr_vindex = self.vindex
                self.vindex = self.vindex + self.vbsize
        else:
            pr_hindex = self.hindex
            self.hindex = self.hindex + self.hbsize
            pr_vindex = self.vindex

        data = self.Ymat[
            int(pr_vindex) : int(pr_vindex + self.vbsize),
            int(pr_hindex) : int(min(self.end_index, pr_hindex + self.hbsize)),
        ]
        out_data = self.Ymat[
            int(pr_vindex) : int(pr_vindex + self.vbsize),
            int(pr_hindex + 1) : int(min(self.end_index, pr_hindex + self.hbsize) + 1),
        ]
        nd, Td = data.shape
        if self.covariates is not None:
            covs = self.covariates[
                :, int(pr_hindex) : int(min(self.end_index, pr_hindex + self.hbsize))
            ]
            rcovs = np.repeat(
                covs.reshape(1, covs.shape[0], covs.shape[1]), repeats=nd, axis=0
            )

        if self.Ycov is not None:
            ycovs = self.Ycov[
                int(pr_vindex) : int(pr_vindex + self.vbsize),
                :,
                int(pr_hindex) : int(min(self.end_index, pr_hindex + self.hbsize)),
            ]
        if option == 1:
            inp = torch.from_numpy(data).view(1, nd, Td)
            out = torch.from_numpy(out_data).view(1, nd, Td)
            if self.covariates is not None:
                rcovs = torch.from_numpy(rcovs).float()
            if self.Ycov is not None:
                ycovs = torch.from_numpy(ycovs).float()
            inp = inp.transpose(0, 1).float()
            if self.covariates is not None:
                inp = torch.cat((inp, rcovs), 1)
            if self.Ycov is not None:
                inp = torch.cat((inp, ycovs), 1)
            out = out.transpose(0, 1).float()
        else:
            inp = torch.from_numpy(data).float()
            out = torch.from_numpy(out_data).float()

        inp[torch.isnan(inp)] = 0
        out[torch.isnan(out)] = 0

        return inp, out, self.vindex, self.hindex

    def supply_test(self, option=1):
        """
        Supplies validation set in the same format as above
        """
        n, T = self.Ymat.shape
        index = self.val_index
        in_data = self.Ymat[
            int(index) : int(index + self.vbsize),
            int(self.end_index) : int(self.end_index + self.val_len),
        ]
        out_data = self.Ymat[
            int(index) : int(index + self.vbsize),
            int(self.end_index + 1) : int(self.end_index + self.val_len + 1),
        ]
        nd, Td = in_data.shape
        if self.covariates is not None:
            covs = self.covariates[
                :, int(self.end_index) : int(self.end_index + self.val_len)
            ]
            rcovs = np.repeat(
                covs.reshape(1, covs.shape[0], covs.shape[1]), repeats=nd, axis=0
            )
        if self.Ycov is not None:
            ycovs = self.Ycov[
                int(index) : int(index + self.vbsize),
                :,
                int(self.end_index) : int(self.end_index + self.val_len),
            ]
        if option == 1:
            inp = torch.from_numpy(in_data).view(1, nd, Td)
            inp = inp.transpose(0, 1).float()
            if self.covariates is not None:
                rcovs = torch.from_numpy(rcovs).float()
            if self.Ycov is not None:
                ycovs = torch.from_numpy(ycovs).float()
            out = torch.from_numpy(out_data).view(1, nd, Td)
            if self.covariates is not None:
                inp = torch.cat((inp, rcovs), 1)
            if self.Ycov is not None:
                inp = torch.cat((inp, ycovs), 1)
            out = out.transpose(0, 1).float()
        else:
            inp = torch.from_numpy(in_data).float()
            out = torch.from_numpy(out_data).float()
        return inp, out, self.vindex, self.hindex
