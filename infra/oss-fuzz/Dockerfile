# Copy to google/oss-fuzz/projects/provide-telemetry/Dockerfile
# Copyright 2026 provide.io llc
#
# Licensed under the Apache License, Version 2.0

FROM gcr.io/oss-fuzz-base/base-builder-go
RUN git clone --depth 1 https://github.com/provide-io/provide-telemetry.git $SRC/provide-telemetry
WORKDIR $SRC/provide-telemetry
COPY build.sh $SRC/
