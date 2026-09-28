"""Entry point of the SageMaker Processing job: trains all three models on the exported data.

SageMaker mounts the input under /opt/ml/processing/input/data and uploads everything written to
/opt/ml/processing/output to S3 when the job ends.
"""

import subprocess
import sys
import time

IN = "/opt/ml/processing/input/data"
OUT = "/opt/ml/processing/output"
STEPS = [
    ("price-change model", ["train.py"]),
    ("next-vintage model", ["train_vintage.py"]),
    ("fair-price model", ["train_fair.py"]),
]


def main() -> int:
    for label, script in STEPS:
        started = time.time()
        print(f"=== {label}: {' '.join(script)}", flush=True)
        subprocess.run([sys.executable, *script, "--input", IN, "--output", OUT], check=True)
        print(f"=== {label} done in {time.time() - started:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
