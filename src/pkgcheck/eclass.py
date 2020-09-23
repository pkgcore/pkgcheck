"""Eclass specific support and addon."""

from collections import UserDict
import os
import pickle
import re

from pkgcore.ebuild.eapi import EAPI
from snakeoil import klass
from snakeoil.cli.exceptions import UserException
from snakeoil.mappings import ImmutableDict
from snakeoil.strings import pluralism

from . import base, caches
from .log import logger


# mapping between known eclass block tags and related classes
_eclass_blocks = dict()


def eclass_block(block, name, singular=False):
    """Decorator to register eclass blocks."""
    def wrapper(cls):
        cls._block = block
        cls._name = name
        _eclass_blocks[block] = (cls(), singular)
    return wrapper


class EclassDocParsingError(Exception):
    """Error when parsing eclass docs."""


def _parsing_error(exc):
    """Callback to handle parsing exceptions."""
    raise exc


class _EclassDoc:
    """Generic block for eclass docs.

    See the devmanual [#]_ for the eclass docs specification.

    .. [#] https://devmanual.gentoo.org/eclass-writing/#documenting-eclasses
    """

    # eclass doc block name
    _block = None
    # eclass doc parsed block name
    _name = None

    def __init__(self, tags):
        self.tags = tags
        # regex matching all known tags for the eclass doc block
        self._block_tags_re = re.compile(rf'^(?P<tag>{"|".join(self.tags)})(?P<value>.*)')

    def _tag_bool(self, block, tag, lineno):
        """Parse boolean tags."""
        try:
            args = next(x for x in block if x)
            raise EclassDocParsingError(
                f'{repr(tag)}, line {lineno}: tag takes no args, got {repr(args)}')
        except StopIteration:
            pass
        return True

    def _tag_inline_arg(self, block, tag, lineno):
        """Parse tags with inline argument."""
        if not block[0]:
            raise EclassDocParsingError(f'{repr(tag)}, line {lineno}: missing inline arg')
        elif len(block) > 1:
            raise EclassDocParsingError(f'{repr(tag)}, line {lineno}: non-inline arg')
        return block[0]

    # TODO: add support for @CODE blocks once doc output is added
    def _tag_multiline_args(self, block, tag, lineno):
        """Parse tags with multiline arguments."""
        if block[0]:
            raise EclassDocParsingError(f'{repr(tag)}, line {lineno}: invalid inline arg')
        if not block[1:]:
            raise EclassDocParsingError(f'{repr(tag)}, line {lineno}: missing args')
        return tuple(block[1:])

    def _tag_deprecated(self, block, tag, lineno):
        """Parse deprecated tags."""
        if not block[0]:
            raise EclassDocParsingError(f'{repr(tag)}, line {lineno}: missing replacement')

        d = {}
        # use inline argument as replacement
        d['replacement'] = None if block[0].lower() == 'none' else block[0]
        # pull following lines as additional info if they exist
        if len(block) > 1:
            d['info'] = block[1:]
        return d

    @klass.jit_attr
    def _required(self):
        """Set of required eclass doc block tags."""
        tags = set()
        for tag, (_name, required, _func) in self.tags.items():
            if required:
                tags.add(tag)
        return frozenset(tags)

    def parse(self, lines, line_ind):
        """Parse an eclass block."""
        blocks = []
        data = dict()
        # track if all required tags are defined
        missing_tags = set(self._required)

        # split eclass doc block into separate blocks by tag
        for i, line in enumerate(lines):
            m = self._block_tags_re.match(line)
            if m is not None:
                tag = m.group('tag')
                missing_tags.discard(tag)
                value = m.group('value').strip()
                blocks.append((tag, line_ind + i, [value]))
            else:
                blocks[-1][-1].append(line)

        # parse each tag block
        for tag, line_ind, block in blocks:
            name, required, func = self.tags[tag]
            try:
                data[name] = func(block, tag, line_ind)
            except EclassDocParsingError as e:
                _parsing_error(e)

        # check if any required tags are missing
        if missing_tags:
            missing_tags_str = ', '.join(map(repr, missing_tags))
            s = pluralism(missing_tags)
            _parsing_error(EclassDocParsingError(
                f'{repr(lines[0])}: missing tag{s}: {missing_tags_str}'))

        return data


