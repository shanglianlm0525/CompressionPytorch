# !/usr/bin/env python
# -- coding: utf-8 --
# @Time : 2023/3/2 16:30
# @Author : liumin
# @File : quant_module_bak.py

import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np


class Quantizer(nn.Module):
    def __init__(self, scheme='mse', bit=8, b_bit=None,  is_quantize=False,
                 is_symmetric = False, per_channel=False,
                 is_calibration=False, calibration_data=None):
        super(Quantizer, self).__init__()
        self.is_quantize = is_quantize
        self.scheme = scheme
        self.bit = bit
        self.b_bit = b_bit

        # weight and activation quantizer config
        # Weight Quantization : per-channel asymmetric quantization
        # Activation Quantization : per-layer asymmetric quantization
        self.is_quantize = is_quantize
        self.is_symmetric = is_symmetric
        self.per_channel = per_channel
        self.is_calibration = is_calibration
        self.calibration_data = calibration_data

        # quantizer parameters
        self.init = False
        self.min = torch.Tensor([float('inf')])[0]
        self.max = torch.Tensor([float('-inf')])[0]
        self.scale = None
        self.offset = None
        self.min_mse = float('inf')

    def set_quantize(self, flag):
        self.is_quantize = flag

    def estimate_range(self, flag):
        self.is_calibration = flag

    def set_symmetric(self, flag):
        self.is_symmetric = flag

    def set_per_channel(self, flag):
        self.per_channel = flag

    def init_params(self, x_f):
        '''
        https://heartbeat.fritz.ai/quantization-arithmetic-421e66afd842

        There exist two modes
        1) Symmetric:
            Symmetric quantization uses absolute max value as its min/max meaning symmetric with respect to zero
        2) Asymmetric
            Asymmetric Quantization uses actual min/max, meaning it is asymmetric with respect to zero

        Scale factor uses full range [-2**n / 2, 2**n - 1]
        '''
        device = x_f.device
        if self.is_symmetric:
            if self.per_channel:
                x_f_tmp = x_f.view(x_f.shape[0], -1)
                x_min, x_max = -torch.max(torch.abs(x_f_tmp), 1)[0], torch.max(torch.abs(x_f_tmp), 1)[0]
            else:
                x_min, x_max = -torch.max(torch.abs(x_f)), torch.max(torch.abs(x_f))
        else:
            if self.per_channel:
                x_f_tmp = x_f.view(x_f.shape[0], -1)
                x_min, x_max = torch.min(x_f_tmp, 1)[0], torch.max(x_f_tmp, 1)[0]
            else:
                x_min, x_max = torch.min(x_f), torch.max(x_f)

        if self.per_channel:
            self.min = torch.min(x_min, self.min.to(device))
            self.max = torch.max(x_max, self.max.to(device))
            max_range = self.max - self.min
        else:
            self.min = torch.min(x_min, self.min.to(device))
            self.max = torch.max(x_max, self.max.to(device))
            max_range = self.max - self.min

        if self.quant_mode == 'mse':
            if not self.init or self.act_q:
                self.init = True
                for i in range(80):
                    scale = (max_range - (0.01 * i)) / float(2 ** self.bit - 1)
                    offset = torch.round(-self.min / scale)
                    x_fp_q = self.quant_dequant(x_f, scale, offset)
                    curr_mse = torch.pow(x_fp_q - x_f, 2).mean().cpu().numpy()
                    if self.min_mse > curr_mse:
                        self.min_mse = curr_mse
                        self.scale = scale
                        self.offset = offset

        elif self.quant_mode == 'minmax':
            if self.per_channel:
                self.scale = max_range / float(2 ** self.bit - 1)
                if not self.is_symmetric:
                    self.offset = torch.round(-x_min / self.scale)
            else:
                self.scale = max_range / float(2 ** self.bit - 1)
                if not self.is_symmetric:
                    self.offset = torch.round(-x_min / self.scale)

        elif self.quant_mode == 'kl_divergence':
            assert self.calibration_data is not None, 'self.calibration_data is not None'
            # 1 count the absmax
            print(111)

            # 2 initialize histogram

            # 3 build histogram

            # 4 using kld to find the best threshold value
        else:
            raise NotImplementedError(self.quant_mode + ' is not Implemented! ')
        self.init = True

    def compute_kl_divergence(self, dist_a, dist_b):
        dist_a = np.array(dist_a)
        dist_b = np.array(dist_b)
        nonzero_inds = dist_a != 0
        return np.sum(dist_a[nonzero_inds] *
                      np.log(dist_a[nonzero_inds] / (dist_b[nonzero_inds] + 1e-12) + 1e-12))

    def quant_dequant(self, x_f, scale, offset):
        '''
        Quantizing
        Formula is derived from below:
        https://medium.com/ai-innovation/quantization-on-pytorch-59dea10851e1
        '''
        if self.per_channel:
            if x_f.ndim == 4:
                scale = scale.view(x_f.shape[0], 1, 1, 1)
                if not self.is_symmetric:
                    offset = offset.view(x_f.shape[0], 1, 1, 1)
            elif x_f.ndim == 2:
                scale = scale.view(x_f.shape[0], 1)
                if not self.is_symmetric:
                    offset = offset.view(x_f.shape[0], 1)
            x_int = torch.round(x_f / scale)
            if not self.is_symmetric:
                x_int += offset

            if self.is_symmetric:
                l_bound, u_bound = -2 ** (self.bit - 1), 2 ** (self.bit - 1) - 1
            else:
                l_bound, u_bound = 0, 2 ** (self.bit) - 1
            x_q = torch.clamp(x_int, min=l_bound, max=u_bound)
            '''
               De-quantizing
            '''
            if not self.is_symmetric:
                x_q -= offset
            x_float_q = x_q * scale
        else:
            x_int = torch.round(x_f / scale)
            if not self.is_symmetric:
                x_int += offset

            if self.is_symmetric:
                l_bound, u_bound = -2 ** (self.bit - 1), 2 ** (self.bit - 1) - 1
            else:
                l_bound, u_bound = 0, 2 ** (self.bit) - 1
            x_q = torch.clamp(x_int, min=l_bound, max=u_bound)

            '''
            De-quantizing
            '''
            if not self.is_symmetric:
                x_q -= offset
            x_float_q = x_q * scale
        return x_float_q

    def forward(self, x_f):
        if self.is_quantize and self.init:
            self.init_params(x_f)
        return self.quant_dequant(x_f, self.scale, self.offset) if self.is_quantize else x_f


