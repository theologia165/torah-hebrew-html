#!/usr/bin/env python3
"""Issue and verify a one-time R2 upload ticket without putting image bytes in Git."""
import hashlib
import json
import os
import sys
from pathlib import Path

import boto3
from botocore.config import Config

BUCKET = "asaichi-torah-images"


def client():
    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        region_name="auto",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def ticket(request_path, output_path):
    request = load(request_path)
    url = client().generate_presigned_url(
        "put_object",
        Params={"Bucket": BUCKET, "Key": request["object_key"], "ContentType": request["content_type"]},
        ExpiresIn=600,
        HttpMethod="PUT",
    )
    result = {
        "run_id": request["run_id"],
        "object_key": request["object_key"],
        "content_type": request["content_type"],
        "byte_size": request["byte_size"],
        "sha256": request["sha256"],
        "expires_in_seconds": 600,
        "put_url": url,
    }
    Path(output_path).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


def verify(request_path, output_path):
    request = load(request_path)
    response = client().get_object(Bucket=BUCKET, Key=request["object_key"])
    body = response["Body"].read()
    result = {
        "run_id": request["run_id"],
        "object_key": request["object_key"],
        "expected_sha256": request["sha256"],
        "actual_sha256": hashlib.sha256(body).hexdigest(),
        "expected_byte_size": request["byte_size"],
        "actual_byte_size": len(body),
        "expected_content_type": request["content_type"],
        "actual_content_type": response.get("ContentType"),
    }
    assert result["actual_sha256"] == result["expected_sha256"], "R2 SHA-256 mismatch"
    assert result["actual_byte_size"] == result["expected_byte_size"], "R2 byte size mismatch"
    assert result["actual_content_type"] == result["expected_content_type"], "R2 content type mismatch"
    result["status"] = "PASS"
    Path(output_path).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] not in {"ticket", "verify"}:
        raise SystemExit("usage: r2_transfer_test.py ticket|verify request.json output.json")
    {"ticket": ticket, "verify": verify}[sys.argv[1]](sys.argv[2], sys.argv[3])
