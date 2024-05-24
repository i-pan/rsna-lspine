import cv2
import glob
import numpy as np
import os
import pandas as pd

from tqdm import tqdm


df = pd.read_csv("../../data/predicted_sagittal_t1_foramina_coords_oof.csv")
# 7 studies have 2 sagittal T1 sequences
# After manual review, it just looks like duplicates
meta_df = pd.read_csv("../../data/dicom_metadata.csv")

num_slices_per_series = {}
for series_id, series_df in meta_df.groupby("series_id"):
    num_slices_per_series[series_id] = len(series_df)

df = df.merge(meta_df[["study_id", "series_id", "rows", "cols"]].drop_duplicates(), on=["study_id", "series_id"])
df["num_slices"] = df.series_id.map(num_slices_per_series)

targets = [
    "lt_foramen_l1_l2_x", "lt_foramen_l2_l3_x", "lt_foramen_l3_l4_x", "lt_foramen_l4_l5_x", "lt_foramen_l5_s1_x",
    "rt_foramen_l1_l2_x", "rt_foramen_l2_l3_x", "rt_foramen_l3_l4_x", "rt_foramen_l4_l5_x", "rt_foramen_l5_s1_x",
    "lt_foramen_l1_l2_y", "lt_foramen_l2_l3_y", "lt_foramen_l3_l4_y", "lt_foramen_l4_l5_y", "lt_foramen_l5_s1_y",
    "rt_foramen_l1_l2_y", "rt_foramen_l2_l3_y", "rt_foramen_l3_l4_y", "rt_foramen_l4_l5_y", "rt_foramen_l5_s1_y",
    "lt_foramen_l1_l2_z", "lt_foramen_l2_l3_z", "lt_foramen_l3_l4_z", "lt_foramen_l4_l5_z", "lt_foramen_l5_s1_z",
    "rt_foramen_l1_l2_z", "rt_foramen_l2_l3_z", "rt_foramen_l3_l4_z", "rt_foramen_l4_l5_z", "rt_foramen_l5_s1_z"
]
for targ in targets:
	if targ.endswith("_x"):
		df[f"{targ}_abs"] = df[targ] * df["cols"]
	elif targ.endswith("_y"):
		df[f"{targ}_abs"] = df[targ] * df["rows"]
	elif targ.endswith("_z"):
		df[f"{targ}_abs"] = df[targ] * df["num_slices"]

for col in df.columns:
	if col.endswith("_abs"):
		df[col] = df[col].round().astype("int")


save_dir = "../../data/train_foramina_crops_3ch/"
levels = ["l1_l2", "l2_l3", "l3_l4", "l4_l5", "l5_s1"]
for row_idx, row in tqdm(df.iterrows(), total=len(df)):
	images = np.sort(glob.glob(os.path.join("../../data/train_pngs/", str(row.study_id), str(row.series_id), "*.png")))
	tmp_save_dir = os.path.join(save_dir, str(row.study_id), str(row.series_id))
	os.makedirs(tmp_save_dir, exist_ok=True)
	for each_side in ["rt_foramen_", "lt_foramen_"]:
		for each_level in levels:
			instance = each_side + each_level + "_z_abs"
			ch1, ch2, ch3 = max(row[instance] - 1, 0), row[instance], min(row[instance] + 1, len(images) - 1)
			instance_img = np.stack([cv2.imread(images[ch1], 0), cv2.imread(images[ch2], 0), cv2.imread(images[ch3], 0)], axis=-1)
			h, w = int(0.15 * instance_img.shape[0]), int(0.15 * instance_img.shape[1])
			xc, yc = row[each_side + each_level + "_x_abs"], row[each_side + each_level + "_y_abs"]
			x1, x2 = xc - w // 2, xc + w // 2
			y1, y2 = yc - h // 2, yc + h // 2
			cropped_foramen = instance_img[y1:y2, x1:x2]
			status = cv2.imwrite(os.path.join(tmp_save_dir, f"{each_side.upper()}{each_level.upper()}.png"), cropped_foramen)
