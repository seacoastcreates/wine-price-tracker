"""Retrain all models on SageMaker and publish the result.

    python -m scripts.sagemaker_train

1. Export the training data (series + context tables) and upload it to S3.
2. Run a SageMaker Processing job (the training image built from ml/Dockerfile) and wait for it.
3. Copy the job's output into the S3 model registry under its model version.
4. Register the model as active and load its forecasts, outlooks, fair prices and metrics.

Configuration comes from the environment: ARTIFACT_BUCKET, SAGEMAKER_ROLE_ARN, TRAIN_IMAGE_URI,
and optionally TRAIN_INSTANCE_TYPE (default ml.t3.xlarge).
"""

import json
import os
from functools import lru_cache
import sys
import tempfile
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError, WaiterError

from scripts import ml_io

INPUT_DIR = "/opt/ml/processing/input/data"
OUTPUT_DIR = "/opt/ml/processing/output"



@lru_cache
def _s3():
    return boto3.client("s3")


@lru_cache
def _sagemaker():
    return boto3.client("sagemaker")


def upload_dir(local: Path, bucket: str, prefix: str) -> None:
    for f in sorted(local.iterdir()):
        if f.is_file():
            _s3().upload_file(str(f), bucket, f"{prefix}/{f.name}")


def download_prefix(bucket: str, prefix: str, local: Path) -> None:
    local.mkdir(parents=True, exist_ok=True)
    for key in _s3().get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix + "/").search("Contents[].Key"):
        if key and not key.endswith("/"):
            _s3().download_file(bucket, key, str(local / Path(key).name))


def copy_prefix(bucket: str, src: str, dst: str) -> None:
    for key in _s3().get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=src + "/").search("Contents[].Key"):
        if key:
            _s3().copy_object(Bucket=bucket, Key=f"{dst}/{Path(key).name}", CopySource={"Bucket": bucket, "Key": key})


def run(bucket: str, role_arn: str, image_uri: str, instance_type: str) -> str:
    job = time.strftime("cellar-train-%Y%m%d-%H%M%S", time.gmtime())
    run_prefix = f"runs/{job}"
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp) / "input"
        ml_io.export(str(data / "series.csv"))
        upload_dir(data, bucket, f"{run_prefix}/input")

    sagemaker = _sagemaker()
    sagemaker.create_processing_job(
        ProcessingJobName=job,
        RoleArn=role_arn,
        AppSpecification={"ImageUri": image_uri},
        ProcessingResources={"ClusterConfig": {"InstanceCount": 1, "InstanceType": instance_type, "VolumeSizeInGB": 30}},
        ProcessingInputs=[{
            "InputName": "data",
            "S3Input": {"S3Uri": f"s3://{bucket}/{run_prefix}/input/", "LocalPath": INPUT_DIR,
                        "S3DataType": "S3Prefix", "S3InputMode": "File"},
        }],
        ProcessingOutputConfig={"Outputs": [{
            "OutputName": "artifacts",
            "S3Output": {"S3Uri": f"s3://{bucket}/{run_prefix}/output", "LocalPath": OUTPUT_DIR,
                         "S3UploadMode": "EndOfJob"},
        }]},
        StoppingCondition={"MaxRuntimeInSeconds": 4 * 3600},
        Tags=[{"Key": "project", "Value": "cellar-index"}],
    )
    print(f"Started SageMaker Processing job {job} on {instance_type}", flush=True)
    try:
        sagemaker.get_waiter("processing_job_completed_or_stopped").wait(
            ProcessingJobName=job, WaiterConfig={"Delay": 60, "MaxAttempts": 240})
    except WaiterError:
        pass  # the status check below reports the failure reason
    desc = sagemaker.describe_processing_job(ProcessingJobName=job)
    if desc["ProcessingJobStatus"] != "Completed":
        raise RuntimeError(f"{job} ended {desc['ProcessingJobStatus']}: {desc.get('FailureReason', 'no reason given')}")
    minutes = (desc["ProcessingEndTime"] - desc["ProcessingStartTime"]).total_seconds() / 60
    print(f"{job} completed in {minutes:.0f} min", flush=True)

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        download_prefix(bucket, f"{run_prefix}/output", out)
        version = json.loads((out / "metrics.json").read_text())["model_version"]
        copy_prefix(bucket, f"{run_prefix}/output", f"registry/{version}")
        ml_io.load(str(out), artifact_uri=f"s3://{bucket}/registry/{version}/model.joblib")
    return version


def main() -> int:
    try:
        version = run(os.environ["ARTIFACT_BUCKET"], os.environ["SAGEMAKER_ROLE_ARN"], os.environ["TRAIN_IMAGE_URI"],
                      os.environ.get("TRAIN_INSTANCE_TYPE", "ml.t3.xlarge"))
        print(f"Model {version} is now active")
        return 0
    except (ClientError, RuntimeError, KeyError) as e:
        print(f"Retraining failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
