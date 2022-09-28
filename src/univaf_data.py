import boto3
from botocore import UNSIGNED
from botocore.client import Config
from contextlib import contextmanager
import gzip
import json
import os
from pathlib import Path

UNIVAF_AWS_BUCKET = 'univaf-data-snapshots'
DATA_PATH = Path(__file__).parent.parent.absolute() / 'data'
CACHE_PATH = DATA_PATH / 'univaf_raw'

S3_CLIENT = None


def s3_client():
    global S3_CLIENT
    if S3_CLIENT is None:
        # Don't bother loading credentials since the files we want are public.
        S3_CLIENT = boto3.client('s3', config=Config(signature_version=UNSIGNED))

    return S3_CLIENT


def download_file(bucket_path, destination_path, force=False):
    if os.path.exists(destination_path) and not force:
        return

    Path(destination_path).parent.mkdir(parents=True, exist_ok=True)
    # Use Boto instead of normal HTTP because it has logic for multithreaded
    # downloads that makes things ~6 times faster.
    s3_client().download_file(UNIVAF_AWS_BUCKET, bucket_path, destination_path)


def log_file_name(log_type, date):
    return f'{log_type}-{date}.ndjson.gz'


def log_file_path(log_type, date):
    return CACHE_PATH / log_file_name(log_type, date)


def download_log_file(log_type, date):
    file_name = log_file_name(log_type, date)
    download_file(f'{log_type}/{file_name}', CACHE_PATH / file_name)


@contextmanager
def open_file(filepath, compressed=None):
    if compressed is None:
        compressed = str(filepath).endswith('.gz')
    with (gzip.open(filepath, 'rt') if compressed else open(filepath)) as f:
        yield f


def read_json_lines(filepath, compressed=None):
    with open_file(filepath, compressed) as f:
        for line in f:
            if line and line != '\n':
                yield json.loads(line)


def open_log_file(log_type, date):
    filepath = log_file_path(log_type, date)
    return open_file(filepath)


def read_log_lines(log_type, date):
    yield from read_json_lines(log_file_path(log_type, date))
