#!/usr/bin/env bash
# Output the current list of Gentoo CI keyword errors.
# Requires bash, curl, and jq installed.

keywords=$(curl -s https://raw.githubusercontent.com/mgorny/pkgcheck2html/master/pkgcheck2html.conf.json | jq -r 'to_entries | .[] | select(.value == "err") | .key' | sort)
errors=$(printf '%s,' ${keywords[@]})
echo ${errors%,}
