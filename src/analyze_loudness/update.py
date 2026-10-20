"""Auto-update identity of analyze-loudness (the client is analyze_common.update)."""

from analyze_common.update import UpdateConfig

from analyze_loudness import __version__

# Raw Ed25519 public key (base64).  Its private half is the UPDATE_SIGNING_KEY
# secret that .github/workflows/release.yaml signs latest.json with.
PUBLIC_KEY = "0g1y/bMsAE+KuuDkQBC9XV/HvSS77KpIDaZ9E/8YPII="

UPDATE_CONFIG = UpdateConfig(
    product="analyze-loudness",
    repo="semnil/analyze-loudness",
    current_version=__version__,
    public_key=PUBLIC_KEY,
    temp_prefix="loudness_update_",
    # Held by the running app; build.py hands it to installer.iss as MyAppMutex.
    mutex_name="com.semnil.loudness-analyzer",
)
