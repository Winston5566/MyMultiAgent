
import json
import os

from pathlib import Path

CHECKPOINT_FILE = Path(
    os.getenv(
        "MULTIAGENT_CHECKPOINT",
        "resilient_checkpoint.json"
    )
)


def save_checkpoint(data):

    # 先写入临时文件
    temp_file = CHECKPOINT_FILE.with_suffix(".tmp")

    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

    # 写入成功后，再替换正式文件
    os.replace(temp_file, CHECKPOINT_FILE)


def load_checkpoint():

    if not CHECKPOINT_FILE.exists():
        return None

    with open(
        CHECKPOINT_FILE,
        "r",
        encoding="utf-8"
    ) as f:
        return json.load(f)
