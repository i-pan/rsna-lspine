import torch
import torch.nn as nn
import torch.nn.functional as F

from monai.losses import DiceLoss, GeneralizedDiceLoss, DiceCELoss
from torchvision.ops import sigmoid_focal_loss


class BCEWithLogitsLoss(nn.BCEWithLogitsLoss):

    def forward(self, p, t):
        return F.binary_cross_entropy_with_logits(p.float(), t.float())


class MaskedBCEWithLogitsSeq(nn.BCEWithLogitsLoss):

    def forward(self, p, t, mask):
        loss = F.binary_cross_entropy_with_logits(p.float(), t.float(), reduction="none")[~mask]
        return loss.mean()


class BCESegCls(nn.Module):

    def forward_seg(self, p, t):
        return {"seg_loss": F.binary_cross_entropy_with_logits(p.float(), t.float())}

    def forward_cls(self, p, t):
        return {"cls_loss": F.binary_cross_entropy_with_logits(p.float(), t.float())}

    def forward(self, p_seg, t_seg, p_cls, t_cls):
        loss_dict = {}
        loss_dict.update(self.forward_seg(p_seg, t_seg))
        loss_dict.update(self.forward_cls(p_cls, t_cls))
        loss_dict["loss"] = loss_dict["seg_loss"] + loss_dict["cls_loss"]
        return loss_dict


class BCEPlusCoords(nn.BCEWithLogitsLoss):

    def forward(self, p, t):
        cls_loss = F.binary_cross_entropy_with_logits(p[:, :13].float(), t[:, :13].float())
        reg_loss = F.l1_loss(p[:, 13:].float(), t[:, 13:].float(), reduction="none")
        reg_loss = reg_loss.reshape(-1)
        ignore = t[:, 13:].reshape(-1)
        reg_loss = reg_loss[ignore != -1].mean()
        loss_dict = {"loss": cls_loss + reg_loss, "cls_loss": cls_loss, "reg_loss": reg_loss}
        return loss_dict


class MaskedBCEWithLogitsSeqPlusCoords(nn.BCEWithLogitsLoss):

    def forward(self, p, t, mask):
        cls_loss = F.binary_cross_entropy_with_logits(p[:, :, :13].float(), t[:, :, :13].float(), reduction="none")[~mask].mean()
        reg_loss = F.l1_loss(p[:, :, 13:].float(), t[:, :, 13:].float(), reduction="none")[~mask]
        reg_loss = reg_loss.reshape(-1)
        ignore = t[:, :, 13:][~mask].reshape(-1)
        reg_loss = reg_loss[ignore != -1].mean()
        loss_dict = {"loss": cls_loss + reg_loss, "cls_loss": cls_loss, "reg_loss": reg_loss}
        return loss_dict


class LevelAndDist(nn.BCEWithLogitsLoss):

    def forward(self, p, t):
        p1, p2, p3 = p[:, :11], p[:, [11, 12]], p[:, 13:]
        t1, t2, t3 = t[:, :11], t[:, [11, 12]], t[:, 13:]
        assert p1.size(1) == t1.size(1) == 11
        assert p2.size(1) == t2.size(1) == 2 
        assert p3.size(1) == t3.size(1) == 10 
        loss_dict = {}
        level_loss = F.cross_entropy(p1.float(), torch.argmax(t1, dim=1).long())
        subart_loss = F.binary_cross_entropy_with_logits(p2.float(), t2.float())
        dist_loss = F.l1_loss(p3.float(), t3.float())
        loss_dict["level_loss"] = level_loss
        loss_dict["subart_loss"] = subart_loss
        loss_dict["dist_loss"] = dist_loss
        loss_dict["loss"] = loss_dict["level_loss"] + loss_dict["subart_loss"] + loss_dict["dist_loss"]
        return loss_dict


class ClassWeightedBCE(nn.Module):

    def __init__(self):
        super().__init__()
        self.weights = torch.tensor([1, 2, 4]).float()

    def forward(self, p, t):
        assert p.shape[1] == t.shape[1] == 3
        loss = F.binary_cross_entropy_with_logits(p.float(), t.float(), reduction="none") * self.weights.to(p.device)
        return loss.mean()


class SampleWeightedLogLoss(nn.BCEWithLogitsLoss):

    def forward(self, p, t, w):
        return F.binary_cross_entropy_with_logits(p.float(), t.float(), weight=w.unsqueeze(1))


class SampleWeightedLogLossV2(nn.BCEWithLogitsLoss):

    def forward(self, p, t):
        w = torch.ones((len(p), 1))
        w[t[:, 1] == 1] = 2
        w[t[:, 2] == 1] = 4
        loss = (F.binary_cross_entropy_with_logits(p.float(), t.float(), reduction="none") * w.float().to(p.device)).mean()
        return loss


class SmoothSampleWeightedLogLoss(nn.BCEWithLogitsLoss):

    def forward(self, p, t):
        t_copy = t.clone()
        w = torch.ones((len(p), ))
        w[t[:, 1] == 1] = 2
        w[t[:, 2] == 1] = 4
        # Mild 
        t_copy[w == 1, 0] -= 0.025
        t_copy[w == 1, 1] += 0.025
        # Moderate
        t_copy[w == 2, 0] += 0.025
        t_copy[w == 2, 1] -= 0.05
        t_copy[w == 2, 2] += 0.025
        # Severe 
        t_copy[w == 4, 1] += 0.025
        t_copy[w == 4, 2] -= 0.025
        w = w.unsqueeze(1)
        loss = (F.binary_cross_entropy_with_logits(p.float(), t_copy.float(), reduction="none") * w.float().to(p.device)).mean()
        return loss


class SampleWeightedLogLossAuxRegression(nn.BCEWithLogitsLoss):

    def forward(self, p, t):
        w = torch.ones((len(p), 1))
        w[t[:, 1] == 1] = 2
        w[t[:, 2] == 1] = 4
        p_cls = p[:, :3]
        p_reg = p[:, 3]
        t_reg = torch.argmax(t, dim=1)
        assert p_reg.shape == t_reg.shape, f"p_reg.shape is {p_reg.shape} while t_reg.shape is {t_reg.shape}"
        loss = (F.binary_cross_entropy_with_logits(p_cls.float(), t.float(), reduction="none") * w.float().to(p.device)).mean()
        reg_loss = (F.l1_loss(p_reg.float(), t_reg.float(), reduction="none") + F.mse_loss(p_reg.float(), t_reg.float(), reduction="none")) * w.squeeze(1).float().to(p.device)
        reg_loss = reg_loss.mean()
        return loss + 0.1 * reg_loss


class SampledWeightedBCEWithValidSlice(nn.Module):

    def forward(self, p, t):
        p, pv = p[:, :3], p[:, 3]
        t, tv = t[:, :3], t[:, 3]
        w = torch.ones((len(p), 1))
        w[t[:, 1] == 1] = 2
        w[t[:, 2] == 1] = 4
        w = w.to(p.device)
        loss1 = (F.binary_cross_entropy_with_logits(p[tv > 0].float(), t[tv > 0].float(), reduction="none") * w[tv > 0].float()).mean()
        loss2 = F.binary_cross_entropy_with_logits(pv.float(), tv.float())
        return loss1 + loss2


class SampledWeightedBCEWithValidSliceWithMask(nn.Module):

    def forward(self, p, t, mask):
        p, t = p[~mask], t[~mask]
        p, pv = p[:, :3], p[:, 3]
        t, tv = t[:, :3], t[:, 3]
        w = torch.ones((len(p), 1))
        w[t[:, 1] == 1] = 2
        w[t[:, 2] == 1] = 4
        w = w.to(p.device)
        loss1 = (F.binary_cross_entropy_with_logits(p[tv > 0].float(), t[tv > 0].float(), reduction="none") * w[tv > 0].float()).mean()
        loss2 = F.binary_cross_entropy_with_logits(pv.float(), tv.float())
        return loss1 + loss2


