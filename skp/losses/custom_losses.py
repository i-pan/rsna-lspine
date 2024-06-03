import torch
import torch.nn as nn
import torch.nn.functional as F

from monai.losses import DiceLoss


class BCEWithLogitsLoss(nn.BCEWithLogitsLoss):

    def forward(self, p, t):
        return F.binary_cross_entropy_with_logits(p.float(), t.float())


class SampleWeightedLogLoss(nn.BCEWithLogitsLoss):

    def forward(self, p, t, w):
        return F.binary_cross_entropy_with_logits(p.float(), t.float(), weight=w.unsqueeze(1))


class MaskedBCEWithLogitsLoss(nn.BCEWithLogitsLoss):

    def forward(self, p, t, mask):
        b, n, c = p.size()
        assert mask.size(0) == b and mask.size(1) == n and mask.ndim == 2
        loss = F.binary_cross_entropy_with_logits(p.float(), t.float(), reduction="none").view(b*n, -1)
        mask = mask.view(b*n)
        assert mask.size(0) == loss.size(0)
        loss = loss[~mask] # negate mask because True indicates padding token
        return loss.mean()

class CrossEntropyLoss(nn.CrossEntropyLoss):

    def forward(self, p, t):
        if t.ndim == 2:
            t = t[:, 0]
        return F.cross_entropy(p.float(), t.long())


class L1Loss(nn.L1Loss):

    def forward(self, p, t):
        assert p.shape == t.shape, f"p.shape {p.shape} does not equal t.shape {t.shape}"
        return F.l1_loss(p.sigmoid().float(), t.float())


class L1LossNoSigmoid(nn.L1Loss):

    def forward(self, p, t):
        assert p.shape == t.shape, f"p.shape {p.shape} does not equal t.shape {t.shape}"
        return F.l1_loss(p.float(), t.float())


class WeightedLogLoss(nn.Module):

    def __init__(self):
        super().__init__()
        self.wts = torch.tensor([1.0, 2.0, 4.0])

    def forward(self, p, t):
        # p.shape == t.shape == (N, C)
        loss = F.binary_cross_entropy_with_logits(p.float(), t.float(), reduction="none")
        loss = self.wts.to(p.device) * loss
        return loss.mean()


class WeightedLogLoss30(nn.Module):

    def __init__(self):
        super().__init__()
        self.wts = torch.tensor([1.0, 2.0, 4.0] * 10)

    def forward(self, p, t):
        # p.shape == t.shape == (N, C)
        loss = F.binary_cross_entropy_with_logits(p.float(), t.float(), reduction="none")
        loss = self.wts.to(p.device) * loss
        return loss.mean()


class WeightedLogLoss6(nn.Module):

    def __init__(self):
        super().__init__()
        self.wts = torch.tensor([1.0, 2.0, 4.0] * 2)

    def forward(self, p, t):
        # p.shape == t.shape == (N, C)
        loss = F.binary_cross_entropy_with_logits(p.float(), t.float(), reduction="none")
        loss = self.wts.to(p.device) * loss
        return loss.mean()


class WeightedLogLossWithArea(nn.Module):

    def __init__(self):
        super().__init__()
        self.wts = torch.tensor([1.0, 2.0, 4.0, 0.33, 0.33, 0.33])

    def forward(self, p, t):
        # p.shape == t.shape == (N, C)
        loss = F.binary_cross_entropy_with_logits(p.float(), t.float(), reduction="none")
        loss = self.wts.to(p.device) * loss
        return loss.mean()
