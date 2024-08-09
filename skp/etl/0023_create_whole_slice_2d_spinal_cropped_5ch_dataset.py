import cv2
import glob
import numpy as np
import os
import pandas as pd

from tqdm import tqdm


coords_df = pd.read_csv("../../data/train_label_coordinates.csv")
coords_df = coords_df.loc[coords_df.condition.apply(lambda x: "Spinal" in x)]

data_dir = "../../data/train_pngs_3ch/"
save_dir = "../../data/train_spinal_cropped_whole_slices/"
os.makedirs(save_dir, exist_ok=True)

for series_id, series_df in tqdm(coords_df.groupby("series_id"), total=len(coords_df.series_id.unique())):
	if len(series_df) != 5:
		continue
	if len(series_df.level.unique()) != 5:
		continue
	median_slice = int(series_df.instance_number.median())
	# Take full extent of y-axis, but use x-coordinate to crop the width of the image
	mean_x = int(np.round(series_df.x.mean()))
	study_id = series_df.study_id.values[0]
	images = list(np.sort(glob.glob(os.path.join(data_dir, str(study_id), str(series_id), "*.png"))))
	images = [images[0]] * 5 + images + [images[-1]] * 5
	# Repeat first and last images in case for some reason the selected median slice index is on the edge
	image_instance_numbers = [int(os.path.basename(_).split("_")[-1].replace(".png", "").replace("INST", "")) for _ in images]
	middle_image_index = image_instance_numbers.index(median_slice)
	selected_images = images[middle_image_index-2:middle_image_index+3]
	img_5ch = np.stack([cv2.imread(each_img)[..., 1] for each_img in selected_images], axis=-1) # take middle channel
	img_5ch = img_5ch[:, mean_x-64:mean_x+64]
	assert img_5ch.shape[-1] == 5
	for each_ch in range(img_5ch.shape[-1]):
		tmp_save_dir = os.path.join(save_dir, f"{study_id}_{series_id}")
		os.makedirs(tmp_save_dir, exist_ok=True)
		status = cv2.imwrite(os.path.join(tmp_save_dir, f"IM{each_ch:06d}.png"), img_5ch[..., each_ch])


### 

df = pd.read_csv("../../data/train_spinal_3d_whole_series.csv")
df["series_folder"] = df.series_folder.apply(lambda x: x.replace("/", "_"))
df.to_csv("../../data/train_spinal_cropped_whole_slices_2d.csv", index=False)