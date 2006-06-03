# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

category_feed = "cat"
package_feed = "cat/pkg"
versioned_feed = "cat/pkg-ver"

__all__ = ("package_feed, versioned_feed", "category_feed", "Feeder")

from pkgcore.restrictions import packages, util
import logging, operator


class template(object):
	feed_type = None

	def __init__(self):
		pass

	def start(self, repo):
		pass

	def finish(self, reporter):
		pass
	
	def process(self, chunk, reporter):
		raise NotImplementedError


class Feeder(object):
	def __init__(self, repo, *checks):
		self.pkg_checks = []
		self.cat_checks = []
		self.cpv_checks = []
		self.first_run = True
		for x in checks:
			self.add_check(x)
		self.repo = repo
		
	def add_check(self, check):
		feed_type = getattr(check, "feed_type")
		if feed_type == category_feed:
			self.cat_checks.append(check)
		elif feed_type == package_feed:
			self.pkg_checks.append(check)
		elif feed_type == versioned_feed:
			self.cpv_checks.append(check)
		else:
			raise TypeError("check feed_type %s unknown for %s" % (feed_type, check))
	
	@staticmethod
	def _generic_fire(attr, check_type, checks, *args):
		if not checks:
			return
		actual = []
		for check in checks:
			try:
				getattr(check, attr)(*args)
				actual.append(check)
			except SystemExit:
				raise
			except Exception, e:
				logging.error("type %s, check %s failed to running %s: %s" % (check_type, check, attr, e))
				del e
		# rebuild the checks should any have failed
		for x in xrange(len(checks)):
			checks.pop()
		checks.extend(actual)

	def fire_starts(self, *a, **kwds):
		return self._generic_fire(*(("start",) + a), **kwds)

	def fire_finishs(self, *a, **kwds):
		return self._generic_fire(*(("finish",) + a), **kwds)

	def run(self, reporter, limiter=packages.AlwaysTrue):
		enabled = {}.fromkeys(["cats", "pkgs", "vers"], False)
		for var, attr in (("cats", ["category"]), ("pkgs", ["package"]), ("vers", ["fullver", "version", "rev"])):
			enabled[var] = bool(list(util.collect_package_restrictions(limiter, attr)))

		cats = enabled.pop("cats")
		pkgs = enabled.pop("pkgs")
		vers = enabled.pop("vers")

		# take the most specific, and disable everything less
		if vers:
			cats = pkgs = False
		elif pkgs:
			vers = True
			cats = False
		elif cats:
			pkgs = vers = True
		else:
			cats = pkgs = vers = True

		if self.first_run:
			if cats:
				self.fire_starts("cat", self.cat_checks, self.repo)
			if pkgs:
				self.fire_starts("key", self.pkg_checks, self.repo)
			if vers:
				self.fire_starts("cpv", self.cpv_checks, self.repo)
		self.first_run = False
		
		# and... build 'er up.
		i = self.repo.itermatch(limiter, sorter=sorted)
		if cats and self.cpv_checks:
			i = self.trigger_cpv_checks(i, reporter)
		if pkgs and self.pkg_checks:
			i = self.trigger_pkg_checks(i, reporter)
		if vers and self.cat_checks:
			i = self.trigger_cat_checks(i, reporter)
		count = 0
		for x in i:
			count += 1

		return count
	
	def finish(self, reporter):
		self.fire_finishs("cat", self.cat_checks, reporter)
		self.fire_finishs("pkg", self.pkg_checks, reporter)
		self.fire_finishs("cpv", self.cpv_checks, reporter)
		
	@staticmethod
	def run_check(checks, payload, reporter, errmsg):
		for check in checks:
			try:
				check.feed(payload, reporter)
			except SystemExit:
				raise
			except Exception, e:
				logging.error(errmsg % (check, e))
				del e

	def _generic_trigger_checks(self, checks, attr, iterable, reporter):
		afunc = operator.attrgetter(attr)
		l = [iterable.next()]
		yield l[0]
		lattr = afunc(l[0])
		for pkg in iterable:
			if lattr != afunc(pkg):
				self.run_check(checks, l, reporter, "check %s"+" "+attr+": '"+lattr+"' threw exception %s")
				l = [pkg]
				lattr = afunc(pkg)
			else:
				l.append(pkg)
			yield pkg
		self.run_check(checks, l, reporter, "check %s"+" "+attr+": '"+lattr+"' threw exception %s")

	def trigger_cat_checks(self, *args):
		return self._generic_trigger_checks(self.cat_checks, "category", *args)
	
	def trigger_pkg_checks(self, *args):
		return self._generic_trigger_checks(self.pkg_checks, "package", *args)

	def trigger_cpv_checks(self, iterable, reporter):
		for pkg in iterable:
			self.run_check(self.cpv_checks, pkg, reporter, "check %s cpv: '"+str(pkg)+"' threw exception %s")
			yield pkg
	

class Result(object):
	
	description = None
	
	def __str__(self):
		try:
			return self.to_str()
		except NotImplementedError:
			return "result from %s" % self.__class__.__name__
	
	def to_str(self):
		raise NotImplementedError
	
	def to_xml(self):
		raise NotImplementedError


class Reporter(object):
	def __init__(self):
		self.reports = []
	
	def add_report(self, result):
#		print result.to_xml()
		print result.to_str()
#		self.reports.append(result)
