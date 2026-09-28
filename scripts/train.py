import argparse
import json
import logging
from pathlib import Path

from skyguard.detect.detector import Detector

logger = logging.getLogger(__name__)

def train():
    logging.basicConfig(level=logging.INFO)
    data_dir = Path("data")
    splits_dir = Path("splits")
    
    if not splits_dir.exists():
        logger.error("splits directory not found")
        return
        
    logger.info("Loading train split...")
    train_rows = []
    with open(splits_dir / "train.jsonl", "r") as f:
        for line in f:
            train_rows.append(json.loads(line))
            
    # filter to NORMAL data
    # The prompt says: Train only on NORMAL data (rows where no fault was injected)
    # Wait, the split.jsonl from step 1 are just the clean observations.
    # The injected data is in injected_train.parquet. We should train on the clean data.
    # So `train_rows` from splits/train.jsonl is purely clean/normal.
    
    logger.info("Loading val split...")
    val_rows = []
    with open(splits_dir / "val.jsonl", "r") as f:
        for line in f:
            val_rows.append(json.loads(line))
            
    logger.info(f"Training on {len(train_rows)} rows...")
    detector = Detector()
    detector.fit(train_rows, val_rows)
    logger.info("Training complete and models saved.")

if __name__ == "__main__":
    train()
