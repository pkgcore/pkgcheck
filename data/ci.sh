#!/usr/bin/env bash
# Output the current list of Gentoo CI keyword errors.
# Requires bash, curl, and jq installed.

# pull latest CI keyword errors
keywords=$(curl -s https://raw.githubusercontent.com/mgorny/pkgcheck2html/master/pkgcheck2html.conf.json | jq -r 'to_entries | .[] | select(.value == "err") | .key' | sort)

# replace checkset in bundled config
cat << EOF > pkgcheck.conf
[CHECKSETS]
GentooCI =$(printf '\n  %s' ${keywords[@]})
EOF
