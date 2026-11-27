#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

UPSTREAM = "Asterisk4Magisk/AsteriskBOX"
INITIAL_TAG = "v1.2.0"
INITIAL_VERSION_CODE = 651
FORK_POINT = "2a748b20b823ebfd14c6dca3df6afb2d1db1343e"
PROJECT_CONFIG = "buildSrc/src/main/kotlin/BuildConfig.kt"
STABLE = r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
FORK = rf"({STABLE})-r\.[1-9][0-9]*"
APK_CODE = r"AsteriskBOX_.+-([1-9][0-9]*)-(?:arm64-v8a|armeabi-v7a|x86|x86_64|universal)\.apk"


def run(*args, data=None):
    return subprocess.run(args, input=data, text=True, check=True, stdout=subprocess.PIPE).stdout.strip()


def releases(repo):
    pages = json.loads(run("gh", "api", "--paginate", "--slurp", f"repos/{repo}/releases?per_page=100"))
    return [release for page in pages for release in page]


def version(tag):
    return tuple(int(part) for part in tag[1:].split("."))


def published_time(release):
    return datetime.fromisoformat(release["published_at"])


def was_published(upstream_tag, fork_releases):
    for release in fork_releases:
        if release["draft"] or release["prerelease"]:
            continue
        match = re.fullmatch(FORK, release["tag_name"])
        if match and version(match[1]) >= version(upstream_tag):
            return True
    return False


def version_floor(fork_releases, upstream_release=None):
    configured = int(os.environ.get("DISTRIBUTED_VERSION_CODE_FLOOR") or "0")
    if not 0 <= configured < 2_100_000_000:
        raise ValueError("DISTRIBUTED_VERSION_CODE_FLOOR is outside the Android versionCode range")
    floor = max(INITIAL_VERSION_CODE, configured)
    distribution = fork_releases + ([upstream_release] if upstream_release else [])
    for release in distribution:
        if release["draft"]:
            continue
        for asset in release["assets"]:
            if not asset["name"].endswith(".apk"):
                continue
            match = re.fullmatch(APK_CODE, asset["name"])
            if not match:
                raise ValueError(f"Cannot establish versionCode for published APK {asset['name']}")
            floor = max(floor, int(match[1]))
    return floor


def eligible(release, start, inclusive):
    if release["draft"] or release["prerelease"]:
        return False
    if release["tag_name"] == start["tag_name"]:
        return inclusive
    if published_time(release) < published_time(start):
        return False
    if not re.fullmatch(STABLE, release["tag_name"]):
        raise ValueError(f"Unexpected official tag {release['tag_name']}; expected vX.Y.Z")
    return version(release["tag_name"]) > version(start["tag_name"])


def official_tag_commit(upstream_tag):
    git_ref = json.loads(run("gh", "api", f"repos/{UPSTREAM}/git/ref/tags/{upstream_tag}"))["object"]
    while git_ref["type"] == "tag":
        git_ref = json.loads(run("gh", "api", f"repos/{UPSTREAM}/git/tags/{git_ref['sha']}"))["object"]
    if git_ref["type"] != "commit":
        raise ValueError(f"Upstream tag {upstream_tag} does not resolve to a commit")
    return git_ref["sha"]


def release_candidate(upstream_release, fork_releases):
    upstream_tag = upstream_release["tag_name"]
    fork_tag = f"{upstream_tag}-r.1"
    fork_source = run("git", "rev-parse", "HEAD")
    run("git", "fetch", "--no-tags", f"https://github.com/{UPSTREAM}.git",
        "+refs/heads/main:refs/remotes/upstream/main",
        f"+refs/tags/{upstream_tag}:refs/upstream-release/{upstream_tag}")
    upstream_commit = run("git", "rev-parse", "--verify", f"refs/upstream-release/{upstream_tag}^{{commit}}")
    if official_tag_commit(upstream_tag) != upstream_commit:
        raise ValueError(f"GitHub and Git disagree on the commit for {upstream_tag}")
    config = run("git", "show", f"{upstream_commit}:{PROJECT_CONFIG}")
    match = re.search(r'^\s*const val VERSION_NAME = "([^"]+)"', config, re.MULTILINE)
    if not match or match[1] != upstream_tag[1:]:
        raise ValueError(f"{upstream_tag} resolves to {upstream_commit}, whose source version is {match[1] if match else 'missing'}")

    bases = run("git", "merge-base", "--all", fork_source, "refs/remotes/upstream/main").splitlines()
    if len(bases) != 1:
        raise ValueError("Cannot identify a unique fork overlay base")
    if subprocess.run(["git", "merge-base", "--is-ancestor", FORK_POINT, bases[0]]).returncode:
        raise ValueError("Fork overlay base predates the original fork point. Confirm upstream history.")
    overlay = subprocess.check_output(["git", "diff", "--binary", "--full-index", bases[0], fork_source])
    if not overlay:
        raise ValueError("Fork overlay is empty")
    run("git", "switch", "--detach", upstream_commit)
    if subprocess.run(["git", "apply", "--3way", "--index"], input=overlay).returncode:
        raise ValueError(f"Fork changes conflict with {upstream_tag}")
    if not re.search(rf'^\s*const val VERSION_NAME = "{re.escape(upstream_tag[1:])}"',
                     Path(PROJECT_CONFIG).read_text(), re.MULTILINE):
        raise ValueError("Fork overlay changed the upstream source version")
    properties = Path("gradle.properties")
    if re.search(r"^\s*asteriskBoxForkRevision\s*=", properties.read_text(), re.MULTILINE):
        raise ValueError("Fork revision must be assigned only on the release tree")
    with properties.open("a") as stream:
        stream.write("\nasteriskBoxForkRevision=1\n")
    run("git", "add", "gradle.properties")
    if "AppUpdateSection()" not in Path("app/src/main/kotlin/features/about/AboutPage.kt").read_text():
        raise ValueError("Fork overlay lost the app updater entry")
    tree = run("git", "write-tree")

    ref = f"refs/tags/{fork_tag}"
    existing = run("git", "ls-remote", "--tags", "origin", ref)
    if existing:
        run("git", "fetch", "--no-tags", "origin", f"{ref}:refs/fork-release/{fork_tag}")
        candidate = run("git", "rev-parse", f"refs/fork-release/{fork_tag}^{{commit}}")
        parents = run("git", "show", "-s", "--format=%P", candidate).split()
        if len(parents) != 2 or parents[0] != upstream_commit:
            raise ValueError(f"Existing {fork_tag} does not have the expected upstream first parent")
        if run("git", "rev-parse", f"{candidate}^{{tree}}") != tree:
            raise ValueError(f"Existing {fork_tag} contains a different fork overlay. Inspect the failed release tag.")
        print(f"Reusing {fork_tag} at {candidate}", flush=True)
    else:
        candidate = run(
            "git", "-c", "user.name=github-actions[bot]",
            "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
            "commit-tree", tree, "-p", upstream_commit, "-p", fork_source,
            "-m", f"Prepare AsteriskBOX {fork_tag}", "-m", f"Upstream-release: {upstream_tag}",
        )
    code = int(run("git", "rev-list", "--count", candidate))
    print(f"Upstream tag {upstream_tag} -> {upstream_commit}; upstream main {run('git', 'rev-parse', 'refs/remotes/upstream/main')}")
    print(f"Fork {fork_tag} -> {candidate}; versionCode {code}")

    floor = version_floor(fork_releases, upstream_release)
    require_higher(code, floor)
    print(f"versionCode {code} exceeds distribution floor {floor}.")
    return fork_tag, candidate, upstream_commit, code, existing


