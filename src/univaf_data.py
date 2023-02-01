import boto3
from botocore import UNSIGNED
from botocore.client import Config
from contextlib import contextmanager
import gzip
import json
import os
from pathlib import Path
import urllib.request

UNIVAF_AWS_BUCKET = 'univaf-data-snapshots'
UNIVAF_ARCHIVES_URL = 'https://archives.getmyvax.org'
DATA_PATH = Path(__file__).parent.parent.absolute() / 'data'
CACHE_PATH = DATA_PATH / 'univaf_raw'

USE_S3 = bool(os.getenv('AWS_ACCESS_KEY_ID') and os.getenv('AWS_SECRET_ACCESS_KEY'))
S3_CLIENT = None


def s3_client():
    global S3_CLIENT
    if S3_CLIENT is None:
        # NOTE: if we need public/non-credentialed S3 usage, set:
        #   config=Config(signature_version=UNSIGNED)
        S3_CLIENT = boto3.client('s3')

    return S3_CLIENT


def download_file(bucket_path, destination_path, force=False, use_s3=USE_S3):
    if os.path.exists(destination_path) and not force:
        return

    print(f'Downloading logfile to: "{destination_path}"')
    Path(destination_path).parent.mkdir(parents=True, exist_ok=True)

    if use_s3:
        download_s3(bucket_path, destination_path)
    else:
        download_http(bucket_path, destination_path)


def download_s3(bucket_path, destination_path):
    # Use Boto instead of normal HTTP because it has logic for multithreaded
    # downloads that makes things ~6 times faster.
    s3_client().download_file(UNIVAF_AWS_BUCKET, bucket_path, str(destination_path))


def download_http(bucket_path, destination_path):
    url = f'{UNIVAF_ARCHIVES_URL.rstrip("/")}/{bucket_path}'
    req = urllib.request.Request(url, headers={'User-Agent': 'univaf-appointment-data-insights/1.0'})
    response = urllib.request.urlopen(req)
    # taken from from https://stackoverflow.com/a/1517728
    CHUNK = 16 * 1024
    with open(destination_path, 'wb') as f:
        while True:
            chunk = response.read(CHUNK)
            if not chunk:
                break
            f.write(chunk)


def log_file_name(log_type, date):
    return f'{log_type}-{date}.ndjson.gz'


def log_file_path(log_type, date):
    return CACHE_PATH / log_file_name(log_type, date)


def download_log_file(log_type, date):
    file_name = log_file_name(log_type, date)
    download_path = CACHE_PATH / file_name
    download_file(f'{log_type}/{file_name}', download_path)
    return download_path


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
