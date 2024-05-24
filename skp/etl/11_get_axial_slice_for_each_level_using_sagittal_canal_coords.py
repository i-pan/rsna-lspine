import numpy as np
import pandas as pd


coords_df = pd.read_csv("../../data/predicted_sagittal_t2_stir_canal_coords_oof.csv")
meta_df = pd.read_csv("../../data/dicom_metadata.csv")
series_descriptions = pd.read_csv("../../data/train_series_descriptions.csv")

relevant_cols = ["study_id", "series_id", "rows", "cols"]
coords_df = coords_df.merge(meta_df[relevant_cols].drop_duplicates(), on=relevant_cols[:2])
num_slices_per_series = {}
for series_id, series_df in meta_df.groupby("series_id"):
    num_slices_per_series[series_id] = len(series_df)

coords_df["num_slices"] = coords_df.series_id.map(num_slices_per_series)

targets = [
    "canal_l1_l2_x", "canal_l2_l3_x", "canal_l3_l4_x", "canal_l4_l5_x", "canal_l5_s1_x",
    "canal_l1_l2_y", "canal_l2_l3_y", "canal_l3_l4_y", "canal_l4_l5_y", "canal_l5_s1_y",
    "canal_l1_l2_z", "canal_l2_l3_z", "canal_l3_l4_z", "canal_l4_l5_z", "canal_l5_s1_z"
]
for targ in targets:
	if targ.endswith("_x"):
		coords_df[f"{targ}_abs"] = coords_df[targ] * coords_df["cols"]
	elif targ.endswith("_y"):
		coords_df[f"{targ}_abs"] = coords_df[targ] * coords_df["rows"]
	elif targ.endswith("_z"):
		coords_df[f"{targ}_abs"] = coords_df[targ] * coords_df["num_slices"]

for col in coords_df.columns:
	if col.endswith("_abs"):
		coords_df[col] = coords_df[col].round().astype("int")

levels = ["l1_l2", "l2_l3", "l3_l4", "l4_l5", "l5_s1"]
dfs_by_level = {}
for each_level in levels:
	level_df = coords_df[["study_id", "series_id"] + [c for c in coords_df.columns if each_level in c]].copy()
	level_df["instance_number"] = level_df[f"canal_{each_level}_z_abs"]
	level_df = level_df.merge(meta_df, on=["study_id", "series_id", "instance_number"])
	dfs_by_level[each_level] = level_df

ax_df = meta_df.loc[meta_df.ImagePlane == "AX"]

axial_slices = []
for each_level, level_df in dfs_by_level.items():
	for each_study_id, study_df in level_df.groupby("study_id"):
		# y-coordinate of sagittal slice will determine WHICH axial slice
		# x-coordinate of sagittal slice will determine y-coordinate of axial slice
		# sagittal slice number will determine x-coordinate of axial slice
		#
		# First, does an axial slice even exist at the specified level? 
		# Remember, some studies are missing part of the axial images
		ax_study_df = ax_df.loc[ax_df.study_id == each_study_id].copy()
		ax_range = (ax_study_df.ImagePositionPatient2.min(), ax_study_df.ImagePositionPatient2.max())
		# This is the position in PIXEL SPACE
		level_position = study_df[f"canal_{each_level}_y_abs"].iloc[0]
		# Now map to world space. ..
		# For sagittal slice, top left-hand corner coordinate is given by (ImagePositionPatient1, ImagePositionPatient2)
		# Thus ImagePositionPatient2 is the CRANIAL MARGIN
		cranial_margin = study_df.ImagePositionPatient2.iloc[0]
		# Need to scale level_position by PixelSpacing
		level_position = study_df.PixelSpacing1.iloc[0] * level_position
		# Values are negative CAUDALLY thus need to subtract level_position from cranial_margin
		level_position = cranial_margin - level_position
		within_range = level_position >= ax_range[0] and level_position <= ax_range[1]
		if not within_range:
			continue
		# Once we determine there is an axial slice near this level, we find it using the minimum distance
		ax_study_df["diff"] = np.abs(ax_study_df.SliceLocation.values - level_position)
		target_axial_slice = ax_study_df.sort_values("diff", ascending=True).iloc[:1]
		target_axial_slice["level"] = each_level
		axial_slices.append(target_axial_slice)

axial_slices_df = pd.concat(axial_slices)
axial_slices_df[["study_id", "series_id", "instance_number", "level"]].to_csv("../../data/axial_slices_per_level_based_on_sagittal_canal_coords.csv", index=False) 