def require_higher(code, floor):
    if not floor < code <= 2_100_000_000:
        raise ValueError(f"Candidate versionCode {code} must exceed distribution floor {floor} and fit Android's limit")


def main():
    repo = os.environ["GITHUB_REPOSITORY"]
    fork_releases = releases(repo)
    if sys.argv[1:] == ["--publish-check"]:
        tag = os.environ["RELEASE_TAG"]
        match = re.fullmatch(FORK, tag)
        if not match or was_published(match[1], fork_releases):
            raise ValueError(f"{tag} or a later fork release is already published")
        upstream_release = json.loads(run("gh", "api", f"repos/{UPSTREAM}/releases/tags/{match[1]}"))
        if upstream_release["draft"] or upstream_release["prerelease"]:
            raise ValueError(f"Upstream release {match[1]} is no longer formal")
        if official_tag_commit(match[1]) != os.environ["UPSTREAM_COMMIT"]:
            raise ValueError(f"Upstream tag {match[1]} moved after planning")
        require_higher(int(os.environ["RELEASE_VERSION_CODE"]), version_floor(fork_releases, upstream_release))
        print("Publication preflight passed.")
        return

    check_only = os.environ["CHECK_ONLY"] == "true"
    override = os.environ.get("UPSTREAM_START_TAG")
    all_upstream = releases(UPSTREAM)
    official = [release for release in all_upstream if not release["draft"] and not release["prerelease"]]
    start_tag = override or INITIAL_TAG
    start = next((release for release in official if release["tag_name"] == start_tag), None)
    if not start or not re.fullmatch(STABLE, start_tag):
        raise ValueError(f"Cannot confirm configured starting tag {start_tag} as an upstream formal release")

    pending = []
    for release in all_upstream:
        tag = release["tag_name"]
        if not eligible(release, start, bool(override)):
            print(f"Skip {tag}: pre-release, draft, or at/before the initial release cutoff.")
        elif was_published(tag, fork_releases):
            print(f"Skip {tag}: fork already published this or a later version.")
        else:
            pending.append(tag)
    pending.sort(key=version)

    if not pending and not check_only:
        print(f"No new stable upstream release after cutoff {start_tag}.")
        return
    probe = pending[0] if pending else start_tag
    if not pending:
        print(f"Dry-run probe uses {probe} even though automatic publication skips it.")
    tag, candidate, upstream_commit, code, existing = release_candidate(next(release for release in official if release["tag_name"] == probe), fork_releases)
    if check_only:
        for floor in (code, code + 1):
            try:
                require_higher(code, floor)
            except ValueError as error:
                print(f"Dry-run rejection verified: {error}")
            else:
                raise ValueError("Version guard accepted an equal or higher distribution floor")
        print("Check only: no remote tag or release created. Build workflow was not invoked.")
        return

    if os.environ.get("SIGNING_READY") != "true":
        raise ValueError("Release signing secrets and RELEASE_SIGNER_SHA256 are required before a tag can be created")
    if not existing:
        run("git", "push", "origin", f"{candidate}:refs/tags/{tag}")
    with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
        stream.write(f"release_tag={tag}\nrelease_commit={candidate}\n")
        stream.write(f"upstream_commit={upstream_commit}\nversion_code={code}\n")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, subprocess.CalledProcessError) as error:
        sys.exit(f"::error::{error}")