class SampledWeightedBCEWithValidSliceWithMaskV2(nn.Module):

    def forward(self, p, t, mask):
        p, t = p[~mask], t[~mask]
        p, pv = p[:, :3], p[:, 3]
        t, tv = t[:, :3], t[:, 3]
        w = torch.ones((len(p), 1))
        t_copy = t.clone()
        t_copy[tv == 0] = 0.
        w[t[:, 1] == 1] = 2
        w[t[:, 2] == 1] = 4
        w = w.to(p.device)
        loss1 = (F.binary_cross_entropy_with_logits(p.float(), t.float(), reduction="none", pos_weight=torch.tensor(10)) * w.float()).mean()
        loss2 = F.binary_cross_entropy_with_logits(pv.float(), tv.float())
        return loss1 + loss2


class SampledWeightedCrossEntropyWithValidSlice(nn.Module):

    def forward(self, p, t):
        p, pv = p[:, :3], p[:, 3]
        t, tv = t[:, :3], t[:, 3]
        w = torch.ones((len(p), 1))
        w[t[:, 1] == 1] = 2
        w[t[:, 2] == 1] = 4
        w = w.to(p.device)
        t = torch.argmax(t, dim=1)
        loss1 = (F.cross_entropy(p[tv > 0].float(), t[tv > 0].long(), reduction="none") * w[tv > 0].float()).mean()
        loss2 = F.binary_cross_entropy_with_logits(pv.float(), tv.float())
        return loss1 + loss2


class SampledWeightedCrossEntropyWithValidSliceWithMask(nn.Module):

    def forward(self, p, t, mask):
        p, t = p[~mask], t[~mask]
        p, pv = p[:, :3], p[:, 3]
        t, tv = t[:, :3], t[:, 3]
        w = torch.ones((len(p), 1))
        w[t[:, 1] == 1] = 2
        w[t[:, 2] == 1] = 4
        w = w.to(p.device)
        t = torch.argmax(t, dim=1)
        loss1 = (F.cross_entropy(p[tv > 0].float(), t[tv > 0].long(), reduction="none") * w[tv > 0].float()).mean()
        loss2 = F.binary_cross_entropy_with_logits(pv.float(), tv.float())
        return loss1 + loss2


class SampledWeightedBCEWithValidSliceV2(nn.Module):

    def forward(self, p, t):
        p, pv = p[:, :3], p[:, 3]
        t, tv = t[:, :3], t[:, 3]
        w = torch.ones((len(p), 1))
        w[t[:, 1] == 1] = 2
        w[t[:, 2] == 1] = 4
        w = w.to(p.device)
        loss1 = (F.binary_cross_entropy_with_logits(p[pv >= 0].float(), t[pv >= 0].float(), reduction="none") * w[pv >= 0].float()).mean()
        loss2 = F.binary_cross_entropy_with_logits(pv.float(), tv.float())
        return loss1 + loss2


class SampleWeightedLogLossAll(nn.BCEWithLogitsLoss):

    def forward(self, p, t):
        w = torch.ones((len(p), 1))
        w[t[:, 1] == 1] = 2
        w[t[:, 2] == 1] = 4
        w[t[:, 4] == 1] = 4 # spinal 2x
        w[t[:, 5] == 1] = 8 # spinal 2x
        w[t[:, 7] == 1] = 2
        w[t[:, 8] == 1] = 4
        loss = (F.binary_cross_entropy_with_logits(p.float(), t.float(), reduction="none") * w.float().to(p.device)).mean()
        return loss


class SampleWeightedLogLossPseudo(nn.BCEWithLogitsLoss):

    def forward(self, p, t):
        t, t_pseudo = t[:, :3], t[:, 3:]
        w = torch.ones((len(p), 1))
        w[t[:, 1] == 1] = 2
        w[t[:, 2] == 1] = 4
        loss1 = (F.binary_cross_entropy_with_logits(p.float(), t.float(), reduction="none") * w.float().to(p.device)).mean()
        loss2 = (F.binary_cross_entropy_with_logits(p.float(), t_pseudo.float(), reduction="none") * w.float().to(p.device)).mean()
        return 0.5 * loss1 + 0.5 * loss2


class SampleWeightedLogLossSpinalSubarticular(nn.BCEWithLogitsLoss):

    def forward(self, p, t):
        # first 3 are right subarticular, next 3 left subarticular, last 3 spinal
        p = torch.cat([p[:, :3], p[:, 3:6], p[:, 6:], p[:, 6:]]) # repeat spinal to weight it 2x
        t = torch.cat([t[:, :3], t[:, 3:6], t[:, 6:], t[:, 6:]])
        w = torch.ones((len(p), 1))
        w[t[:, 1] == 1] = 2
        w[t[:, 2] == 1] = 4
        loss = (F.binary_cross_entropy_with_logits(p.float(), t.float(), reduction="none") * w.float().to(p.device)).mean()
        return loss


class SampleWeightedLogLossMixup(nn.BCEWithLogitsLoss):

    def forward(self, p, t, w=None):
        if not isinstance(w, torch.Tensor):
            w = torch.ones((len(p), 1))
            w[t[:, 1] == 1] = 2
            w[t[:, 2] == 1] = 4
        if w.ndim == 1:
            w = w.unsqueeze(1)
        loss = (F.binary_cross_entropy_with_logits(p.float(), t.float(), reduction="none") * w.float().to(p.device)).mean()
        return loss


class SampleWeightedCrossEntropy(nn.CrossEntropyLoss):

    def forward(self, p, t):
        w = torch.ones(len(p))
        w[t[:, 1] == 1] = 2
        w[t[:, 2] == 1] = 4
        t = torch.argmax(t, dim=1)
        loss = (F.cross_entropy(p.float(), t.long(), reduction="none") * w.float().to(p.device)).mean()
        return loss


class SampleWeightedCrossEntropyBilateral(nn.CrossEntropyLoss):

    def forward(self, p, t):
        p = torch.cat([p[:, :3], p[:, 3:]])
        t = torch.cat([t[:, :3], t[:, 3:]])
        w = torch.ones(len(p))
        w[t[:, 1] == 1] = 2
        w[t[:, 2] == 1] = 4
        t = torch.argmax(t, dim=1)
        loss = (F.cross_entropy(p.float(), t.long(), reduction="none") * w.float().to(p.device)).mean()
        return loss


class SampleWeightedCrossEntropyMixup(nn.Module):

    def forward(self, p, t, w=None):
        if not isinstance(w, torch.Tensor):
            w = torch.ones(len(p))
            w[t[:, 1] == 1] = 2
            w[t[:, 2] == 1] = 4
        # assumes one-hot encoded labels
        p = F.log_softmax(p.float(), -1)
        w = w.float().to(p.device)
        loss = -(p * t).sum(-1)
        return (loss * w).sum() / w.sum()


class SampleWeightedCrossEntropyBilat(nn.BCEWithLogitsLoss):

    def forward(self, p, t):
        p, t = torch.cat([p[:, :3], p[:, 3:]], dim=0), torch.cat([t[:, :3], t[:, 3:]], dim=0)
        w = torch.ones((len(p), ))
        w[t[:, 1] == 1] = 2.0
        w[t[:, 2] == 1] = 4.0 
        w = w.to(p.device)
        t = torch.argmax(t, dim=1)
        return (F.cross_entropy(p.float(), t.long(), reduction="none") * w.float()).mean()


def torch_log_loss(p, t):
    p = p.sigmoid()
    p = p / (p.sum(1).unsqueeze(1) + 1e-10)
    w = torch.ones((len(p), )).to(p.device)
    w[t[:, 1] == 1] = 2
    w[t[:, 2] == 1] = 4
    loss = -torch.xlogy(t.float(), p.float()).sum(1)
    loss = loss * w
    loss = loss / w.sum()
    return loss.sum()



def torch_log_loss_with_logits(logits, t, w=None):
    loss = (-t.float() * F.log_softmax(logits, dim=1)).sum(1)
    if isinstance(w, torch.Tensor):
        loss = loss * w
        return loss.sum() / w.sum()
    else:
        return loss.mean()