@eclass_block('@ECLASS:', None, singular=True)
class _EclassBlock(_EclassDoc):
    """ECLASS doc block."""

    def __init__(self):
        tags = {
            '@ECLASS:': ('name', True, self._tag_inline_arg),
            '@VCSURL:': ('vcsurl', False, self._tag_inline_arg),
            '@BLURB:': ('blurb', True, self._tag_inline_arg),
            # TODO: add to devmanual
            '@DEPRECATED:': ('deprecated', False, self._tag_deprecated),

            '@MAINTAINER:': ('maintainers', True, self._tag_multiline_args),
            '@AUTHOR:': ('authors', False, self._tag_multiline_args),
            '@BUGREPORTS:': ('bugreports', False, self._tag_multiline_args),
            '@DESCRIPTION:': ('description', False, self._tag_multiline_args),
            '@EXAMPLE:': ('example', False, self._tag_multiline_args),

            # undocumented in devmanual
            '@SUPPORTED_EAPIS:': ('supported_eapis', False, self._supported_eapis),
        }
        super().__init__(tags)

    def _supported_eapis(self, block, tag, lineno):
        """Parse @SUPPORTED_EAPIS tag arguments."""
        eapis = set(block[0].split())
        unknown = eapis - set(EAPI.known_eapis)
        if unknown:
            s = pluralism(unknown)
            unknown_str = ' '.join(sorted(unknown))
            raise EclassDocParsingError(
                f'{repr(tag)}, line {lineno}: unknown EAPI{s}: {unknown_str}')
        return frozenset(eapis)


@eclass_block('@ECLASS-VARIABLE:', 'variables')
class _EclassVarBlock(_EclassDoc):
    """ECLASS-VARIABLE doc block."""

    def __init__(self):
        tags = {
            '@ECLASS-VARIABLE:': ('name', True, self._tag_inline_arg),
            # TODO: add to devmanual
            '@DEPRECATED:': ('deprecated', False, self._tag_deprecated),

            '@DEFAULT_UNSET': ('default_unset', False, self._tag_bool),
            '@INTERNAL': ('internal', False, self._tag_bool),
            '@REQUIRED': ('required', False, self._tag_bool),

            # undocumented in devmanual
            '@PRE_INHERIT': ('pre_inherit', False, self._tag_bool),
            '@USER_VARIABLE': ('user_variable', False, self._tag_bool),
            '@OUTPUT_VARIABLE': ('output_variable', False, self._tag_bool),

            '@DESCRIPTION:': ('description', True, self._tag_multiline_args),
        }
        super().__init__(tags)


@eclass_block('@FUNCTION:', 'functions')
class _EclassFuncBlock(_EclassDoc):
    """FUNCTION doc block."""

    def __init__(self):
        tags = {
            '@FUNCTION:': ('name', True, self._tag_inline_arg),
            '@RETURN:': ('returns', False, self._tag_inline_arg),
            # TODO: add to devmanual
            '@DEPRECATED:': ('deprecated', False, self._tag_deprecated),

            '@INTERNAL': ('internal', False, self._tag_bool),

            '@MAINTAINER:': ('maintainers', False, self._tag_multiline_args),
            '@DESCRIPTION:': ('description', False, self._tag_multiline_args),

            # TODO: The devmanual states this is required, but disabling for now since
            # many phase override functions don't document usage.
            '@USAGE:': ('usage', False, self._usage),
        }
        super().__init__(tags)

    def _usage(self, block, tag, lineno):
        """Parse @USAGE tag arguments.

        Empty usage is allowed for functions with no arguments.
        """
        return tuple(block)


@eclass_block('@VARIABLE:', 'function-variables')
class _EclassFuncVarBlock(_EclassDoc):
    """VARIABLE doc block."""

    def __init__(self):
        tags = {
            '@VARIABLE:': ('name', True, self._tag_inline_arg),
            # TODO: add to devmanual
            '@DEPRECATED:': ('deprecated', False, self._tag_deprecated),

            '@DEFAULT_UNSET': ('default_unset', False, self._tag_bool),
            '@INTERNAL': ('internal', False, self._tag_bool),
            '@REQUIRED': ('required', False, self._tag_bool),

            '@DESCRIPTION:': ('description', True, self._tag_multiline_args),
        }
        super().__init__(tags)


_eclass_blocks_re = re.compile(
    rf'^(?P<prefix>\s*#) (?P<tag>{"|".join(_eclass_blocks)})(?P<value>.*)')


