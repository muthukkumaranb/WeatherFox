import json
from pathlib import Path
from skyguard.eval.srt_baseline import srt_baseline

def main():
    print("Loading train data...")
    train_rows = []
    with open("splits/train.jsonl", "r") as f:
        for line in f:
            train_rows.append(json.loads(line))
            
    print("Loading val_eval data...")
    val_rows = []
    with open("splits/val_eval.jsonl", "r") as f:
        for line in f:
            val_rows.append(json.loads(line))
            
    print("Running SRT baseline...")
    verdicts = srt_baseline(val_rows, train_rows, "reports/val/srt_baseline.jsonl")
    print(f"Saved {len(verdicts)} verdicts.")

if __name__ == "__main__":
    main()
