#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0
set -euo pipefail

fail() { echo "::error::$*" >&2; exit 1; }
preflight() {
  python3 .github/scripts/follow-upstream-release.py --publish-check
  remote="$(git ls-remote origin "refs/tags/$RELEASE_TAG" | cut -f1)"
  [[ "$remote" == "$RELEASE_COMMIT" ]] || fail "Fork release tag no longer points to the tested commit."
}
preflight

tag="$RELEASE_TAG"
signer="$(jq -er .signerSha256 release-artifacts/update-manifest.json)"
published="$(gh api --paginate --slurp "repos/$GITHUB_REPOSITORY/releases?per_page=100")"
prior_tags="$(jq -r '.[][] | select(.draft == false and any(.assets[]; .name | endswith(".apk"))) | .tag_name' <<< "$published")"
while IFS= read -r prior; do
  [[ -n "$prior" ]] || continue
  prior_signer="$(gh release download "$prior" --pattern update-manifest.json --output - | jq -er .signerSha256)" ||
    fail "Cannot confirm the signer of previously distributed APKs in $prior."
  [[ "$prior_signer" == "$signer" ]] || fail "Signer differs from previously distributed APKs in $prior."
done <<< "$prior_tags"

existing="$(jq -c --arg tag "$tag" 'first(.[][] | select(.tag_name == $tag)) // empty' <<< "$published")"
if [[ -z "$existing" ]]; then
  gh release create "$tag" --verify-tag --draft --title "AsteriskBOX ${tag#v}" \
    --notes "Based on Asterisk4Magisk/AsteriskBOX ${tag%-r.1}. Android versionCode: $RELEASE_VERSION_CODE."
else
  jq -e '.draft == true' <<< "$existing" >/dev/null || fail "Release $tag is already published."
fi

gh release upload "$tag" release-artifacts/*.apk release-artifacts/update-manifest.json --clobber
gh release view "$tag" --json isDraft,assets > "$RUNNER_TEMP/fork-draft.json"
python3 - "$RUNNER_TEMP/fork-draft.json" <<'PY'
import json
import sys
from pathlib import Path

draft = json.loads(Path(sys.argv[1]).read_text())
expected = {path.name: path.stat().st_size for path in Path("release-artifacts").iterdir()}
uploaded = {asset["name"]: asset["size"] for asset in draft["assets"] if asset["state"] == "uploaded"}
if not draft["isDraft"] or len(draft["assets"]) != len(expected) or uploaded != expected:
    sys.exit("::error::The draft does not contain exactly the five verified APKs and the manifest.")
PY
preflight
gh release edit "$tag" --draft=false --latest