class WeightedLogLossWithLogits(nn.Module):

    @staticmethod
    def torch_log_loss_with_logits(logits, t, w=None):
        loss = (-t * F.log_softmax(logits, dim=1)).sum(1)
        if isinstance(w, torch.Tensor):
            loss = loss * w
            return loss.sum() / w.sum()
        else:
            return loss.mean()

    def forward(self, p, t):
        w = torch.ones((len(p), )).to(p.device)
        w[t[:, 1] == 1] = 2
        w[t[:, 2] == 1] = 4
        return self.torch_log_loss_with_logits(p.float(), t.float(), w=w)


class SampleWeightedWholeSpinalBCE(nn.Module):

    def forward(self, p, t):
        p = torch.cat([p[:, i:i+3] for i in range(0, 15, 3)], dim=0)
        t = torch.cat([t[:, i:i+3] for i in range(0, 15, 3)], dim=0)
        w = torch.ones((len(p), 1)).to(p.device)
        w[t[:, 1] == 1] = 2
        w[t[:, 2] == 1] = 4
        loss = (F.binary_cross_entropy_with_logits(p.float(), t.float(), reduction="none") * w.float().to(p.device)).mean()
        return loss


class WeightedLogLossWholeSpinalSeriesPlusCoords(WeightedLogLossWithLogits):

    def forward(self, p, t):
        p_grade, t_grade = p[:, :15], t[:, :15]
        p_coord, t_coord = p[:, 15:], t[:, 15:]
        p_grade = torch.cat([p_grade[:, :3], p_grade[:, 3:6], p_grade[:, 6:9], p_grade[:, 9:12], p_grade[:, 12:15]], dim=0)
        t_grade = torch.cat([t_grade[:, :3], t_grade[:, 3:6], t_grade[:, 6:9], t_grade[:, 9:12], t_grade[:, 12:15]], dim=0)
        w = torch.ones((len(p_grade), )).to(p.device)
        w[t_grade[:, 1] == 1] = 2
        w[t_grade[:, 2] == 1] = 4
        loss_dict = {"grade_loss": self.torch_log_loss_with_logits(p_grade.float(), t_grade.float(), w=w)}
        loss_dict["coord_loss"] = F.l1_loss(p_coord.sigmoid().float(), t_coord.float())
        loss_dict["loss"] = loss_dict["grade_loss"] + loss_dict["coord_loss"]
        return loss_dict


class SampleWeightedLogLossV3(nn.BCEWithLogitsLoss):

    def forward(self, p, t):
        return torch_log_loss(p, t)


class SampleWeightedLogLossBilat(nn.BCEWithLogitsLoss):

    def forward(self, p, t):
        p, t = torch.cat([p[:, :3], p[:, 3:]], dim=0), torch.cat([t[:, :3], t[:, 3:]], dim=0)
        w = torch.ones((len(p), ))
        w[t[:, 1] == 1] = 2.0
        w[t[:, 2] == 1] = 4.0 
        w = w.to(p.device)
        return F.binary_cross_entropy_with_logits(p.float(), t.float(), weight=w.unsqueeze(1))


class ComboLevelsAndMaskedCoordsLoss(nn.Module):

    def forward(self, p_coords, p_levels, t_coords, t_levels, included_levels):
        levels_loss = F.binary_cross_entropy_with_logits(p_levels.float(), t_levels.float())
        coords_loss = F.l1_loss(p_coords.float().sigmoid(), t_coords.float(), reduction="none")
        coords_mean_loss = []
        for b_idx, inc in enumerate(included_levels):
            tmp_indices = torch.where(inc)[0]
            tmp_indices = torch.cat([tmp_indices, tmp_indices + 15])
            # does throw error but uncommon so ignore for now
            # assert t_coords[b_idx, tmp_indices].max() <= 1 
            coords_mean_loss.append(coords_loss[b_idx, tmp_indices].mean())
        coords_loss = torch.stack(coords_mean_loss).mean(0)
        return {"loss": levels_loss + 10 * coords_loss, "levels_loss": levels_loss, "coords_loss": coords_loss}


class SampleWeightedLogLossBilatV2(nn.BCEWithLogitsLoss):

    def forward(self, p, t, w):
        # p.shape = t.shape = (N, 6); first 3 right, second 3 left
        # w.shape = (N, 2); 1st weight rt, 2nd weight left
        rt_loss = F.binary_cross_entropy_with_logits(p[:, :3].float(), t[:, :3].float(), weight=w[:, 0].unsqueeze(1))
        lt_loss = F.binary_cross_entropy_with_logits(p[:, 3:].float(), t[:, 3:].float(), weight=w[:, 1].unsqueeze(1))
        return (rt_loss + lt_loss) / 2


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


class LevelSubartDistSeq(nn.Module):

    def forward(self, p, t, mask):
        p1, p2 = p[:, :, :16], p[:, :, 16:]
        t1, t2 = t[:, :, :16], t[:, :, 16:]
        assert p1.size(2) == t1.size(2) == 16
        assert p2.size(2) == t2.size(2) == 10
        # BCE 
        cls_loss = F.binary_cross_entropy_with_logits(p1.float(), t1.float(), reduction="none")[~mask].mean()
        # L1
        dist_loss = F.smooth_l1_loss(p2.float(), t2.float(), reduction="none")[~mask].mean()
        return {"loss": cls_loss + dist_loss, "cls_loss": cls_loss, "dist_loss": dist_loss}


class LevelSpinalDistSeq(nn.Module):

    def forward(self, p, t, mask):
        p1, p2 = p[:, :, :5], p[:, :, 5:]
        t1, t2 = t[:, :, :5], t[:, :, 5:]
        assert p1.size(2) == t1.size(2) == 5
        assert p2.size(2) == t2.size(2) == 5
        # BCE 
        cls_loss = F.binary_cross_entropy_with_logits(p1.float(), t1.float(), reduction="none")[~mask].mean()
        # L1
        dist_loss = F.smooth_l1_loss(p2.float(), t2.float(), reduction="none")[~mask].mean()
        return {"loss": cls_loss + dist_loss, "cls_loss": cls_loss, "dist_loss": dist_loss}


class LevelForaminaDistSeq(nn.Module):

    def forward(self, p, t, mask):
        p1, p2 = p[:, :, :10], p[:, :, 10:]
        t1, t2 = t[:, :, :10], t[:, :, 10:]
        assert p1.size(2) == t1.size(2) == 10
        assert p2.size(2) == t2.size(2) == 10
        # BCE 
        cls_loss = F.binary_cross_entropy_with_logits(p1.float(), t1.float(), reduction="none")[~mask].mean()
        # L1
        dist_loss = F.smooth_l1_loss(p2.float(), t2.float(), reduction="none")[~mask].mean()
        return {"loss": cls_loss + dist_loss, "cls_loss": cls_loss, "dist_loss": dist_loss}


class LevelAgnosticForaminaDistSeq(nn.Module):

    def forward(self, p, t, mask):
        p1, p2 = p[:, :, :2], p[:, :, 2:]
        t1, t2 = t[:, :, :2], t[:, :, 2:]
        assert p1.size(2) == t1.size(2) ==2
        assert p2.size(2) == t2.size(2) ==2
        # BCE 
        cls_loss = F.binary_cross_entropy_with_logits(p1.float(), t1.float(), reduction="none")[~mask].mean()
        # L1
        dist_loss = F.smooth_l1_loss(p2.float(), t2.float(), reduction="none")[~mask].mean()
        return {"loss": cls_loss + dist_loss, "cls_loss": cls_loss, "dist_loss": dist_loss}


class GeneralizedDSC(nn.Module):

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.loss_func = DiceLoss(include_background=True, to_onehot_y=True, sigmoid=False, softmax=True)

    def forward(self, p, t):
        return {"loss": self.loss_func(p, t)}


class L1Loss(nn.L1Loss):

    def forward(self, p, t):
        assert p.shape == t.shape, f"p.shape {p.shape} does not equal t.shape {t.shape}"
        return F.l1_loss(p.sigmoid().float(), t.float())


