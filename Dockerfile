FROM python:3-alpine
ARG PKGCHECK_VERSION

RUN apk add --no-cache "bash>=5.3" git perl xz zstd && \
    apk add --no-cache --virtual .cpanm make perl-app-cpanminus && \
    cpanm --quiet --notest Gentoo::PerlMod::Version && \
    apk del .cpanm make perl-app-cpanminus && \
    pip install --root-user-action=ignore pkgcheck==${PKGCHECK_VERSION} setuptools requests && \
    # TODO: drop once py-tree-sitter releases past 0.26.0, which segfaults
    apk add --no-cache --virtual .tree-sitter build-base && \
    pip install --root-user-action=ignore --force-reinstall --no-deps \
        "tree-sitter @ git+https://github.com/tree-sitter/py-tree-sitter.git@2e556e540dd4ccce0e24c92d4413ef9ac85284a5" && \
    apk del .tree-sitter && \
    pip cache purge && \
    ln -sv /bin/bash /usr/bin/bash && \
    git config --global --add safe.directory '*'
