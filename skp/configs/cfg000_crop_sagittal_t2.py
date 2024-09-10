import albumentations as A
import cv2

from .base import Config


cfg = Config()
cfg.neptune_mode = "async"

cfg.save_dir = "experiments/"
cfg.project = "gradientecho/rsna-lspine"

cfg.task = "classification"

cfg.model = "net_2d"
cfg.backbone = "mobilenetv3_small_100"
cfg.pretrained = True
cfg.num_input_channels = 1
cfg.pool = "gem"
cfg.pool_params = dict(p=3)
cfg.dropout = 0.1
cfg.num_classes = 2
cfg.normalization = "-1_1"
cfg.normalization_params = {"min": 0, "max": 255}

cfg.fold = 0 
cfg.dataset = "simple_2d"
cfg.data_dir = "/home/ian/projects/rsna-lspine/data/train_pngs_3ch/"
cfg.annotations_file = "/home/ian/projects/rsna-lspine/data/train_crop_sagittal_t2_kfold.csv"
cfg.inputs = "filepath"
cfg.targets = ["x_min_rel", "x_max_rel"]
cfg.cv2_load_flag = cv2.IMREAD_COLOR
cfg.num_workers = 16
cfg.pin_memory = True
cfg.select_image_channel = 1
# cfg.sampler = "IterationBasedSampler"
# cfg.num_iterations_per_epoch = 1000
cfg.backbone_img_size = False
cfg.convert_to_3d = False

cfg.loss = "L1Loss"
cfg.loss_params = {}

cfg.batch_size = 16
cfg.num_epochs = 5
cfg.optimizer = "AdamW"
cfg.optimizer_params = {"lr": 3e-4}

cfg.scheduler = "CosineAnnealingLR"
cfg.scheduler_params = {"eta_min": 0}
cfg.scheduler_interval = "step"

cfg.val_batch_size = cfg.batch_size * 2
cfg.metrics = ["Dummy"]
cfg.val_metric = "loss"
cfg.val_track = "min"

cfg.image_height = 512
cfg.image_width = 512

cfg.train_transforms = A.Compose([
    A.Resize(cfg.image_height, cfg.image_width, p=1),
    A.VerticalFlip(p=0.5),
    A.SomeOf([
        # A.ShiftScaleRotate(shift_limit=0.00, scale_limit=0.2, rotate_limit=0, border_mode=cv2.BORDER_CONSTANT, p=1),
        # A.ShiftScaleRotate(shift_limit=0.00, scale_limit=0.0, rotate_limit=30, border_mode=cv2.BORDER_CONSTANT, p=1),
        # A.GridDistortion(p=1),
        A.GaussianBlur(p=1),
        A.GaussNoise(p=1),
        A.RandomGamma(p=1),
        A.RandomBrightnessContrast(contrast_limit=0.2, brightness_limit=0.0, p=1),
        A.RandomBrightnessContrast(contrast_limit=0.0, brightness_limit=0.2, p=1),
    ], n=3, p=0.95, replace=False)
])

cfg.val_transforms = A.Compose([
    A.Resize(cfg.image_height, cfg.image_width, p=1)
])
