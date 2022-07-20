import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request

UNIVAF_AWS_BUCKET = 'univaf-data-snapshots'
DATA_PATH = Path(__file__).parent.parent.absolute() / 'data'
CACHE_PATH = DATA_PATH / 'univaf_raw'
SUPPORTS_AWS_CLI = None


def supports_aws_cli():
    global SUPPORTS_AWS_CLI
    if SUPPORTS_AWS_CLI is None:
        result = subprocess.run(('which', 'aws'), capture_output=True)
        SUPPORTS_AWS_CLI = result.returncode == 0

    return SUPPORTS_AWS_CLI


def s3_copy(source, destination):
    subprocess.run(('aws', 's3', 'cp', source, destination))


def download_file(bucket_path, destination_path, force=False):
    if os.path.exists(destination_path) and not force:
        return

    Path(destination_path).parent.mkdir(parents=True, exist_ok=True)
    if supports_aws_cli():
        s3_uri = f's3://{UNIVAF_AWS_BUCKET}/{bucket_path}'
        subprocess.run(('aws', 's3', 'cp', '--no-sign-request', s3_uri, destination_path))
    else:
        url = f'http://{UNIVAF_AWS_BUCKET}.s3.amazonaws.com/{bucket_path}'
        print(f'Writing {url} to {destination_path}', file=sys.stderr)
        with open(destination_path, 'wb') as f:
            with urllib.request.urlopen(url) as remote:
                f.write(remote.read())


def log_file_name(log_type, date):
    return f'{log_type}-{date}.ndjson.gz'


def log_file_path(log_type, date):
    return CACHE_PATH / log_file_name(log_type, date)


def download_log_file(log_type, date):
    file_name = log_file_name(log_type, date)
    download_file(f'{log_type}/{file_name}', CACHE_PATH / file_name)


def open_file(filepath, compressed=None):
    if compressed is None:
        compressed = str(filepath).endswith('.gz')


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
