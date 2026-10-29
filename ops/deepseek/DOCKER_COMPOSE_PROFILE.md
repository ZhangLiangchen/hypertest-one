# Docker Cloud Worker candidate (disabled)

`compose.cloud-worker.yml` is a preparation template, not the live Mac Compose configuration. Its two Cloud scheduling switches are fixed to `false`. The application also rejects the Docker profile before contacting the database while `CONTAINER_CREATE_INTENT_ENABLED` is false. Do not start real tasks or enable that gate until Docker member admission, original-key recovery and the end-to-end integration are verified.

The trusted deployment supplies a pushed, clean Git commit and a digest-qualified Python base. Build `ops/deepseek/Dockerfile.worker` with BuildKit from that exact checkout with `SOURCE_COMMIT` set to the full commit, then record the resulting immutable image ID. The image contains neither the service release manifest nor credentials. The Landlock launcher normally downloads from the official npm registry. If the exact public archive is already available in an integrity-addressed local cache, add `--secret id=landlock_archive,src=/absolute/path/to/archive` to the BuildKit build; the mount is not included in the image, and the same pinned SHA512, package, member and architecture checks apply. A supplied but invalid archive fails the build without a network fallback when that installation step runs. BuildKit does not use secret contents in cache keys; pass `--no-cache` (or otherwise invalidate that step) when the currently supplied archive itself must be revalidated. From that clean checkout, prepare the manifest with:

```sh
python3 ops/deepseek/prepare_docker_manifest.py \
  --checkout /absolute/path/to/clean/checkout \
  --commit PUSHED_FULL_SHA --remote-ref origin/BRANCH \
  --image-id sha256:FULL_IMAGE_ID \
  --destination /absolute/private/output/release.json
```

The tool requires the checked-out HEAD and fetched remote-tracking ref to equal that SHA. It checks the image revision, runs a no-network/no-credential SDK version probe, hashes the source archive and the image's venv archive, and writes a new manifest exclusively. Its manifest digest must be placed in `HYPERTEST_CLOUD_RELEASE_SHA256`; it is an operator deployment record, not a runtime rehash of the root filesystem. Preserve partial files for diagnosis instead of overwriting them.

Before starting a candidate service, a trusted initializer must prepare distinct local named volumes, without touching existing business volumes:

- A Worker-only private runtime root and a separate Attempt shared root, each owned by UID 997 with mode 0700. The Agent only mounts approved subpaths of the shared volume; it never receives the private root.
- A Worker-only credential volume holding `wrapping-key` and `deepseek-key` as UID 997 owner-only regular files. The wrapping key and key ID must match the API's existing Cloud encryption identity; establish whether that identity already exists before provisioning. Never generate a replacement for an existing identity. Keep credentials out of the repository, image, logs, Agent mounts and profile JSON.
- A release volume containing `release.json` and a completed `docker-service.json` based on the example. Both files must be root-owned regular files, without aliases, and mounted readonly at their fixed paths. The profile names the exact Compose project/service, full image ID, commit, volume names, Engine-visible socket source and complete expected Engine mount set. Do not derive expected values from the untrusted Agent or from the same inspect response being checked.

The image runs as UID 997/GID 0 because this Mac's tested Docker socket permissions require the latter; only the trusted Worker receives the socket. The Agent stays UID 997/GID 988, has no Docker socket, and does not use native Codex delegation. The Worker has a 1 GiB/0-swap/80-PID bound; the candidate reserves a separate 2 GiB/0-swap/128-PID Attempt within the aggregate 4 GiB/256-PID limit. Admission checks the Worker's own cgroup and Engine values, plus separate Engine/DB member accounting; it does not claim independent observation of the Agent cgroup.

The template attaches only to the existing `hypertest-mac_backend` network and does not change WireGuard, TLS, BFF, database or PowerContext. Supply the nonsecret Compose substitution values from reviewed deployment configuration and the database URL through the dedicated protected Worker env file. The fixed profile requires the true Engine-visible bind source, which may differ from the Mac-side socket path. Verify the entire rendered configuration and the Docker service/Attempt gate before any startup. Neither startup admission nor a successful health check proves provider authentication, framework execution, or an exchange.
