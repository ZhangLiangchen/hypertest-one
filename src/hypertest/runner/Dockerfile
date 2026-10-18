ARG BASE_IMAGE
FROM ${BASE_IMAGE}
ARG PROFILE_ID
ARG DEPENDENCY_LOCK_SHA256
ARG LAUNCHER_SHA256
ARG BASE_IMAGE_DIGEST
LABEL org.hypertest.environment.profile_id=$PROFILE_ID \
      org.hypertest.environment.dependency_lock_sha256=$DEPENDENCY_LOCK_SHA256 \
      org.hypertest.environment.launcher_sha256=$LAUNCHER_SHA256 \
      org.hypertest.environment.base_image_digest=$BASE_IMAGE_DIGEST
# The build script verifies the complete wheel closure before this offline step.
COPY wheels /opt/wheels
COPY requirements.txt /opt/hypertest/requirements.txt
COPY service_launcher.py /opt/hypertest/service_launcher.py
RUN python -m pip install --no-index --find-links=/opt/wheels --require-hashes --no-cache-dir -r /opt/hypertest/requirements.txt \
    && python -m pip check && rm -rf /opt/wheels
RUN mkdir -p /repo /results && chmod 1777 /results
WORKDIR /repo
