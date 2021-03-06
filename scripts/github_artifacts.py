#!/usr/bin/env python3
import argparse
import json
import os.path
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from tempfile import TemporaryFile
from zipfile import ZipFile

import requests
from requests.auth import HTTPBasicAuth


def find_artifacts(repo, auth):
    # TODO(ddn): Use the PyGithub package like the version script does.
    repo_prefix = f"https://api.github.com/repos/{repo}"
    response = requests.get(
        f"{repo_prefix}/actions/runs",
        params={"branch": "master", "status": "success"},
        headers={"Accept": "application/vnd.github.v3+json"},
        auth=auth,
    )
    runs = response.json()
    conda_package_ubuntu_artifact = None
    conda_package_macos_artifact = None
    docs_artifact = None
    for run in runs["workflow_runs"]:
        response = requests.get(run["artifacts_url"], headers={"Accept": "application/vnd.github.v3+json"}, auth=auth)
        artifacts = response.json()
        for artifact in artifacts["artifacts"]:
            if artifact["name"].startswith("conda-pkgs-ubuntu") and not conda_package_ubuntu_artifact:
                conda_package_ubuntu_artifact = artifact
            if artifact["name"].startswith("conda-pkgs-MacOS") and not conda_package_macos_artifact:
                conda_package_macos_artifact = artifact
            if artifact["name"].startswith("katana-python-docs") and not docs_artifact:
                docs_artifact = artifact
        # TODO(amp): docs_artifact and conda_package_macos_artifact are broken.
        if conda_package_ubuntu_artifact:
            print(f"Found artifacts at commit: {run['head_commit']['message']}")
            break
    return conda_package_ubuntu_artifact, conda_package_macos_artifact, docs_artifact


def download_and_unpack(artifact, path, auth):
    if artifact is None:
        return

    try:
        os.mkdir(path)
    except FileExistsError:
        pass

    response = requests.get(artifact["archive_download_url"], stream=True, auth=auth)
    with TemporaryFile(mode="w+b") as tmp:
        for chunk in response.iter_content(chunk_size=1024):
            tmp.write(chunk)
        tmp.seek(0)
        with ZipFile(tmp) as unzipper:
            unzipper.extractall(path)
        print(f"Extracted artifact {artifact['name']} into {path}")


def get_auth():
    try:
        password = os.environ.get("GITHUB_PASSWORD", os.environ.get("GITHUB_TOKEN", None))
        if not password:
            raise KeyError()
        return HTTPBasicAuth(os.environ["GITHUB_USERNAME"], password)
    except KeyError:
        return None


def list_cmd(args):
    repo = args.repo
    if args.limit < 0:
        limit = None
    else:
        limit = args.limit

    auth = get_auth()
    if not auth:
        print(
            "This script requires GITHUB_USERNAME and either GITHUB_PASSWORD "
            "or GITHUB_TOKEN to be set to valid Github credentials."
        )
        return 2

    repo_prefix = f"https://api.github.com/repos/{repo}"
    page = 0
    while True:
        response = requests.get(
            f"{repo_prefix}/actions/artifacts",
            params={"page": page},
            headers={"Accept": "application/vnd.github.v3+json"},
            auth=auth,
        )

        data = response.json()["artifacts"]
        data_len = len(data)

        if data_len == 0:
            break
        if limit is not None:
            data_len = min(data_len, limit)
            limit -= data_len

        json.dump(data[:data_len], sys.stdout, indent="  ")

        if limit is not None and limit == 0:
            break

        page += 1

    return 0


def python_cmd(args):
    leave = args.leave
    upload_pkgs = args.upload_pkgs
    upload_docs = args.upload_docs
    repo = args.repo

    if not leave and not upload_pkgs and not upload_docs:
        print("Aborting because the downloaded artifacts would not be uploaded or left for other uses.")
        print()
        return 1

    auth = get_auth()
    if not auth:
        print(
            "This script requires GITHUB_USERNAME and either GITHUB_PASSWORD or "
            "GITHUB_TOKEN to be set to valid Github credentials."
        )
        return 2

    conda_package_ubuntu_artifact, conda_package_macos_artifact, docs_artifact = find_artifacts(repo, auth)

    dir = Path(tempfile.mkdtemp())
    pkgs_dir = dir / "galois-pkgs"
    docs_dir = dir / "galois-docs"

    download_and_unpack(conda_package_ubuntu_artifact, os.path.expanduser(pkgs_dir), auth)
    download_and_unpack(conda_package_macos_artifact, os.path.expanduser(pkgs_dir), auth)
    download_and_unpack(docs_artifact, os.path.expanduser(docs_dir), auth)

    packages = list((pkgs_dir).glob("*/*.tar.bz2"))
    package_names = [str(f.name) for f in packages]
    print("Downloaded packages: " + ", ".join(package_names))

    pkgs_upload_cmd = ["anaconda", "upload", "-u", "KatanaGraph", "--label", "dev"] + [str(f) for f in packages]

    try:
        if upload_pkgs:
            subprocess.check_call(pkgs_upload_cmd)

        if upload_docs:
            # TODO(amp): Add support for docs upload once we have a place to upload the docs.
            raise NotImplementedError("Uploading documentation is not yet supported.")
    except subprocess.CalledProcessError as e:
        leave = True
        print()
        print(f"An upload failed, leaving downloaded files: {e}")
        print()

    if leave:
        print("Upload packages with:")
        print()
        print(" ".join(pkgs_upload_cmd))
        print()
        # TODO(amp): Add instructions for docs upload
        print(f"This script leaves the downloaded katana-python documentation in: {docs_dir}")
        print(f"This script leaves the downloaded conda packages in: {pkgs_dir}")
        print(f"To clean up after this script, delete: {dir}")
    return 0


def main():
    parser = argparse.ArgumentParser()
    sub_parsers = parser.add_subparsers()

    python_parser = sub_parsers.add_parser(
        "python", help="Download python artifacts and optionally upload them to anaconda"
    )
    python_parser.set_defaults(func=python_cmd)

    python_parser.add_argument(
        "--upload-pkgs",
        "-p",
        action="store_true",
        default=False,
        help="Upload the packages in the artifacts to anaconda. Requires you to be logged into anaconda.",
    )
    python_parser.add_argument(
        "--upload-docs",
        "-d",
        action="store_true",
        default=False,
        help="Upload the documentation in the artifacts to ???. This is not yet implemented.",
    )
    python_parser.add_argument(
        "--leave",
        "-l",
        action="store_true",
        default=False,
        help="Leave the downloaded and unpacked artifacts in the temporary directory for other uses.",
    )
    python_parser.add_argument(
        "--repo", default="katanagraph/katana", help="Repo to query",
    )

    list_parser = sub_parsers.add_parser("list", help="List artifacts in a repo")
    list_parser.set_defaults(func=list_cmd)

    list_parser.add_argument(
        "--repo", default="katanagraph/katana", help="Repo to query",
    )
    list_parser.add_argument(
        "--limit",
        default=500,
        type=int,
        help="Limit output to a number of entries. Values less than zero mean no limit.",
    )

    args = parser.parse_args()

    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)

    exit_code = args.func(args)
    if exit_code == 1:
        parser.print_help()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
