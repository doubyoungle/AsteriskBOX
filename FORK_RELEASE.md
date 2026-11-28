# AsteriskBOX fork releases

The fork follows the release GitHub marks as Latest in [AsteriskBOX Releases](https://github.com/Asterisk4Magisk/AsteriskBOX/releases). The first eligible stable version is `v1.2.1` and the historical versionCode floor is `651`. Set the repository Actions variable `UPSTREAM_START_TAG` to an official stable tag to override the minimum eligible version.

**Follow Upstream Release** checks every six hours when `AUTO_FORK_RELEASE_ENABLED=true`. Manual dispatch defaults to check-only. It uses a read-only token to validate the same pending candidate without creating a remote tag or invoking the build. If Latest is already covered by a fork release or is below the minimum version, the workflow skips it.

The workflow applies the fork's changes from `main` to the verified upstream tag and prepares `vX.Y.Z-r.1`. The release commit records the upstream source as its first parent and the fork source as its second parent. It uses Git commit count as Android versionCode, which must exceed the upstream APK versionCode from the release notes and every distributed fork release versionCode verified against its update manifest. Set `DISTRIBUTED_VERSION_CODE_FLOOR` to the highest code distributed outside GitHub Releases, including signed test builds when applicable. On retry, the workflow reproduces the existing tag's tree from its recorded parents and requires the fork parent to remain in the current fork history.

**Build Fork APKs** can build an unsigned validation artifact from the default branch on manual dispatch. An automatic release calls the same workflow for the generated tag. It runs unit tests and lint, then signs and verifies all five APKs, uploads the APKs and manifest to a draft, and promotes the complete draft to Latest.

Configure `RELEASE_KEYSTORE_BASE64`, `RELEASE_KEYSTORE_PASSWORD`, `RELEASE_KEY_ALIAS` and, if needed, `RELEASE_KEY_PASSWORD` as repository Actions Secrets. Set the repository Actions variable `RELEASE_SIGNER_SHA256` to the expected APK signing certificate's SHA-256 fingerprint. Confirm the signer of any installation that must upgrade in place before choosing a key. Keep the signing backup outside the repository.

On a signed fork APK, use **About → App updates** to check manually. The app also checks at launch with a six-hour interval. It compares Android version codes, prefers a device ABI and falls back to universal, verifies the download and current signer, and asks the Android package installer to install the APK. API rate limits trigger use of the static manifest.