class L1LossDistanceAndCoords(nn.Module):

    def forward(self, p, t):
        # p.shape will be 30 in order of: (rt_dist ... lt_dist ... rt_coord_x ... lt_coord_x ...)
        dist_loss = (F.l1_loss(p[:, :10].float(), t[:, :10].float()) + F.mse_loss(p[:, :10].float(), t[:, :10].float()) / 10) / 2.
        coord_loss = (F.l1_loss(p[:, 10:].sigmoid().float(), t[:, 10:].float()) + F.mse_loss(p[:, 10:].sigmoid().float(), t[:, 10:].float())) / 2.
        return {"loss": dist_loss + 100 * coord_loss, "dist_loss": dist_loss, "coord_loss": coord_loss}


class SimpleDiceBCE(nn.Module):

    def __init__(self, eps=1e-5, bce_weight=0.2):
        super().__init__()
        self.eps = eps
        self.bce_weight = bce_weight

    def forward(self, p, t):
        assert p.shape == t.shape
        p, t = p.float(), t.float()
        intersection = torch.sum(p.sigmoid() * t, dim=(2, 3))
        denominator = torch.sum(p.sigmoid(), dim=(2, 3)) + torch.sum(t, dim=(2, 3)) 
        dice = (2. * intersection + self.eps) / (denominator + self.eps)
        dice_loss = (1 - dice).mean()
        bce_loss = F.binary_cross_entropy_with_logits(p, t)
        return {"loss": dice_loss + self.bce_weight * bce_loss, "dice_loss": dice_loss, "bce_loss": bce_loss}


class SimpleDiceBCE_3d(nn.Module):

    def __init__(self, eps=1e-5, bce_weight=0.2):
        super().__init__()
        self.eps = eps
        self.bce_weight = bce_weight

    def forward(self, p, t):
        assert p.shape == t.shape
        p, t = p.float(), t.float()
        intersection = torch.sum(p.sigmoid() * t, dim=(2, 3, 4))
        denominator = torch.sum(p.sigmoid(), dim=(2, 3, 4)) + torch.sum(t, dim=(2, 3, 4)) 
        dice = (2. * intersection + self.eps) / (denominator + self.eps)
        dice_loss = (1 - dice).mean()
        bce_loss = F.binary_cross_entropy_with_logits(p, t)
        return {"loss": dice_loss + self.bce_weight * bce_loss, "dice_loss": dice_loss, "bce_loss": bce_loss}


class SimpleDice_3d(nn.Module):

    def __init__(self, eps=1e-5):
        super().__init__()
        self.eps = eps

    def forward(self, p, t):
        assert p.shape == t.shape
        p, t = p.float(), t.float()
        intersection = torch.sum(p.sigmoid() * t, dim=(2, 3, 4))
        denominator = torch.sum(p.sigmoid(), dim=(2, 3, 4)) + torch.sum(t, dim=(2, 3, 4)) 
        dice = (2. * intersection + self.eps) / (denominator + self.eps)
        dice_loss = (1 - dice).mean()
        return {"loss": dice_loss}


class SigmoidDiceBCELoss(nn.Module):

    def __init__(self, seg_pos_weight=None):
        super().__init__()
        self.eps = 1e-5
        self.seg_pos_weight = torch.tensor(seg_pos_weight) if not isinstance(seg_pos_weight, type(None)) else 1.0

    def forward(self, p, t):
        # p.shape = t.shape = (N, C, H, W)
        assert p.shape == t.shape
        p, t = p.float(), t.float()
        intersection = torch.sum(p.sigmoid() * t)
        denominator = torch.sum(p.sigmoid()) + torch.sum(t) 
        dice = (2. * intersection + self.eps) / (denominator + self.eps)
        dice_loss = 1 - dice
        bce_loss = F.binary_cross_entropy_with_logits(p, t, pos_weight=torch.tensor(self.seg_pos_weight))
        return {"seg_loss": 1.0 * dice_loss + 1.0 * bce_loss, "dice_loss": dice_loss, "bce_loss": bce_loss}


class DistCoordSingleModelLoss(nn.Module):

    @staticmethod
    def dist_loss(p, t):
        p, t = p.float(), t.float()
        l1_loss, l2_loss = F.l1_loss(p, t), F.mse_loss(p, t)
        # calculate L1 and L2 losses for tracking, but use smooth L1 loss for optimization
        return {"dist_loss_l1": l1_loss, "dist_loss_l2": l2_loss, "dist_loss": F.smooth_l1_loss(p, t)}

    @staticmethod
    def coord_loss(p, t):
        p_sigmoid, t = p.sigmoid().float(), t.float()
        # calculate L1 and L2 losses for tracking, but use average of MAE and MSE for optimization
        l1_loss, l2_loss = F.l1_loss(p_sigmoid, t), F.mse_loss(p_sigmoid, t)
        return {"coord_loss_l1": l1_loss, "coord_loss_l2": l2_loss, "coord_loss": (l1_loss + l2_loss) / 2.}

    def forward(self, p_dist, t_dist, p_coord, t_coord, mask):
        dist_loss_dict = self.dist_loss(p_dist[~mask], t_dist[~mask])
        coord_loss_dict = self.coord_loss(p_coord, t_coord)
        loss_dict = {"loss": dist_loss_dict["dist_loss"] + coord_loss_dict["coord_loss"] * 100}
        loss_dict.update(dist_loss_dict)
        loss_dict.update(coord_loss_dict)
        return loss_dict


class L1LossDistCoordSeg(nn.Module):

    def __init__(self, loss_weights=None, seg_pos_weight=None):
        super().__init__()
        self.loss_weights = torch.tensor(loss_weights) if not isinstance(loss_weights, type(None)) else torch.tensor([1., 1., 1.])
        self.seg_pos_weight = torch.tensor(seg_pos_weight) if not isinstance(seg_pos_weight, type(None)) else 1.0
        self.seg_loss = SigmoidDiceBCELoss()

    def forward(self, p_seg, p, t_seg, t):
        # p.shape will be 30 in order of: (rt_dist ... lt_dist ... rt_coord_x ... lt_coord_x ...)
        dist_loss = (F.l1_loss(p[:, :10].float(), t[:, :10].float()) + F.mse_loss(p[:, :10].float(), t[:, :10].float()) / 10) / 2.
        coord_loss = (F.l1_loss(p[:, 10:].sigmoid().float(), t[:, 10:].float()) + F.mse_loss(p[:, 10:].sigmoid().float(), t[:, 10:].float())) / 2.
        seg_loss_dict = self.seg_loss(p_seg, t_seg)
        loss_dict = {
            "loss": self.loss_weights[0] * dist_loss + self.loss_weights[1] * coord_loss + self.loss_weights[2] * seg_loss_dict["seg_loss"], 
            "dist_loss": dist_loss, 
            "coord_loss": coord_loss, 
        }
        loss_dict.update(seg_loss_dict)
        return loss_dict


class MaskedSmoothL1Loss(nn.Module):

    def forward(self, p, t, mask):
        loss_dict = {
            "loss": F.smooth_l1_loss(p[~mask], t[~mask]),
            "l1_loss": F.l1_loss(p[~mask], t[~mask]),
            "l2_loss": F.mse_loss(p[~mask], t[~mask])
        }
        return loss_dict


class MaskedSmoothL1LossSubarticular(nn.Module):

    def forward(self, p, t, mask):
        mask = mask.unsqueeze(2).repeat(1, 1, t.shape[2])
        assert mask.shape == t.shape, f"mask.shape = {mask.shape}, t.shape = {t.shape}"
        mask[t == -88888] = True
        loss_dict = {
            "loss": F.smooth_l1_loss(p[~mask], t[~mask]),
            "l1_loss": F.l1_loss(p[~mask], t[~mask]),
            "l2_loss": F.mse_loss(p[~mask], t[~mask])
        }
        return loss_dict


