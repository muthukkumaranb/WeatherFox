import csv
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

def generate_sample_review():
    logging.basicConfig(level=logging.INFO)
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    
    out_file = reports_dir / "review.csv"
    
    with open(out_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["station_id", "ts_utc", "variable", "value", "reviewer_1", "reviewer_2", "notes"])
        # Mock 200 rows
        for i in range(200):
            writer.writerow([f"INI{i:04d}", "2023-01-01T12:00:00Z", "T", 25.0, "", "", ""])
            
    logger.info(f"Sample review CSV written to {out_file}.")

if __name__ == "__main__":
    generate_sample_review()
