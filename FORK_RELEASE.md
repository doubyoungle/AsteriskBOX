# AsteriskBOX fork releases

The fork follows official [AsteriskBOX Releases](https://github.com/Asterisk4Magisk/AsteriskBOX/releases). The initial cutoff is `v1.2.0` (versionCode `651`). The scheduled workflow skips that release, older releases, and prereleases. To use an explicit inclusive starting release, set the fork's Actions variable `UPSTREAM_START_TAG` to its exact stable tag before enabling the schedule.

**Follow Upstream Release** checks every six hours. Its default manual dispatch is check-only. The dry run uses the real release metadata and official Git tag, checks that the fork overlay applies, and exercises the versionCode guard. With no new candidate it probes the cutoff tag while retaining the automatic skip. Enable the schedule with the Actions variable `AUTO_FORK_RELEASE_ENABLED=true`.

The workflow applies the fork's changes from main to the official tagged source and prepares `vX.Y.Z-r.1`. The tag's first parent records the upstream release commit. Android uses the complete Git commit count for `versionCode`. The workflow checks that count against published APKs and the upstream APKs for this baseline. Set `DISTRIBUTED_VERSION_CODE_FLOOR` to the highest code of any APK distributed outside GitHub Releases, such as a privately shared CI build.

**Build Fork APKs** can build an unsigned validation artifact from the default branch on manual dispatch. An automatic release calls the same workflow for the generated tag. It runs unit tests and lint, then signs and verifies all five APKs, uploads the APKs and manifest to a draft, and promotes the complete draft to Latest. A retry can reuse a prepared tag if it still matches the official baseline and the fork overlay.

Configure `RELEASE_KEYSTORE_BASE64`, `RELEASE_KEYSTORE_PASSWORD`, `RELEASE_KEY_ALIAS` and, if needed, `RELEASE_KEY_PASSWORD` as repository Actions Secrets. Set the repository Actions variable `RELEASE_SIGNER_SHA256` to the expected APK signing certificate's SHA-256 fingerprint. Confirm the signer of any installation that must upgrade in place before choosing a key. Keep the signing backup outside the repository.

On a signed fork APK, use **About → App updates** to check manually. The app also checks at launch with a six-hour interval. It compares Android version codes, prefers a device ABI and falls back to universal, verifies the download and current signer, and asks the Android package installer to install the APK. API rate limits trigger use of the static manifest.