class MaskedSmoothL1LossBCESubarticular(nn.Module):

    def dist_loss(self, p, t, mask):
        mask = mask.clone().unsqueeze(2).repeat(1, 1, t.shape[2])
        assert mask.shape == t.shape, f"mask.shape = {mask.shape}, t.shape = {t.shape}"
        mask[t == -88888] = True
        loss_dict = {
            "dist_loss": F.smooth_l1_loss(p[~mask], t[~mask]),
            "dist_loss_l1": F.l1_loss(p[~mask], t[~mask]),
            "dist_loss_l2": F.mse_loss(p[~mask], t[~mask])
        }
        return loss_dict

    def bce_loss(self, p, t, mask):
        mask = mask.clone().unsqueeze(2).repeat(1, 1, t.shape[2])
        assert mask.shape == t.shape, f"mask.shape = {mask.shape}, t.shape = {t.shape}"
        return {"bce_loss": F.binary_cross_entropy_with_logits(p[~mask].float(), t[~mask].float())}

    def forward(self, p, t, mask):
        loss_dict = {}
        loss_dict.update(self.dist_loss(p[:, :, :10], t[:, :, :10], mask))
        loss_dict.update(self.bce_loss(p[:, :, 10:], t[:, :, 10:], mask))
        loss_dict.update({"loss": loss_dict["dist_loss"]})# + loss_dict["bce_loss"]})
        return loss_dict


class L1LossDistCoordSegV2(nn.Module):

    def __init__(self, loss_weights=None, seg_pos_weight=None):
        super().__init__()
        self.loss_weights = torch.tensor(loss_weights) if not isinstance(loss_weights, type(None)) else torch.tensor([1., 1., 1.])
        self.seg_loss = SigmoidDiceBCELoss(seg_pos_weight=seg_pos_weight)

    def forward(self, p_seg, p, t_seg, t):
        assert p.shape[1] == 30
        # p.shape will be 30 in order of: (rt_dist ... lt_dist ... rt_coord_x ... lt_coord_x ...)
        dist_loss = (F.l1_loss(p[:, :10].float(), t[:, :10].float()) + F.mse_loss(p[:, :10].float(), t[:, :10].float()) / 10) / 2.
        coord_loss = (F.l1_loss(p[:, 10:].sigmoid().float(), t[:, 10:].float()) + F.mse_loss(p[:, 10:].sigmoid().float(), t[:, 10:].float())) / 2.
        seg_loss_dict = self.seg_loss(p_seg, t_seg)
        loss_dict = {
            "loss": self.loss_weights[0] * dist_loss + self.loss_weights[1] * coord_loss + self.loss_weights[2] * seg_loss_dict["seg_loss"], 
            "dist_loss": dist_loss, 
            "coord_loss": coord_loss, 
        }
        loss_dict.update(seg_loss_dict)
        return loss_dict


class L1LossDistCoordSegV3(nn.Module):
    # Only calculate coordinate loss for slices and adjacent slices with foramen
    # Coordinate labels will be -1 for those without foramen
    def __init__(self, loss_weights=None, seg_pos_weight=None):
        super().__init__()
        self.loss_weights = torch.tensor(loss_weights) if not isinstance(loss_weights, type(None)) else torch.tensor([1., 1., 1.])
        self.seg_loss = SigmoidDiceBCELoss(seg_pos_weight=seg_pos_weight)

    def dist_loss(self, p, t):
        assert p.shape[1] == t.shape[1] == 10
        p, t = p.float(), t.float()
        l1_loss, l2_loss = F.l1_loss(p, t), F.mse_loss(p, t)
        # calculate L1 and L2 losses for tracking, but use smooth L1 loss for optimization
        return {"dist_loss_l1": l1_loss, "dist_loss_l2": l2_loss, "dist_loss": F.smooth_l1_loss(p, t)}

    @staticmethod
    def coord_loss(p, t):
        p_sigmoid, t = p.sigmoid().float(), t.float()
        # calculate L1 and L2 losses for tracking, but use average of MAE and MSE for optimization
        l1_loss, l2_loss = F.l1_loss(p_sigmoid, t), F.mse_loss(p_sigmoid, t)
        return {"coord_loss_l1": l1_loss, "coord_loss_l2": l2_loss, "coord_loss": (l1_loss + l2_loss) / 2.}

    def forward(self, p_seg, p, t_seg, t):
        assert p.shape[1] == t.shape[1] == 30
        # p.shape will be 30 in order of: (rt_dist ... lt_dist ... rt_coord_x ... lt_coord_x ...)
        dist_loss_dict = self.dist_loss(p[:, :10], t[:, :10])
        coord_mask = t[:, 10:] == -1
        if coord_mask.sum().item() == coord_mask.shape[0] * coord_mask.shape[1]:
            # in the rare event that there are no valid coord losses in the batch
            coord_loss = torch.tensor(0.).to(p.device)
            coord_loss_dict = {k: coord_loss for k in ["coord_loss_l1", "coord_loss_l2", "coord_loss"]}
        else:
            coord_loss_dict = self.coord_loss(p[:, 10:][~coord_mask], t[:, 10:][~coord_mask])
        seg_loss_dict = self.seg_loss(p_seg, t_seg)
        loss_dict = {
            "loss": self.loss_weights[0] * dist_loss_dict["dist_loss"] + \
                    self.loss_weights[1] * coord_loss_dict["coord_loss"] + \
                    self.loss_weights[2] * seg_loss_dict["seg_loss"]
        }
        loss_dict.update(dist_loss_dict)
        loss_dict.update(coord_loss_dict)
        loss_dict.update(seg_loss_dict)
        return loss_dict


class L1LossDistCoordSegV4(nn.Module):
    # Only calculate coordinate loss for slices and adjacent slices with foramen
    # Coordinate labels will be -1 for those without foramen
    def __init__(self, loss_weights=None, seg_pos_weight=None):
        super().__init__()
        self.loss_weights = torch.tensor(loss_weights) if not isinstance(loss_weights, type(None)) else torch.tensor([1., 1., 1.])
        self.seg_loss = SigmoidDiceBCELoss(seg_pos_weight=seg_pos_weight)

    def dist_loss(self, p, t):
        assert p.shape[1] == t.shape[1] == 10
        p, t = p.float(), t.float()
        l1_loss, l2_loss = F.l1_loss(p, t), F.mse_loss(p, t)
        # calculate L1 and L2 losses for tracking, but use smooth L1 loss for optimization
        return {"dist_loss_l1": l1_loss, "dist_loss_l2": l2_loss, "dist_loss": F.smooth_l1_loss(p, t)}

    @staticmethod
    def coord_loss(p, t):
        p_sigmoid, t = p.sigmoid().float(), t.float()
        # calculate L1 and L2 losses for tracking, but use average of MAE and MSE for optimization
        l1_loss, l2_loss = F.l1_loss(p_sigmoid, t), F.mse_loss(p_sigmoid, t)
        return {"coord_loss_l1": l1_loss, "coord_loss_l2": l2_loss, "coord_loss": (l1_loss + l2_loss) / 2.}

    def forward(self, p_seg, p, t_seg, t):
        assert p.shape[1] == t.shape[1] == 20
        # p.shape will be 30 in order of: (rt_dist ... lt_dist ... coord_x ... coord_x ...)
        dist_loss_dict = self.dist_loss(p[:, :10], t[:, :10])
        coord_mask = t[:, 10:] == -1
        if coord_mask.sum().item() == coord_mask.shape[0] * coord_mask.shape[1]:
            # in the rare event that there are no valid coord losses in the batch
            coord_loss = torch.tensor(0.).to(p.device)
            coord_loss_dict = {k: coord_loss for k in ["coord_loss_l1", "coord_loss_l2", "coord_loss"]}
        else:
            coord_loss_dict = self.coord_loss(p[:, 10:][~coord_mask], t[:, 10:][~coord_mask])
        seg_loss_dict = self.seg_loss(p_seg, t_seg)
        loss_dict = {
            "loss": self.loss_weights[0] * dist_loss_dict["dist_loss"] + \
                    self.loss_weights[1] * coord_loss_dict["coord_loss"] + \
                    self.loss_weights[2] * seg_loss_dict["seg_loss"]
        }
        loss_dict.update(dist_loss_dict)
        loss_dict.update(coord_loss_dict)
        loss_dict.update(seg_loss_dict)
        return loss_dict


class L1LossDistOnly(nn.Module):

    def forward(self, p, t):
        assert p.shape[1] == t.shape[1] == 10
        p, t = p.float(), t.float()
        l1_loss, l2_loss = F.l1_loss(p, t), F.mse_loss(p, t)
        # calculate L1 and L2 losses for tracking, but use smooth L1 loss for optimization
        return {"dist_loss_l1": l1_loss, "dist_loss_l2": l2_loss, "loss": F.smooth_l1_loss(p, t)}


