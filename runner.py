#!/usr/bin/python
# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2


from pkgcore.config import load_config
from pkgcore.util.modules import load_module, FailedImport
import sys, os, logging, time, signal

def exithandler(signum,frame):
	signal.signal(signal.SIGINT, signal.SIG_IGN)
	signal.signal(signal.SIGTERM, signal.SIG_IGN)
	print "caught signal %i, shutting down" % signum
	sys.exit(1)

if __name__ == "__main__":
	if len(sys.argv) != 3:
		print "need the location to dump the reports, and the arg of the repo to scan"
		sys.exit(1)
	location = os.path.abspath(sys.argv[1])
	repo_name = sys.argv[2]
                    
	signal.signal(signal.SIGCHLD, signal.SIG_DFL)
	signal.signal(signal.SIGINT, exithandler)
	signal.signal(signal.SIGTERM, exithandler)
	signal.signal(signal.SIGPIPE, signal.SIG_DFL)
	
	conf = load_config()
	repo = conf.repo[repo_name]
	import reports
	import reports.base
	runner = reports.base.Feeder(repo)
	reporter = reports.base.Reporter()
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
				try:
					runner.add_check(obj(location))
				except SystemExit:
					raise
				except Exception, e:
					logging.error("test %s failed to be added: %s" % (obj, e))
					del e
					continue

	start_time = time.time()
	print "checks: %i cat, %i pkg, %i version" % (len(runner.cat_checks), \
		len(runner.pkg_checks), len(runner.cpv_checks))
	nodes = 0
	if runner.cat_checks or runner.pkg_checks or runner.cpv_checks:
		nodes = runner.run(reporter)
	elapsed = time.time() - start_time
	minutes = int(elapsed)/60
	seconds = elapsed - (minutes * 60)
	print "processed %i pkgs: %im%.2fs" % (nodes, minutes, seconds)