class QConv2d(nn.Module):
    '''
    Fuses only the following sequence of modules:
    conv, bn
    conv, bn, relu
    conv, relu
    bn, relu
    '''
    def __init__(self, module, w_scheme='mse', w_bit = 8, b_bit=8, a_scheme='mse', a_bit=8, calibration_data=None):
        super(QConv2d, self).__init__()
        # weights
        self.conv = module
        self.weight_quantizer = Quantizer(w_scheme, w_bit, b_bit,
                                          is_symmetric = False, per_channel=True)
        self.kwarg = {'stride': self.conv.stride, 'padding': self.conv.padding,
                      'dilation': self.conv.dilation, 'groups': self.conv.groups}

        self.act = None
        # activations
        self.act_quantizer = Quantizer(a_scheme, a_bit, None,
                                       is_symmetric = True, per_channel=False, calibration_data=calibration_data)
        self.pre_act = False

    def fuse_bn(self):
        '''
                https://towardsdatascience.com/speed-up-inference-with-batch-normalization-folding-8a45a83a89d8

                W_fold = gamma * W / sqrt(var + eps)
                b_fold = (gamma * ( bias - mu ) / sqrt(var + eps)) + beta
                '''
        if hasattr(self.conv, 'gamma'):
            gamma = getattr(self.conv, 'gamma')
            beta = getattr(self.conv, 'beta')
            mu = getattr(self.conv, 'mu')
            var = getattr(self.conv, 'var')
            eps = getattr(self.conv, 'eps')

            denom = gamma.div(torch.sqrt(var + eps))

            if getattr(self.conv, 'bias') == None:
                self.conv.bias = torch.nn.Parameter(var.new_zeros(var.shape))
            b_fold = denom * (self.conv.bias.data - mu) + beta
            self.conv.bias.data.copy_(b_fold)

            denom = denom.unsqueeze(-1).unsqueeze(-1).unsqueeze(-1)
            self.conv.weight.data.mul_(denom)

    def get_params(self):
        w = self.conv.weight.detach()
        if self.conv.bias != None:
            b = self.conv.bias.detach()
        else:
            b = None
        w = self.weight_quantizer(w)
        return w, b

    def turn_preactivation_on(self):
        self.pre_act = True


    def forward(self, x):
        w, b = self.get_params()
        out = F.conv2d(input=x, weight=w, bias=b, **self.kwarg)
        if self.act and not self.pre_act:
            out = self.act(out)
        out = self.act_quantizer(out)
        return out


class QLinear(nn.Module):
    '''
    Fuses only the following sequence of modules:
    linear, relu
    bn, relu
    '''
    def __init__(self, module, w_scheme='mse', w_bit = 8, b_bit=8, a_scheme='mse', a_bit=8, calibration_data=None):
        super(QLinear, self).__init__()
        self.fc = module
        # self.fc, self.norm, self.act = module
        self.weight_quantizer = Quantizer(w_scheme, w_bit, None,
                                          is_symmetric = False, per_channel=True)
        self.act = None
        # activations
        self.act_quantizer = Quantizer(a_scheme, a_bit, None,
                                       is_symmetric = True, per_channel=False, calibration_data=calibration_data)

    def get_params(self):
        w = self.fc.weight.detach()
        if self.fc.bias != None:
            b = self.fc.bias.detach()
        else:
            b = None
        w = self.weight_quantizer(w)
        return w, b

    def forward(self, x):
        w, b = self.get_params()
        out = F.linear(x, w, b)
        if self.act:
            out = self.act(out)
        out = self.act_quantizer(out)
        return out


class QIdentity(nn.Module):
    def __init__(self):
        super(QIdentity, self).__init__()

    def forward(self, x):
        return x


class QConcat(nn.Module):
    def __init__(self, dim):
        super(QConcat, self).__init__()
        self.dim = dim

    def forward(self, x, y):
        return torch.cat((x,y),self.dim)


class QAdd(nn.Module):
    def __init__(self):
        super(QAdd, self).__init__()

    def forward(self, x, y):
        return x + y