class L1DistAndBCE(nn.Module):

    def dist_loss(self, p, t):
        assert p.shape[1] == t.shape[1] == 10
        p, t = p.float(), t.float()
        l1_loss, l2_loss = F.l1_loss(p, t), F.mse_loss(p, t)
        # calculate L1 and L2 losses for tracking, but use smooth L1 loss for optimization
        return {"dist_loss_l1": l1_loss, "dist_loss_l2": l2_loss, "dist_loss": F.smooth_l1_loss(p, t)}

    def bce(self, p, t):
        assert p.shape[1] == t.shape[1] == 10
        p, t = p.float(), t.float()
        # calculate L1 and L2 losses for tracking, but use smooth L1 loss for optimization
        return {"bce_loss": F.binary_cross_entropy_with_logits(p.float(), t.float())}

    def forward(self, p, t):
        dist_loss_dict = self.dist_loss(p[:, :10], t[:, :10])
        bce_loss_dict = self.bce(p[:, 10:], t[:, 10:])
        loss_dict = {"loss": dist_loss_dict["dist_loss"] + bce_loss_dict["bce_loss"]}
        loss_dict.update(dist_loss_dict)
        loss_dict.update(bce_loss_dict)
        return loss_dict


class L1DistCoordBCE(nn.Module):

    def dist_loss(self, p, t):
        assert p.shape[1] == t.shape[1] == 10
        p, t = p.float(), t.float()
        l1_loss, l2_loss = F.l1_loss(p, t), F.mse_loss(p, t)
        # calculate L1 and L2 losses for tracking, but use smooth L1 loss for optimization
        return {"dist_loss_l1": l1_loss, "dist_loss_l2": l2_loss, "dist_loss": F.smooth_l1_loss(p, t)}

    def bce(self, p, t):
        assert p.shape[1] == t.shape[1] == 10
        p, t = p.float(), t.float()
        # calculate L1 and L2 losses for tracking, but use smooth L1 loss for optimization
        return {"bce_loss": F.binary_cross_entropy_with_logits(p.float(), t.float())}

    @staticmethod
    def coord_loss(p, t):
        assert p.shape[1] == t.shape[1] == 10
        coord_mask = t == -1
        if coord_mask.sum().item() == coord_mask.shape[0] * coord_mask.shape[1]:
            # in the rare event that there are no valid coord losses in the batch
            l1_loss = torch.tensor(0.).to(p.device)
            l2_loss = torch.tensor(0.).to(p.device)
        else:
            p_sigmoid, t = p.sigmoid().float(), t.float()
            # calculate L1 and L2 losses for tracking, but use average of MAE and MSE for optimization
            l1_loss, l2_loss = F.l1_loss(p_sigmoid[~coord_mask], t[~coord_mask]), F.mse_loss(p_sigmoid[~coord_mask], t[~coord_mask])
        return {"coord_loss_l1": l1_loss, "coord_loss_l2": l2_loss, "coord_loss": (l1_loss + l2_loss) / 2.}

    def forward(self, p, t):
        dist_loss_dict = self.dist_loss(p[:, :10], t[:, :10])
        bce_loss_dict = self.bce(p[:, 10:20], t[:, 10:20])
        coord_loss_dict = self.coord_loss(p[:, 20:], t[:, 20:])
        loss_dict = {"loss": dist_loss_dict["dist_loss"] + bce_loss_dict["bce_loss"] + 100 * coord_loss_dict["coord_loss"]}
        loss_dict.update(dist_loss_dict)
        loss_dict.update(bce_loss_dict)
        loss_dict.update(coord_loss_dict)
        return loss_dict


class L1DistCoordBCESpinal(nn.Module):

    def dist_loss(self, p, t):
        assert p.shape[1] == t.shape[1] == 5
        p, t = p.float(), t.float()
        l1_loss, l2_loss = F.l1_loss(p, t), F.mse_loss(p, t)
        # calculate L1 and L2 losses for tracking, but use smooth L1 loss for optimization
        return {"dist_loss_l1": l1_loss, "dist_loss_l2": l2_loss, "dist_loss": F.smooth_l1_loss(p, t)}

    def bce(self, p, t):
        assert p.shape[1] == t.shape[1] == 5
        p, t = p.float(), t.float()
        # calculate L1 and L2 losses for tracking, but use smooth L1 loss for optimization
        return {"bce_loss": F.binary_cross_entropy_with_logits(p.float(), t.float())}

    @staticmethod
    def coord_loss(p, t):
        assert p.shape[1] == t.shape[1] == 10
        coord_mask = t == -1
        if coord_mask.sum().item() == coord_mask.shape[0] * coord_mask.shape[1]:
            # in the rare event that there are no valid coord losses in the batch
            l1_loss = torch.tensor(0.).to(p.device)
            l2_loss = torch.tensor(0.).to(p.device)
        else:
            p_sigmoid, t = p.sigmoid().float(), t.float()
            # calculate L1 and L2 losses for tracking, but use average of MAE and MSE for optimization
            l1_loss, l2_loss = F.l1_loss(p_sigmoid[~coord_mask], t[~coord_mask]), F.mse_loss(p_sigmoid[~coord_mask], t[~coord_mask])
        return {"coord_loss_l1": l1_loss, "coord_loss_l2": l2_loss, "coord_loss": (l1_loss + l2_loss) / 2.}

    def forward(self, p, t):
        dist_loss_dict = self.dist_loss(p[:, :5], t[:, :5])
        bce_loss_dict = self.bce(p[:, 5:10], t[:, 5:10])
        coord_loss_dict = self.coord_loss(p[:, 10:], t[:, 10:])
        loss_dict = {"loss": dist_loss_dict["dist_loss"] + bce_loss_dict["bce_loss"] + 100 * coord_loss_dict["coord_loss"]}
        loss_dict.update(dist_loss_dict)
        loss_dict.update(bce_loss_dict)
        loss_dict.update(coord_loss_dict)
        return loss_dict


class L1DistCoordBCESubarticular(nn.Module):

    def dist_loss(self, p, t):
        assert p.shape[1] == t.shape[1] == 10
        mask = t == -88888
        if mask.sum().item() == mask.shape[0] * mask.shape[1]:
            # in the rare event that there are no valid coord losses in the batch
            l1_loss = torch.tensor(0.).to(p.device)
            l2_loss = torch.tensor(0.).to(p.device)
            loss = torch.tensor(0.).to(p.device)
        else:
            p, t = p.float(), t.float()
            l1_loss, l2_loss = F.l1_loss(p[~mask], t[~mask]), F.mse_loss(p[~mask], t[~mask])
            loss = F.smooth_l1_loss(p[~mask], t[~mask])
        # calculate L1 and L2 losses for tracking, but use smooth L1 loss for optimization
        return {"dist_loss_l1": l1_loss, "dist_loss_l2": l2_loss, "dist_loss": loss}

    def bce(self, p, t):
        assert p.shape[1] == t.shape[1] == 10
        p, t = p.float(), t.float()
        # calculate L1 and L2 losses for tracking, but use smooth L1 loss for optimization
        return {"bce_loss": F.binary_cross_entropy_with_logits(p.float(), t.float())}

    @staticmethod
    def coord_loss(p, t):
        assert p.shape[1] == t.shape[1] == 4
        mask = t == -88888
        if mask.sum().item() == mask.shape[0] * mask.shape[1]:
            # in the rare event that there are no valid coord losses in the batch
            l1_loss = torch.tensor(0.).to(p.device)
            l2_loss = torch.tensor(0.).to(p.device)
        else:
            p_sigmoid, t = p.sigmoid().float(), t.float()
            # calculate L1 and L2 losses for tracking, but use average of MAE and MSE for optimization
            l1_loss, l2_loss = F.l1_loss(p_sigmoid[~mask], t[~mask]), F.mse_loss(p_sigmoid[~mask], t[~mask])
        return {"coord_loss_l1": l1_loss, "coord_loss_l2": l2_loss, "coord_loss": (l1_loss + l2_loss) / 2.}

    def forward(self, p, t):
        dist_loss_dict = self.dist_loss(p[:, :10], t[:, :10])
        bce_loss_dict = self.bce(p[:, 10:20], t[:, 10:20])
        coord_loss_dict = self.coord_loss(p[:, 20:], t[:, 20:])
        loss_dict = {"loss": dist_loss_dict["dist_loss"] + bce_loss_dict["bce_loss"] + 100 * coord_loss_dict["coord_loss"]}
        loss_dict.update(dist_loss_dict)
        loss_dict.update(bce_loss_dict)
        loss_dict.update(coord_loss_dict)
        return loss_dict


