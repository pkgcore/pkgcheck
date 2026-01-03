FROM python:3-alpine
ARG PKGCHECK_VERSION

RUN apk add --no-cache "bash>=5.3" git perl xz zstd && \
    apk add --no-cache --virtual .cpanm make perl-app-cpanminus && \
    cpanm --quiet --notest Gentoo::PerlMod::Version && \
    apk del .cpanm make perl-app-cpanminus && \
    pip install --root-user-action=ignore pkgcheck==${PKGCHECK_VERSION} setuptools requests && \
    pip cache purge && \
    ln -sv /bin/bash /usr/bin/bash && \
    git config --global --add safe.directory '*'