class Eclass(UserDict):
    """Support parsing eclass docs for a given eclass path."""

    def __init__(self, path):
        self.path = path
        self.mtime = os.path.getmtime(self.path)
        data = self.parse(self.path)
        super().__init__(data)

    @property
    def functions(self):
        """Tuple of documented function names in the eclass."""
        return tuple(d['name'] for d in self.data.get('functions', []))

    @property
    def variables(self):
        """Tuple of documented variable names in the eclass."""
        return tuple(d['name'] for d in self.data.get('variables', []))

    @staticmethod
    def parse(path):
        """Parse eclass docs."""
        blocks = []

        with open(path) as f:
            lines = f.read().splitlines()
            line_ind = 0

            while line_ind < len(lines):
                m = _eclass_blocks_re.match(lines[line_ind])
                if m is not None:
                    # Isolate identified doc block by pulling all following
                    # lines with a matching prefix.
                    prefix = m.group('prefix')
                    tag = m.group('tag')
                    block = []
                    block_start = line_ind + 1
                    while line_ind < len(lines):
                        line = lines[line_ind]
                        if not line.startswith(prefix):
                            break
                        line = line[len(prefix) + 1:]
                        block.append(line)
                        line_ind += 1
                    blocks.append((tag, block, block_start))
                line_ind += 1

        # @ECLASS block must exist and be first in eclasses
        if not blocks:
            _parsing_error(EclassDocParsingError("'@ECLASS:' block missing"))
        elif blocks[0][0] != '@ECLASS:':
            _parsing_error(EclassDocParsingError("'@ECLASS:' block not first"))

        data = dict()
        duplicates = {k: set() for k in _eclass_blocks.keys()}

        # parse identified blocks
        for tag, block, block_start in blocks:
            obj, singular = _eclass_blocks[tag]
            block_data = obj.parse(block, block_start)
            # check if duplicate blocks exist and merge data
            if singular:
                if block_data.keys() & data.keys():
                    _parsing_error(EclassDocParsingError(
                        f"'@ECLASS:', line {block_start}: duplicate block"))
                data.update(block_data)
            else:
                name = block_data['name']
                if name in duplicates[tag]:
                    _parsing_error(EclassDocParsingError(
                        f'{repr(block[0])}, line {block_start}: duplicate block'))
                duplicates[tag].add(name)
                data.setdefault(obj._name, []).append(block_data)

        return data


class _EclassCache(UserDict, caches.Cache):
    """Cache that encapsulates eclass data."""

    def __init__(self, data):
        super().__init__(data)
        self._cache = EclassAddon.cache


class EclassAddon(base.Addon, caches.CachedAddon):
    """Eclass support for various checks."""

    # cache registry
    cache = caches.CacheData(type='eclass', file='eclass.pickle', version=1)

    def __init__(self, *args):
        super().__init__(*args)
        self.eclasses = {}

    @klass.jit_attr
    def deprecated(self):
        """Mapping of deprecated eclasses to their replacements (if any)."""
        return ImmutableDict({
            k: v['deprecated']['replacement']
            for k, v in self.eclasses.items() if 'deprecated' in v
        })

    def update_cache(self, output_lock, force=False):
        """Update related cache and push updates to disk."""
        try:
            # running from scan subcommand
            repos = self.options.target_repo.trees
        except AttributeError:
            # running from cache subcommand
            repos = self.options.domain.ebuild_repos

        if self.options.cache['eclass']:
            for repo in repos:
                if repo.repo_id == 'gentoo':
                    cache_file = self.cache_file(repo)
                    cache_eclasses = False
                    eclasses = {}

                    if not force:
                        # try loading cached eclass data
                        try:
                            with open(cache_file, 'rb') as f:
                                eclasses = pickle.load(f)
                            if eclasses.version != self.cache.version:
                                logger.debug('forcing eclass repo cache regen due to outdated version')
                                os.remove(cache_file)
                        except FileNotFoundError:
                            pass
                        except (AttributeError, EOFError, ImportError, IndexError) as e:
                            logger.debug('forcing eclass cache regen: %s', e)
                            os.remove(cache_file)

                    # check for eclass removals
                    for name, eclass in list(eclasses.items()):
                        if not os.path.exists(eclass.path):
                            del eclasses[name]
                            cache_eclasses = True

                    # check for eclass additions and updates
                    for name, eclass in sorted(repo.eclass_cache.eclasses.items()):
                        try:
                            if os.path.getmtime(eclass.path) != eclasses[name].mtime:
                                raise KeyError
                        except (KeyError, AttributeError):
                            try:
                                eclasses[name] = Eclass(eclass.path)
                                cache_eclasses = True
                            except (IOError, EclassDocParsingError):
                                continue

                    # push eclasses to disk if any changes were found
                    if cache_eclasses:
                        try:
                            os.makedirs(os.path.dirname(cache_file), exist_ok=True)
                            with open(cache_file, 'wb+') as f:
                                pickle.dump(_EclassCache(eclasses), f)
                        except IOError as e:
                            msg = f'failed dumping eclasses: {cache_file!r}: {e.strerror}'
                            raise UserException(msg)

                    self.eclasses = eclasses
