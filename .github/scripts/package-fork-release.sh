#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0
set -euo pipefail

fail() { echo "::error::$*" >&2; exit 1; }
: "${RELEASE_KEYSTORE_BASE64:?Missing RELEASE_KEYSTORE_BASE64}"
: "${RELEASE_KEYSTORE_PASSWORD:?Missing RELEASE_KEYSTORE_PASSWORD}"
: "${RELEASE_KEY_ALIAS:?Missing RELEASE_KEY_ALIAS}"
export RELEASE_KEY_PASSWORD="${RELEASE_KEY_PASSWORD:-$RELEASE_KEYSTORE_PASSWORD}"

signer="${RELEASE_SIGNER_SHA256//:/}"
signer="${signer,,}"
[[ "$signer" =~ ^[0-9a-f]{64}$ ]] || fail "RELEASE_SIGNER_SHA256 must be the APK signing certificate's SHA-256 fingerprint."

tools="$ANDROID_HOME/build-tools/$BUILD_TOOLS_VERSION"
version="${RELEASE_TAG#v}"
umask 077
work="$(mktemp -d)"
trap 'rm -rf -- "$work"' EXIT
printf '%s' "$RELEASE_KEYSTORE_BASE64" | base64 --decode > "$work/release.keystore"
unset RELEASE_KEYSTORE_BASE64
mkdir -p release-artifacts

shopt -s nullglob
for apk in build-apks/*.apk; do
  badging="$("$tools/aapt2" dump badging "$apk")"
  identity="$(sed -n "s/^package: name='\([^']*\)' versionCode='\([^']*\)' versionName='\([^']*\)'.*/\1 \2 \3/p" <<< "$badging")"
  [[ "$identity" == "org.asterisk.zcc.abox $RELEASE_VERSION_CODE $version" ]] ||
    fail "Unexpected package or version in ${apk##*/}: $identity"
  native_abis="$(sed -n "s/^native-code: //p" <<< "$badging" | tr -d "'" | xargs -n1 | LC_ALL=C sort | xargs)"
  case "$native_abis" in
    arm64-v8a|armeabi-v7a|x86|x86_64) abi="$native_abis" ;;
    'arm64-v8a armeabi-v7a x86 x86_64') abi=universal ;;
    *) fail "Unexpected native ABIs in ${apk##*/}: $native_abis" ;;
  esac
  output="release-artifacts/AsteriskBOX_${version}-$RELEASE_VERSION_CODE-$abi.apk"
  [[ ! -e "$output" ]] || fail "Duplicate $abi APK"
  "$tools/zipalign" -P 16 -f 4 "$apk" "$work/aligned.apk"
  "$tools/apksigner" sign --ks "$work/release.keystore" --ks-key-alias "$RELEASE_KEY_ALIAS" \
    --ks-pass env:RELEASE_KEYSTORE_PASSWORD --key-pass env:RELEASE_KEY_PASSWORD \
    --out "$output" "$work/aligned.apk"
  "$tools/zipalign" -c -P 16 4 "$output"
  certs="$("$tools/apksigner" verify --print-certs "$output" |
    sed -n 's/^Signer #[0-9]* certificate SHA-256 digest: //p')"
  [[ "${certs,,}" == "$signer" ]] || fail "Signing certificate mismatch for $abi"
  echo "Verified $abi APK and pinned signer $signer."
done
for abi in arm64-v8a armeabi-v7a x86 x86_64 universal; do
  [[ -s "release-artifacts/AsteriskBOX_${version}-$RELEASE_VERSION_CODE-$abi.apk" ]] || fail "Missing $abi APK"
done
rm -f release-artifacts/*.idsig

python3 - "$signer" <<'PY'
import hashlib
import json
import os
import sys
from pathlib import Path

directory = Path("release-artifacts")
tag = os.environ["RELEASE_TAG"]
base = f'https://github.com/{os.environ["GITHUB_REPOSITORY"]}/releases/download/{tag}'
assets = []
for apk in sorted(directory.glob("*.apk")):
    with apk.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    assets.append({
        "name": apk.name,
        "size": apk.stat().st_size,
        "digest": f"sha256:{digest}",
        "browser_download_url": f"{base}/{apk.name}",
    })
manifest = {
    "tag_name": tag,
    "versionCode": int(os.environ["RELEASE_VERSION_CODE"]),
    "signerSha256": sys.argv[1],
    "assets": assets,
}
(directory / "update-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
PY
