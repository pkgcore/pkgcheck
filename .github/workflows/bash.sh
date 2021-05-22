#!/bin/sh
# Download static build of recent bash release.

URL="https://github.com/robxu9/bash-static/releases/download/5.1.004-1.2.2/bash-linux-x86_64"
curl -L "$URL" > /usr/local/bin/bash
chmod +x /usr/local/bin/bash
