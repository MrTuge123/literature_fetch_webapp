"""Package the Python code for Lambda without Docker.

Lambda runs Linux on arm64, so `pip install` must fetch Linux arm64 wheels, not the macOS ones:
--platform manylinux2014_aarch64 --only-binary=:all: does that from your Mac. Then the code
(digest/, api/, config.yaml) is copied next to the packages. Nothing else from the repo is
included: no .env, seen/, history/ or subscribers/.

The asset hash covers the code and requirements-lambda.txt, so `cdk deploy` uploads a new zip
only when one of them changed. (Switching to Docker later: drop `local=` and CDK builds in
the image below instead.)
"""
import hashlib
import os
import shutil
import subprocess
import sys

import aws_cdk as cdk
import jsii
from aws_cdk import aws_lambda as lambda_

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CODE = ["digest", "api", "config.yaml"]
REQUIREMENTS = "requirements-lambda.txt"
PYTHON = "3.12"
PLATFORM = "manylinux2014_aarch64"
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store")


def _files():
    for name in CODE + [REQUIREMENTS]:
        path = os.path.join(REPO, name)
        if os.path.isfile(path):
            yield name, path
            continue
        for root, dirs, files in os.walk(path):
            dirs[:] = sorted(d for d in dirs if d != "__pycache__")
            for f in sorted(files):
                if not f.endswith(".pyc"):
                    full = os.path.join(root, f)
                    yield os.path.relpath(full, REPO), full


def source_hash():
    h = hashlib.sha256()
    for rel, full in _files():
        h.update(rel.encode())
        with open(full, "rb") as f:
            h.update(f.read())
    return h.hexdigest()


@jsii.implements(cdk.ILocalBundling)
class LocalPip:
    def try_bundle(self, output_dir, *args, **kwargs):
        print(f"Bundling the worker: pip install ({PLATFORM}, Python {PYTHON}) + {', '.join(CODE)}")
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--no-compile",
                        "-r", os.path.join(REPO, REQUIREMENTS), "--target", output_dir,
                        "--platform", PLATFORM, "--implementation", "cp", "--python-version", PYTHON,
                        "--only-binary=:all:"], check=True)
        for name in CODE:
            src, dst = os.path.join(REPO, name), os.path.join(output_dir, name)
            if os.path.isdir(src):
                shutil.copytree(src, dst, ignore=IGNORE, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)
        return True


def worker_code():
    return lambda_.Code.from_asset(
        os.path.join(REPO, "api"),                   # only used for Docker builds; LocalPip reads REPO
        asset_hash_type=cdk.AssetHashType.CUSTOM,
        asset_hash=source_hash(),
        bundling=cdk.BundlingOptions(
            image=lambda_.Runtime.PYTHON_3_12.bundling_image,
            local=LocalPip(),
            command=["bash", "-c", "echo 'Docker build not set up yet' && exit 1"],
        ),
    )