class SigmoidDiceBCELoss(nn.Module):

    def __init__(self, seg_pos_weight=None):
        super().__init__()
        self.eps = 1e-5
        self.seg_pos_weight = torch.tensor(seg_pos_weight) if not isinstance(seg_pos_weight, type(None)) else 1.0

    def forward(self, p, t):
        # p.shape = t.shape = (N, C, H, W)
        assert p.shape == t.shape
        p, t = p.float(), t.float()
        intersection = torch.sum(p.sigmoid() * t)
        denominator = torch.sum(p.sigmoid()) + torch.sum(t) 
        dice = (2. * intersection + self.eps) / (denominator + self.eps)
        dice_loss = 1 - dice
        bce_loss = F.binary_cross_entropy_with_logits(p, t, pos_weight=torch.tensor(self.seg_pos_weight))
        return {"seg_loss": 1.0 * dice_loss + 1.0 * bce_loss, "dice_loss": dice_loss, "bce_loss": bce_loss}


class BCEL1LossDistCoordSeg(nn.Module):
    # Only calculate coordinate loss for slices and adjacent slices with foramen
    # Coordinate labels will be -1 for those without foramen
    def __init__(self, loss_weights=None, seg_pos_weight=None):
        super().__init__()
        self.loss_weights = torch.tensor(loss_weights) if not isinstance(loss_weights, type(None)) else torch.tensor([1., 1., 1.])
        self.seg_loss = SigmoidDiceBCELoss(seg_pos_weight=seg_pos_weight)
    
    def dist_loss(self, p, t):
        assert p.shape[1] == t.shape[1] == 10
        return {"dist_loss": F.binary_cross_entropy_with_logits(p, t)}

    @staticmethod
    def coord_loss(p, t):
        p_sigmoid, t = p.sigmoid().float(), t.float()
        # calculate L1 and L2 losses for tracking, but use average of MAE and MSE for optimization
        l1_loss, l2_loss = F.l1_loss(p_sigmoid, t), F.mse_loss(p_sigmoid, t)
        return {"coord_loss_l1": l1_loss, "coord_loss_l2": l2_loss, "coord_loss": (l1_loss + l2_loss) / 2.}

    def forward(self, p_seg, p, t_seg, t):
        assert p.shape[1] == t.shape[1] == 20
        # p.shape will be 30 in order of: (rt_dist ... lt_dist ... coord_x ... coord_x ...)
        dist_loss_dict = self.dist_loss(p[:, :10], t[:, :10])
        coord_mask = t[:, 10:] == -1
        if coord_mask.sum().item() == coord_mask.shape[0] * coord_mask.shape[1]:
            # in the rare event that there are no valid coord losses in the batch
            coord_loss = torch.tensor(0.).to(p.device)
            coord_loss_dict = {k: coord_loss for k in ["coord_loss_l1", "coord_loss_l2", "coord_loss"]}
        else:
            coord_loss_dict = self.coord_loss(p[:, 10:][~coord_mask], t[:, 10:][~coord_mask])
        seg_loss_dict = self.seg_loss(p_seg, t_seg)
        loss_dict = {
            "loss": self.loss_weights[0] * dist_loss_dict["dist_loss"] + \
                    self.loss_weights[1] * coord_loss_dict["coord_loss"] + \
                    self.loss_weights[2] * seg_loss_dict["seg_loss"]
        }
        loss_dict.update(dist_loss_dict)
        loss_dict.update(coord_loss_dict)
        loss_dict.update(seg_loss_dict)
        return loss_dict


class L1LossDistCoordSegSpinalV3(nn.Module):

    def __init__(self, loss_weights=None, seg_pos_weight=None):
        super().__init__()
        self.loss_weights = torch.tensor(loss_weights) if not isinstance(loss_weights, type(None)) else torch.tensor([1., 1., 1.])
        self.seg_loss = SigmoidDiceBCELoss(seg_pos_weight=seg_pos_weight)

    def dist_loss(self, p, t):
        assert p.shape[1] == t.shape[1] == 5
        p, t = p.float(), t.float()
        l1_loss, l2_loss = F.l1_loss(p, t), F.mse_loss(p, t)
        # calculate L1 and L2 losses for tracking, but use smooth L1 loss for optimization
        return {"dist_loss_l1": l1_loss, "dist_loss_l2": l2_loss, "dist_loss": F.smooth_l1_loss(p, t)}

    @staticmethod
    def coord_loss(p, t):
        p_sigmoid, t = p.sigmoid().float(), t.float()
        # calculate L1 and L2 losses for tracking, but use average of MAE and MSE for optimization
        l1_loss, l2_loss = F.l1_loss(p_sigmoid, t), F.mse_loss(p_sigmoid, t)
        return {"coord_loss_l1": l1_loss, "coord_loss_l2": l2_loss, "coord_loss": (l1_loss + l2_loss) / 2.}

    def forward(self, p_seg, p, t_seg, t):
        assert p.shape[1] == t.shape[1] == 15
        # p.shape will be 15 in order of: (dist ... coord_x ... coord_y ...)
        dist_loss_dict = self.dist_loss(p[:, :5], t[:, :5])
        coord_mask = t[:, 5:] == -1
        if coord_mask.sum().item() == coord_mask.shape[0] * coord_mask.shape[1]:
            # in the rare event that there are no valid coord losses in the batch
            coord_loss = torch.tensor(0.).to(p.device)
            coord_loss_dict = {k: coord_loss for k in ["coord_loss_l1", "coord_loss_l2", "coord_loss"]}
        else:
            coord_loss_dict = self.coord_loss(p[:, 5:][~coord_mask], t[:, 5:][~coord_mask])
        seg_loss_dict = self.seg_loss(p_seg, t_seg)
        loss_dict = {
            "loss": self.loss_weights[0] * dist_loss_dict["dist_loss"] + \
                    self.loss_weights[1] * coord_loss_dict["coord_loss"] + \
                    self.loss_weights[2] * seg_loss_dict["seg_loss"]
        }
        loss_dict.update(dist_loss_dict)
        loss_dict.update(coord_loss_dict)
        loss_dict.update(seg_loss_dict)
        return loss_dict


