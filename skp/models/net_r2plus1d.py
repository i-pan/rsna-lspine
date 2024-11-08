import math
import re
import torch
import torch.nn as nn
import torch.nn.functional as F

from timm import create_model

from .pool_3d import SelectAdaptivePool3d


class GeM(nn.Module):

    def __init__(self, p=3, eps=1e-6):
        super().__init__()
        self.p = nn.Parameter(torch.ones(1)*p)
        self.eps = eps
        self.flatten = nn.Flatten(1)

    def forward(self, x):
        x = F.avg_pool3d(x.clamp(min=self.eps).pow(self.p), (x.size(-3), x.size(-2), x.size(-1))).pow(1./self.p)
        return self.flatten(x)


class Net(nn.Module):

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg

        # Set up R(2+1)D backbone
        if not self.cfg.pretrained:
            from pytorchvideo.models import hub
            self.backbone = getattr(hub, "r2plus1d_r50")(pretrained=False)
        else:
            self.backbone = torch.hub.load("facebookresearch/pytorchvideo", model="r2plus1d_r50", pretrained=True)

        # default model will downsample time/z-dimension by 2 after blocks 3 and 4 (so 4x)
        # then avg pool at the end
        # will modify so that there is no downsampling of that dimension and just avg pool at end
        self.backbone.blocks[3].res_blocks[0].branch1_conv.stride = (1, 2, 2)
        self.backbone.blocks[3].res_blocks[0].branch2.conv_b.conv_t.stride = (1, 1, 1)
        self.backbone.blocks[4].res_blocks[0].branch1_conv.stride = (1, 2, 2)
        self.backbone.blocks[4].res_blocks[0].branch2.conv_b.conv_t.stride = (1, 1, 1)
        self.backbone.blocks[5] = nn.Identity()

        self.change_num_input_channels()

        self.dim_feats = self.backbone(torch.randn((2, self.cfg.num_input_channels, 32, 128, 128))).size(1)
        self.dim_feats = self.dim_feats * (2 if self.cfg.pool == "catavgmax" else 1)
        self.pooling = self.get_pool_layer()

        if isinstance(self.cfg.reduce_feat_dim, int):
            # Use 1D grouped convolution to reduce # of parameters
            groups = math.gcd(self.dim_feats, self.cfg.reduce_feat_dim)
            self.feat_reduce = nn.Conv1d(self.dim_feats, self.cfg.reduce_feat_dim, groups=groups, kernel_size=1,
                                         stride=1, bias=False)
            self.dim_feats = self.cfg.reduce_feat_dim

        self.dropout = nn.Dropout(p=self.cfg.dropout) 
        self.linear = nn.Linear(self.dim_feats, self.cfg.num_classes)

        if self.cfg.load_pretrained_backbone:
            print(f"Loading pretrained backbone from {self.cfg.load_pretrained_backbone} ...")
            weights = torch.load(self.cfg.load_pretrained_backbone, map_location=lambda storage, loc: storage)['state_dict']
            weights = {re.sub(r'^model.', '', k) : v for k,v in weights.items()}
            # Get feature_reduction, if present
            feat_reduce_weight = {re.sub(r"^feat_reduce.", "", k): v
                                  for k, v in weights.items() if "feat_reduce" in k}
            # Get backbone only
            weights = {re.sub(r'^backbone.', '', k) : v for k,v in weights.items() if 'backbone' in k}
            self.backbone.load_state_dict(weights)
            if len(feat_reduce_weight) > 0:
                self.feat_reduce.load_state_dict(feat_reduce_weight)

        if self.cfg.freeze_backbone:
            self.freeze_backbone()

    def normalize(self, x):
        if self.cfg.normalization == "-1_1":
            mini, maxi = self.cfg.normalization_params["min"], self.cfg.normalization_params["max"]
            x = x - mini
            x = x / (maxi - mini) 
            x = x - 0.5 
            x = x * 2.0
        elif self.cfg.normalization == "0_1":
            mini, maxi = self.cfg.normalization_params["min"], self.cfg.normalization_params["max"]
            x = x - mini
            x = x / (maxi - mini) 
        elif self.cfg.normalization == "mean_sd":
            mean, sd = self.cfg.normalization_params["mean"], self.cfg.normalization_params["sd"]
            x = (x - mean) / sd
        elif self.cfg.normalization == "per_channel_mean_sd":
            mean, sd = self.cfg.normalization_params["mean"], self.cfg.normalization_params["sd"]
            assert len(mean) == len(sd) == x.size(1)
            mean, sd = torch.tensor(mean).unsqueeze(0), torch.tensor(sd).unsqueeze(0)
            for i in range(x.ndim - 2):
                mean, sd = mean.unsqueeze(-1), sd.unsqueeze(-1)
            x = (x - mean) / sd
        return x 

    def forward(self, batch, return_loss=False, return_features=False):
        x = batch["x"]
        y = batch["y"] if "y" in batch else None

        if return_loss:
            assert isinstance(y, torch.Tensor)

        x = self.normalize(x) 
        
        features = self.pooling(self.backbone(x)) 

        if hasattr(self, "feat_reduce"):
            features = self.feat_reduce(features.unsqueeze(-1)).squeeze(-1) 

        if self.cfg.multisample_dropout:
            logits = torch.mean(torch.stack([self.classifier(self.dropout(features)) for _ in range(5)]), dim=0)
        else:
            logits = self.linear(self.dropout(features))

        if self.cfg.activation_function == "sigmoid":
            logits = torch.sigmoid(logits)

        out = {"logits": logits}
        if return_features:
            out["features"] = features 
        if return_loss: 
            loss = self.criterion(logits, y, w=batch["wts"]) if "wts" in batch else self.criterion(logits, y)
            out["loss"] = loss
            
        return out

    def get_pool_layer(self):
        assert self.cfg.pool in ["avg", "max", "fast", "avgmax", "catavgmax", "gem"], f"{layer_name} is not a valid pooling layer"
        if self.cfg.pool == "gem":
            return GeM(**self.cfg.pool_params) if hasattr(self.cfg, "pool_params") else GeM()
        else:
            return SelectAdaptivePool3d(pool_type=self.cfg.pool, flatten=True)

    def freeze_backbone(self):
        for param in self.backbone.parameters(): 
            param.requires_grad = False
        if hasattr(self, "feat_reduce"):
            for param in self.feat_reduce.parameters():
                param.requires_grad = False

    def change_num_input_channels(self):
        # Assumes original number of input channels in model is 3
        for i, m in enumerate(self.backbone.modules()):
          if isinstance(m, nn.Conv3d) and m.in_channels == 3:
            m.in_channels = self.cfg.num_input_channels
            # First, sum across channels
            W = m.weight.sum(1, keepdim=True)
            # Then, divide by number of channels
            W = W / self.cfg.num_input_channels
            # Then, repeat by number of channels
            size = [1] * W.ndim
            size[1] = self.cfg.num_input_channels
            W = W.repeat(size)
            m.weight = nn.Parameter(W)
            break

    def set_criterion(self, loss):
        self.criterion = loss
