import cv2
import numpy as np
import os
import pandas as pd
import torch

from torch.utils.data import Dataset as TorchDataset, default_collate


train_collate_fn = default_collate
val_collate_fn = default_collate


class Dataset(TorchDataset):

    def __init__(self, cfg, mode):
        self.cfg = cfg 
        self.mode = mode
        df = pd.read_csv(self.cfg.annotations_file)
        if self.mode == "train":
            df = df[df.fold != self.cfg.fold]
            self.transforms = self.cfg.train_transforms
        elif self.mode == "val":
            df = df.drop_duplicates().reset_index(drop=True)
            df = df[df.fold == self.cfg.fold]
            if "with_augs" in self.cfg.annotations_file:
                # should ignore the generated aug images and only 
                # do validation on the original images
                df = df.loc[df.filepath.apply(lambda x: x.endswith("_000.png"))].reset_index(drop=True)
                df = df.iloc[1::3]
            if "ignore_during_val" in df.columns:
                df = df[df.ignore_during_val == 0]
            self.transforms = self.cfg.val_transforms

        self.df = df.reset_index(drop=True)
        self.inputs = df[self.cfg.inputs].tolist()
        self.labels = df[self.cfg.targets].values 
        if "sampling_weight" in df.columns:
            self.sampling_weights = df.sampling_weight.values
            
        self.collate_fn = train_collate_fn if mode == "train" else val_collate_fn

    def __len__(self):
        return len(self.inputs) 

    def get(self, i):
        try:
            x = cv2.imread(os.path.join(self.cfg.data_dir, self.inputs[i]), self.cfg.cv2_load_flag)
            if isinstance(self.cfg.select_image_channel, int):
                x = x[..., self.cfg.select_image_channel]
                x = np.expand_dims(x, axis=-1)
            y = self.labels[i]
            return x, y
        except Exception as e:
            print(e)
            return None

    def __getitem__(self, i):
        data = self.get(i)
        while not isinstance(data, tuple):
            i = np.random.randint(len(self))
            data = self.get(i)

        x, y = data

        if self.cfg.channel_reverse and self.mode == "train" and bool(np.random.binomial(1, 0.5)):
            x = np.ascontiguousarray(x[:, :, ::-1])

        # if self.cfg.flip_lr and bool(np.random.binomial(1, 0.5)) and self.mode == "train":
        #     # Mainly for training subarticular full slice model 
        #     # If flip image then need to also flip the labels
        #     x = np.fliplr(x)
        #     y = y[[3, 4, 5, 0, 1, 2]]

        x = self.transforms(image=x)["image"]

        if x.ndim == 2:
            x = np.expand_dims(x, axis=-1)

        x = x.transpose(2, 0, 1) # channels-last -> channels-first
        x = torch.tensor(x).float()
        if y.ndim == 0:
            y = torch.tensor(y).float().unsqueeze(-1)

        return {"x": x, "y": y, "index": i}
