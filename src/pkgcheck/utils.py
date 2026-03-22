"""Various miscellaneous utility functions."""

# based on https://github.com/audreyr/binaryornot
#
# Copyright (c) 2013, Audrey Roy
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# * Redistributions of source code must retain the above copyright notice, this
#   list of conditions and the following disclaimer.
#
# * Redistributions in binary form must reproduce the above copyright notice,
#   this list of conditions and the following disclaimer in the documentation
#   and/or other materials provided with the distribution.
#
# * Neither the name of BinaryOrNot nor the names of its contributors may be used
#   to endorse or promote products derived from this software without specific
#   prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

_control_chars = b"\n\r\t\f\b"
_printable_ascii = _control_chars + bytes(range(32, 127))
_printable_high_ascii = bytes(range(127, 256))


def is_binary(path, blocksize=1024):
    """Check if a given file is binary or not.

    :param path: Path to a file to check.
    :param blocksize: Amount of bytes to read for determination.
    :returns: True if appears to be a binary, otherwise False.
    """
    try:
        with open(path, "rb") as f:
            byte_str = f.read(blocksize)
    except IOError:
        return False

    # empty files are considered text
    if not byte_str:
        return False

    try:
        byte_str.decode()
        return False
    except UnicodeDecodeError:
        # Delay import to hide during wheel/sdist builds that iterate over and
        # import most modules to generate check/keyword/reporter lists.
        import charset_normalizer

        return charset_normalizer.is_binary(byte_str)
