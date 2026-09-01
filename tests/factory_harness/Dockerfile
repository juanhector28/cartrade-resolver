ARG BASE_IMAGE=cartrade-resolver-base:local
FROM ${BASE_IMAGE}

COPY tests/factory_harness/resolver_test_patch.py /tmp/resolver_test_patch.py
RUN python /tmp/resolver_test_patch.py && rm /tmp/resolver_test_patch.py
COPY tests/factory_harness/resolver_test_patch_v12.py /tmp/resolver_test_patch_v12.py
RUN python /tmp/resolver_test_patch_v12.py && rm /tmp/resolver_test_patch_v12.py
COPY tests/factory_harness/resolver_test_patch_v13.py /tmp/resolver_test_patch_v13.py
RUN python /tmp/resolver_test_patch_v13.py && rm /tmp/resolver_test_patch_v13.py

ENV ATLAS_TEST_ENV=1 \
    ATLAS_TEST_CLOCK_PATH=/test-clock/clock.json
