#!/bin/sh
# Mangle the manylinux docker image to successfully build and test wheels.

set -e

# install git
if type -P apk; then
    apk add --no-cache git bash
else
    apt-get update
    apt-get install -y git
fi

# download static build of recent bash release
URL="https://github.com/robxu9/bash-static/releases/download/5.1.008-1.2.2/bash-linux-x86_64"
curl -L "$URL" > /usr/local/bin/bash
chmod +x /usr/local/bin/bash
