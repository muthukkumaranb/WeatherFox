import argparse
import json
import logging
from pathlib import Path

from skyguard.data.inject import inject_faults
import pandas as pd

logger = logging.getLogger(__name__)

def make_injections():
    logging.basicConfig(level=logging.INFO)
    data_dir = Path("data")
    splits_dir = Path("splits")
    
    if not splits_dir.exists():
        logger.error("splits directory not found")
        return
        
    # Read original stream
    clean_obs_dir = data_dir / "clean" / "obs"
    if not clean_obs_dir.exists():
        logger.error("clean/obs not found")
        return
        
    for split_file in splits_dir.glob("*.jsonl"):
        split = split_file.stem
        if split == "split":
            continue
            
        logger.info(f"Injecting faults for {split}...")
        
        # Determine seed based on split
        seed = 1 if split == "train" else 2 if split == "val" else 3
        
        rows = []
        with open(split_file, "r") as f:
            for line in f:
                rows.append(json.loads(line))
                
        # Inject
        # Rate: 1-3%
        # The prompt says 1-3% spread over seasons, hours.
        rate = 0.02
        inj_rows, labels = inject_faults(rows, seed=seed, rate=rate, split=split)
        
        # Write injected rows to parquet
        df = pd.DataFrame(inj_rows)
        stream_dir = data_dir / "stream"
        stream_dir.mkdir(exist_ok=True)
        df.to_parquet(stream_dir / f"injected_{split}.parquet")
        
        # Write labels to jsonl
        labels_dir = data_dir / "labels"
        labels_dir.mkdir(exist_ok=True)
        with open(labels_dir / f"injections_{split}.jsonl", "w") as f:
            for lbl in labels:
                f.write(json.dumps(lbl) + "\n")
                
        logger.info(f"Done {split}: {len(inj_rows)} rows, {len(labels)} labels")

if __name__ == "__main__":
    make_injections()
