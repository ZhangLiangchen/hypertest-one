FROM python:3.12-slim
# scripts/build-runner-image.sh downloads verified wheels into the build context.
COPY wheels /opt/wheels
RUN python -m pip install --no-index --find-links=/opt/wheels --no-cache-dir 'pytest==8.3.5' && rm -rf /opt/wheels
RUN mkdir -p /repo /results && chmod 1777 /results
WORKDIR /repo
