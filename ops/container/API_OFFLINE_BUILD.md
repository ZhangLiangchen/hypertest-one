# Local API offline build

`build_api_offline.py` builds the API using the already deployed, fixed
`hypertest-mac-api:903c9bd` image for its runtime dependencies and a fixed
Worker image for an isolated wheel-build stage. Both images are checked by
complete image ID and revision. The Worker image must already have been built
from the same pushed Git commit and tagged locally; it supplies no SDK or
model dependencies to the resulting API.

The script requires a clean checkout at the pushed commit, a verified wheelhouse
from `ops/deepseek/stage_offline_build_wheels.py`, and unchanged API dependency
declarations and packaged assets relative to the existing API image. It copies
the pushed commit's migration scripts and installs the newly built project wheel without
network or dependency resolution, and compares the old and new third-party
package lists. It returns an immutable image ID; it neither changes Compose nor
starts the API.

```sh
python3 ops/container/build_api_offline.py \
  --checkout /absolute/path/to/clean/checkout \
  --commit PUSHED_FULL_SHA --remote-ref origin/BRANCH \
  --wheelhouse /absolute/path/to/verified/wheelhouse \
  --worker-image-id sha256:FULL_IMAGE_ID \
  --worker-image-tag hypertest-mac-cloud-worker:FIXED_TAG
```

Apply any new migrations separately using the normal maintenance flow. If the
dependency declarations or packaged assets have changed, use the normal API build
instead. The build verifies reuse of the existing image's
dependencies; it does not retroactively authenticate their installation.
