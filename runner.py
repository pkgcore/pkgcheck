#!/usr/bin/python
# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

from pkgcore.config import load_config
from pkgcore.util.modules import load_module, FailedImport
from pkgcore.util.commandline import generate_restriction
from pkgcore.util.lists import stable_unique
from pkgcore.restrictions import packages
import sys, os, logging, time, signal

def exithandler(signum,frame):
	signal.signal(signal.SIGINT, signal.SIG_IGN)
	signal.signal(signal.SIGTERM, signal.SIG_IGN)
	print "caught signal %i, shutting down" % signum
	sys.exit(1)

if __name__ == "__main__":
	if len(sys.argv) < 2:
		print "need the arg of the repo to scan"
		sys.exit(1)
	repo_name = sys.argv[1]
	if len(sys.argv) > 2:
		limiters = stable_unique(map(generate_restriction, sys.argv[2:]))
	else:
		limiters = [packages.AlwaysTrue]
                    
	signal.signal(signal.SIGCHLD, signal.SIG_DFL)
	signal.signal(signal.SIGINT, exithandler)
	signal.signal(signal.SIGTERM, exithandler)
	signal.signal(signal.SIGPIPE, signal.SIG_DFL)
	
	conf = load_config()
	repo = conf.repo[repo_name]
	import reports
	import reports.base
	reporter = reports.base.Reporter()
	runner = reports.base.Feeder(repo)
	checks = []
	for loc in map(str, reports.__path__):
		for mod in [x for x in os.listdir(loc) if x.endswith(".py")]:
			try:
				module = load_module("reports.%s" % mod[:-3])
			except FailedImport:
				continue
			for name in dir(module):
				if not "report" in name.lower():
					continue
				obj = getattr(module, name)
				if not getattr(obj, "feed_type", False):
					continue
				checks.append(obj)
				try:
					runner.add_check(obj())
				except SystemExit:
					raise
				except Exception, e:
					logging.error("test %s failed to be added: %s" % (obj, e))
					del e
					continue
	start_time = time.time()
	nodes = 0
	print "checks: %i cat, %i pkg, %i version" % (len(runner.cat_checks), \
		len(runner.pkg_checks), len(runner.cpv_checks))
	if not (runner.cat_checks or runner.pkg_checks or runner.cpv_checks):
		print "no tests"
		sys.exit(1)
	for filterer in limiters:
		nodes += runner.run(reporter, filterer)
	runner.finish(reporter)
	elapsed = time.time() - start_time
	minutes = int(elapsed)/60
	seconds = elapsed - (minutes * 60)
	print "processed %i pkgs: %im%.2fs" % (nodes, minutes, seconds)
