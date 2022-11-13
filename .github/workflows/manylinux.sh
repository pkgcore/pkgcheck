#!/bin/sh
# Mangle the manylinux docker image to successfully build and test wheels.

set -ex

# install git
if command -v apk; then
    apk add --no-cache git bash py3-lxml
elif command -v yum; then
    yum update -y
    yum install -y libxslt-devel libxml2-devel python-devel
else
    apt-get update
    apt-get install -y git libxml2-dev libxslt-dev python-dev
fi

# download static build of recent bash release
URL="https://github.com/robxu9/bash-static/releases/download/5.1.016-1.2.3/bash-linux-${1:-x86_64}"
curl -L "$URL" > /usr/local/bin/bash
chmod +x /usr/local/bin/bash
