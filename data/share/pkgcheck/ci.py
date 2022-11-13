#!/usr/bin/env python3

import json
import urllib.request

JSON_URL = 'https://raw.githubusercontent.com/mgorny/pkgcheck2html/master/pkgcheck2html.conf.json'

with urllib.request.urlopen(JSON_URL) as f:
    ci_data = json.loads(f.read())

with open('pkgcheck.conf', 'w') as f:
    f.write('[CHECKSETS]\nGentooCI =\n')
    for k, v in sorted(ci_data.items()):
        if v == 'err':
            f.write(f'  {k}\n')