class L1LossDistCoordSegSubarticularV3(nn.Module):
    # Only calculate coordinate loss for slices and adjacent slices with foramen
    # Coordinate labels will be -1 for those without foramen
    def __init__(self, loss_weights=None, seg_pos_weight=None):
        super().__init__()
        self.loss_weights = torch.tensor(loss_weights) if not isinstance(loss_weights, type(None)) else torch.tensor([1., 1., 1.])
        self.seg_loss = SigmoidDiceBCELoss(seg_pos_weight=seg_pos_weight)

    def dist_loss(self, p, t):
        p, t = p.float(), t.float()
        l1_loss, l2_loss = F.l1_loss(p, t), F.mse_loss(p, t)
        # calculate L1 and L2 losses for tracking, but use smooth L1 loss for optimization
        return {"dist_loss_l1": l1_loss, "dist_loss_l2": l2_loss, "dist_loss": F.smooth_l1_loss(p, t)}

    @staticmethod
    def coord_loss(p, t):
        p_sigmoid, t = p.sigmoid().float(), t.float()
        # calculate L1 and L2 losses for tracking, but use average of MAE and MSE for optimization
        l1_loss, l2_loss = F.l1_loss(p_sigmoid, t), F.mse_loss(p_sigmoid, t)
        return {"coord_loss_l1": l1_loss, "coord_loss_l2": l2_loss, "coord_loss": (l1_loss + l2_loss) / 2.}

    def forward(self, p_seg, p, t_seg, t):
        assert p.shape[1] == t.shape[1] == 30
        # p.shape will be 30 in order of: (rt_dist ... lt_dist ... rt_coord_x ... lt_coord_x ...)
        dist_mask = t[:, :10] == -88888
        dist_loss_dict = self.dist_loss(p[:, :10][~dist_mask], t[:, :10][~dist_mask])
        coord_mask = t[:, 10:] == -1
        if coord_mask.sum().item() == coord_mask.shape[0] * coord_mask.shape[1]:
            # in the rare event that there are no valid coord losses in the batch
            coord_loss = torch.tensor(0.).to(p.device)
            coord_loss_dict = {k: coord_loss for k in ["coord_loss_l1", "coord_loss_l2", "coord_loss"]}
        else:
            coord_loss_dict = self.coord_loss(p[:, 10:][~coord_mask], t[:, 10:][~coord_mask])
        seg_loss_dict = self.seg_loss(p_seg, t_seg)
        loss_dict = {
            "loss": self.loss_weights[0] * dist_loss_dict["dist_loss"] + \
                    self.loss_weights[1] * coord_loss_dict["coord_loss"] + \
                    self.loss_weights[2] * seg_loss_dict["seg_loss"]
        }
        loss_dict.update(dist_loss_dict)
        loss_dict.update(coord_loss_dict)
        loss_dict.update(seg_loss_dict)
        return loss_dict


class L1LossDistCoordSegSubarticularV4(nn.Module):
    # Only calculate coordinate loss for slices and adjacent slices with foramen
    # Coordinate labels will be -1 for those without foramen
    def __init__(self, loss_weights=None, seg_pos_weight=None):
        super().__init__()
        self.loss_weights = torch.tensor(loss_weights) if not isinstance(loss_weights, type(None)) else torch.tensor([1., 1., 1.])
        self.seg_loss = SigmoidDiceBCELoss(seg_pos_weight=seg_pos_weight)

    def dist_loss(self, p, t):
        p, t = p.float(), t.float()
        l1_loss, l2_loss = F.l1_loss(p, t), F.mse_loss(p, t)
        # calculate L1 and L2 losses for tracking, but use smooth L1 loss for optimization
        return {"dist_loss_l1": l1_loss, "dist_loss_l2": l2_loss, "dist_loss": F.smooth_l1_loss(p, t)}

    @staticmethod
    def coord_loss(p, t):
        p_sigmoid, t = p.sigmoid().float(), t.float()
        # calculate L1 and L2 losses for tracking, but use average of MAE and MSE for optimization
        l1_loss, l2_loss = F.l1_loss(p_sigmoid, t), F.mse_loss(p_sigmoid, t)
        return {"coord_loss_l1": l1_loss, "coord_loss_l2": l2_loss, "coord_loss": (l1_loss + l2_loss) / 2.}

    def forward(self, p_seg, p, t_seg, t):
        assert p.shape[1] == t.shape[1] == 14
        # p.shape will be 30 in order of: (rt_dist ... lt_dist ... rt_coord_x ... lt_coord_x ...)
        dist_mask = t[:, :10] == -88888
        dist_loss_dict = self.dist_loss(p[:, :10][~dist_mask], t[:, :10][~dist_mask])
        coord_mask = t[:, 10:] == -1
        if coord_mask.sum().item() == coord_mask.shape[0] * coord_mask.shape[1]:
            # in the rare event that there are no valid coord losses in the batch
            coord_loss = torch.tensor(0.).to(p.device)
            coord_loss_dict = {k: coord_loss for k in ["coord_loss_l1", "coord_loss_l2", "coord_loss"]}
        else:
            coord_loss_dict = self.coord_loss(p[:, 10:][~coord_mask], t[:, 10:][~coord_mask])
        seg_loss_dict = self.seg_loss(p_seg, t_seg)
        loss_dict = {
            "loss": self.loss_weights[0] * dist_loss_dict["dist_loss"] + \
                    self.loss_weights[1] * coord_loss_dict["coord_loss"] + \
                    self.loss_weights[2] * seg_loss_dict["seg_loss"]
        }
        loss_dict.update(dist_loss_dict)
        loss_dict.update(coord_loss_dict)
        loss_dict.update(seg_loss_dict)
        return loss_dict


class L1LossDistCoordSegSpinalV2(nn.Module):

    def __init__(self, loss_weights=None, seg_pos_weight=None):
        super().__init__()
        self.loss_weights = torch.tensor(loss_weights) if not isinstance(loss_weights, type(None)) else torch.tensor([1., 1., 1.])
        self.seg_loss = SigmoidDiceBCELoss(seg_pos_weight=seg_pos_weight)

    def forward(self, p_seg, p, t_seg, t):
        assert p.shape[1] == 15
        # p.shape will be 15 in order of: (dist, coord_x, coord_y)
        dist_loss = (F.l1_loss(p[:, :5].float(), t[:, :5].float()) + F.mse_loss(p[:, :5].float(), t[:, :5].float()) / 10) / 2.
        coord_loss = (F.l1_loss(p[:, 5:].sigmoid().float(), t[:, 5:].float()) + F.mse_loss(p[:, 5:].sigmoid().float(), t[:, 5:].float())) / 2.
        seg_loss_dict = self.seg_loss(p_seg, t_seg)
        loss_dict = {
            "loss": self.loss_weights[0] * dist_loss + self.loss_weights[1] * coord_loss + self.loss_weights[2] * seg_loss_dict["seg_loss"], 
            "dist_loss": dist_loss, 
            "coord_loss": coord_loss, 
        }
        loss_dict.update(seg_loss_dict)
        return loss_dict


class L1LossDistanceAndCoordsSeq(nn.Module):

    def forward(self, p_dist, p_coord, t_dist, t_coord, mask):
        coord_loss_l1 = F.l1_loss(p_coord.sigmoid().float(), t_coord.float())
        coord_loss_l2 = F.mse_loss(p_coord.sigmoid().float(), t_coord.float())
        # mask is 1 if padded, 0 if not padded, so need to negate mask for loss calculation
        dist_loss_l1 = F.l1_loss(p_dist[~mask].float(), t_dist[~mask].float())
        dist_loss_l2 = F.mse_loss(p_dist[~mask].float(), t_dist[~mask].float())
        coord_loss = (coord_loss_l1 + coord_loss_l2) / 2.
        dist_loss = (dist_loss_l1 + dist_loss_l2 / 10.) / 2.
        return {"loss": dist_loss + 100 * coord_loss, "dist_loss": dist_loss, "coord_loss": coord_loss}


class L1TanhLoss(nn.L1Loss):

    def forward(self, p, t):
        assert p.shape == t.shape, f"p.shape {p.shape} does not equal t.shape {t.shape}"
        return F.l1_loss(p.tanh().float(), t.float())


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


class BCELoss_SegCls(nn.Module):

    def __init__(self, pos_weight=None):
        super().__init__()
        self.wts = torch.tensor([0.5, 0.5])
        self.pos_weight = torch.tensor(pos_weight)

    def forward(self, p_seg, p_cls, t_seg, t_cls):
        segloss = F.binary_cross_entropy_with_logits(p_seg.float(), t_seg.float(), pos_weight=self.pos_weight)
        clsloss = F.binary_cross_entropy_with_logits(p_cls.float(), t_cls.float())
        loss = self.wts[0] * segloss + self.wts[1] * clsloss
        return {"loss": loss, "seg_loss": segloss, "cls_loss": clsloss}


class FocalBCELoss_SegCls(nn.Module):

    def __init__(self):
        super().__init__()
        self.wts = torch.tensor([0.5, 0.5])

    def forward(self, p_seg, p_cls, t_seg, t_cls):
        segloss = sigmoid_focal_loss(p_seg.float(), t_seg.float(), reduction="mean")
        clsloss = F.binary_cross_entropy_with_logits(p_cls.float(), t_cls.float())
        loss = self.wts[0] * segloss + self.wts[1] * clsloss
        return loss
