"""
BSD 3-Clause License

Copyright (c) Soumith Chintala 2016,
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

* Redistributions of source code must retain the above copyright notice, this
  list of conditions and the following disclaimer.

* Redistributions in binary form must reproduce the above copyright notice,
  this list of conditions and the following disclaimer in the documentation
  and/or other materials provided with the distribution.

* Neither the name of the copyright holder nor the names of its
  contributors may be used to endorse or promote products derived from
  this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
"""

import math
import torch

from torch import nn
from torch.nn import functional as F


class DeepLabV3PlusDecoder(nn.Module):
    def __init__(
        self, cfg
    ):
        super().__init__()
        self.cfg = cfg

        if self.cfg.decoder_output_stride not in {8, 16}:
            raise ValueError("Output stride should be 8 or 16, got {}.".format(output_stride))

        self.out_channels = self.cfg.decoder_out_channels
        self.output_stride = self.cfg.decoder_output_stride

        self.aspp = nn.Sequential(
            ASPP(self.cfg.encoder_channels[-1], self.out_channels, self.cfg.atrous_rates, separable=True),
            SeparableConv3d(self.out_channels, self.out_channels, kernel_size=3, padding=1, bias=False),
            nn.BatchNorm3d(self.out_channels),
            nn.ReLU(),
        )

        size = (self.cfg.roi_x // math.prod(self.cfg.z_strides[:2]), self.cfg.roi_y // 4, self.cfg.roi_z // 4)
        self.up = nn.Upsample(size=size, mode="trilinear")

        highres_in_channels = self.cfg.encoder_channels[-4]
        highres_out_channels = 48  # proposed by authors of paper
        self.block1 = nn.Sequential(
            nn.Conv3d(highres_in_channels, highres_out_channels, kernel_size=1, bias=False),
            nn.BatchNorm3d(highres_out_channels),
            nn.ReLU(),
        )
        self.block2 = nn.Sequential(
            SeparableConv3d(
                highres_out_channels + self.out_channels,
                self.out_channels,
                kernel_size=3,
                padding=1,
                bias=False,
            ),
            nn.BatchNorm3d(self.out_channels),
            nn.ReLU(),
        )

    def forward(self, *features):
        aspp_features = self.aspp(features[-1])
        aspp_features = self.up(aspp_features)
        high_res_features = self.block1(features[-4])
        concat_features = torch.cat([aspp_features, high_res_features], dim=1)
        fused_features = self.block2(concat_features)
        return fused_features


class ASPPConv(nn.Sequential):
    def __init__(self, in_channels, out_channels, dilation):
        super().__init__(
            nn.Conv3d(
                in_channels,
                out_channels,
                kernel_size=3,
                padding=dilation,
                dilation=dilation,
                bias=False,
            ),
            nn.BatchNorm3d(out_channels),
            nn.ReLU(),
        )


class ASPPSeparableConv(nn.Sequential):
    def __init__(self, in_channels, out_channels, dilation):
        super().__init__(
            SeparableConv3d(
                in_channels,
                out_channels,
                kernel_size=3,
                padding=dilation,
                dilation=dilation,
                bias=False,
            ),
            nn.BatchNorm3d(out_channels),
            nn.ReLU(),
        )


class ASPPPooling(nn.Sequential):
    def __init__(self, in_channels, out_channels):
        super().__init__(
            nn.AdaptiveAvgPool3d(1),
            nn.Conv3d(in_channels, out_channels, kernel_size=1, bias=False),
            nn.BatchNorm3d(out_channels),
            nn.ReLU(),
        )

    def forward(self, x):
        size = x.shape[-3:]
        for mod in self:
            x = mod(x)
        return F.interpolate(x, size=size, mode="trilinear", align_corners=False)


class ASPP(nn.Module):
    def __init__(self, in_channels, out_channels, atrous_rates, separable=False):
        super(ASPP, self).__init__()
        modules = []
        modules.append(
            nn.Sequential(
                nn.Conv3d(in_channels, out_channels, 1, bias=False),
                nn.BatchNorm3d(out_channels),
                nn.ReLU(),
            )
        )

        rate1, rate2, rate3 = tuple(atrous_rates)
        ASPPConvModule = ASPPConv if not separable else ASPPSeparableConv

        modules.append(ASPPConvModule(in_channels, out_channels, rate1))
        modules.append(ASPPConvModule(in_channels, out_channels, rate2))
        modules.append(ASPPConvModule(in_channels, out_channels, rate3))
        modules.append(ASPPPooling(in_channels, out_channels))

        self.convs = nn.ModuleList(modules)

        self.project = nn.Sequential(
            nn.Conv3d(5 * out_channels, out_channels, kernel_size=1, bias=False),
            nn.BatchNorm3d(out_channels),
            nn.ReLU(),
            nn.Dropout(0.5),
        )

    def forward(self, x):
        res = []
        for conv in self.convs:
            res.append(conv(x))
        res = torch.cat(res, dim=1)
        return self.project(res)


class SeparableConv3d(nn.Sequential):
    def __init__(
        self,
        in_channels,
        out_channels,
        kernel_size,
        stride=1,
        padding=0,
        dilation=1,
        bias=True,
    ):
        depthwise_conv = nn.Conv3d(
            in_channels,
            in_channels,
            kernel_size,
            stride=stride,
            padding=padding,
            dilation=dilation,
            groups=in_channels,
            bias=False,
        )
        pointwise_conv = nn.Conv3d(
            in_channels,
            out_channels,
            kernel_size=1,
            bias=bias,
        )
        super().__init__(depthwise_conv, pointwise_conv)
