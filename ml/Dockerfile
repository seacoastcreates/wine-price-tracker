# SageMaker Processing image for quarterly retraining. Library versions come from pyproject.toml's exact
# pins, which the API server also installs, so artifacts trained here always load in serving.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /opt/program
COPY pyproject.toml ./
COPY wineprice ./wineprice
RUN pip install --no-cache-dir .
COPY train.py train_vintage.py train_fair.py sagemaker_job.py ./
ENTRYPOINT ["python3", "/opt/program/sagemaker_job.py"]
