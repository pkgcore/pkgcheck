# Copyright: 2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

category_feed = "cat"
package_feed = "cat/pkg"
versioned_feed = "cat/pkg-ver"

__all__ = ("package_feed, versioned_feed", "category_feed", "Feeder")

from pkgcore.restrictions import packages
import logging, operator

class template(object):
	feed_type = None

	def start(self):
		raise NotImplementedError

	def finalize(self):
		raise NotImplementedError

	def process(self, chunk):
		raise NotImplementedError

class Feeder(object):
	def __init__(self, repo, *checks):
		self.pkg_checks = []
		self.cat_checks = []
		self.cpv_checks = []
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
	def _generic_fire(check_type, checks, attr, repo=None):
		if not checks:
			return
		if repo is not None:
			args = [repo]
		else:
			args = []
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
		return self._generic_fire(*(a + ("start",)), **kwds)

	def fire_finishs(self, *a, **kwds):
		return self._generic_fire(*(a + ("finish",)), **kwds)
	
	def run(self):
		self.fire_starts("cat", self.cat_checks, repo=self.repo)
		self.fire_starts("key", self.pkg_checks, repo=self.repo)
		self.fire_starts("cpv", self.cpv_checks, repo=self.repo)
		
		# and... build 'er up.
		i = self.repo.itermatch(packages.AlwaysTrue, sorter=sorted)
		if self.cpv_checks:
			i = self.trigger_cpv_checks(i)
		if self.pkg_checks:
			i = self.trigger_pkg_checks(i)
		if self.cat_checks:
			i = self.trigger_cat_checks(i)
		count = 0
		for x in i:
			count += 1

		self.fire_finishs("cat", self.cat_checks)
		self.fire_finishs("pkg", self.pkg_checks)
		self.fire_finishs("cpv", self.cpv_checks)
		return count
		
	@staticmethod
	def run_check(checks, payload, errmsg):
		for check in checks:
			try:
				check.feed(payload)
			except SystemExit:
				raise
			except Exception, e:
				logging.error(errmsg % (check, e))
				del e

	def _generic_trigger_checks(self, checks, attr, iterable):
		afunc = operator.attrgetter(attr)
		l = [iterable.next()]
		yield l[0]
		lattr = afunc(l[0])
		for pkg in iterable:
			if lattr != afunc(pkg):
				self.run_check(checks, l, "check %s"+" "+attr+": '"+lattr+"' threw exception %s")
				l = [pkg]
				lattr = afunc(pkg)
			else:
				l.append(pkg)
			yield pkg
		self.run_check(checks, l, "check %s"+" "+attr+": '"+lattr+"' threw exception %s")

	def trigger_cat_checks(self, iterable):
		return self._generic_trigger_checks(self.cat_checks, "category", iterable)
	
	def trigger_pkg_checks(self, iterable):
		return self._generic_trigger_checks(self.pkg_checks, "package", iterable)

	def trigger_cpv_checks(self, iterable):
		for pkg in iterable:
			self.run_check(self.cpv_checks, pkg, "check %s cpv: '"+str(pkg)+"' threw exception %s")
			yield pkg
	
