import bz2
import tarfile
from io import BytesIO
from pathlib import Path

import pandas as pd

from .tar_writer import WebDatasetWriter


def read_bz2_file(file_path: Path):
    """
    Reads a .bz2 compressed file and returns its decompressed content as bytes.
    """
    try:
        with bz2.open(file_path, "rb") as bz2f:
            return bz2f.read()
    except FileNotFoundError:
        print(f"Error: The file '{file_path}' was not found.")
    except Exception as e:
        print(f"An error occurred while reading '{file_path}': {e}")
    return None


def read_gaze_data(file_path):
    # Now read the whole file as raw text to get the gaze part
    gaze_data = []
    with open(file_path, "r") as f:
        next(f)  # skip header
        for line in f:
            parts = line.strip().split(",")
            try:
                gaze_floats = list(map(float, parts[6:]))
            except ValueError:
                gaze_floats = [-1, -1]
            gaze_points = [
                [gaze_floats[i], gaze_floats[i + 1]]
                for i in range(0, len(gaze_floats), 2)
            ]
            gaze_data.append(gaze_points)
    # Add gaze column to dataframe
    return gaze_data


def extract_images_and_write_to_webdataset(tar_bz2_file, writer, eye_gaze) -> None:
    """
    Decompresses the .tar.bz2 file, extracts images, and writes them to a WebDataset tar file.
    """
    decompressed_data = read_bz2_file(tar_bz2_file)
    if decompressed_data is None:
        return

    tar_bytes = BytesIO(decompressed_data)

    with tarfile.open(fileobj=tar_bytes, mode="r:") as tar:
        for num, member in enumerate(tar.getmembers()):
            # NOTE: The first member of tar (num=0) file is the info. So the images start from num=1
            if member.isfile():
                file_data = tar.extractfile(member).read()
                try:
                    sample = {
                        "__key__": str(num),
                        "jpg": file_data,
                        "json": eye_gaze[num - 1],  # img index starts from 1
                    }
                    writer.write(sample)
                except ValueError:
                    print("incorrect data format")


def get_game_meta_data(game: str, config: dict) -> pd.DataFrame:
    """
    Reads meta data CSV from config and returns DataFrame grouped by subject_id with list of trial_ids for the given game.
    """
    meta_data_path = Path(config["meta_data_path"])
    meta_data = pd.read_csv(meta_data_path)
    game_meta_data = (
        meta_data[meta_data["GameName"] == game]
        .groupby("subject_id")["trial_id"]
        .apply(list)
        .reset_index()
    )
    return game_meta_data


def eye_gaze_to_webdataset(game: str, config: dict) -> None:
    """
    For each subject and trial in the specified game, reads the corresponding eye gaze data file
    and writes images to a WebDataset tar file.
    """
    webdataset_writer = WebDatasetWriter(config)

    raw_data_path = Path(config["raw_data_path"]) / game
    game_meta_data = get_game_meta_data(game, config)

    for _, row in game_meta_data.iterrows():
        subject_id = row["subject_id"]
        trial_ids = row["trial_id"]

        print(f"Reading data for subject: {subject_id}")

        for run, trial_id in enumerate(trial_ids):
            pattern = f"{trial_id}_{subject_id}*.txt"
            matched_files = list(raw_data_path.glob(pattern))

            # Create a tar file with subject_id and trail_id
            webdataset_writer.create_tar_file(
                file_name=f"{subject_id}_{trial_id}",
                write_path=config["processed_data_path"] + f"/{game}/",
            )

            if not matched_files:
                print(f"Warning: No files found for pattern '{pattern}'")
                continue

            file_path = matched_files[0]
            read_path = file_path.with_suffix("")  # remove '.txt'
            eye_gaze = read_gaze_data(file_path)

            # Write the game frames to .tar files
            tar_bz2_file = read_path.with_name(f"{read_path.name}.tar.bz2")
            extract_images_and_write_to_webdataset(
                tar_bz2_file, webdataset_writer, eye_gaze
            )

    # Close the webdataset writer gracefully
    webdataset_writer.close()
