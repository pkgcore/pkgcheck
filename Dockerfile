FROM python:3-alpine
ARG PKGCHECK_VERSION

RUN apk add --no-cache "bash>=5.3" git perl xz zstd && \
    apk add --no-cache --virtual .build build-base perl-app-cpanminus && \
    cpanm --quiet --notest Gentoo::PerlMod::Version && \
    pip install --root-user-action=ignore pkgcheck==${PKGCHECK_VERSION} setuptools requests && \
    apk del .build && \
    pip cache purge && \
    ln -sv /bin/bash /usr/bin/bash && \
    git config --global --add safe.directory '*'
