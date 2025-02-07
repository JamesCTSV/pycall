"""A simple wrapper for Asterisk call files."""

from __future__ import with_statement
from shutil import move
from time import mktime
from pwd import getpwnam
from tempfile import mkstemp
from os import chown, error, utime
import os, paramiko

from path import Path

from .call import Call
from .actions import Action, Context
from .errors import ParamikoError, InvalidTimeError, NoSpoolPermissionError, NoUserError, \
    NoUserPermissionError, ValidationError


class CallFile(object):
    """Stores and manipulates Asterisk call files."""

    #: The default spooling directory (should be OK for most systems).
    DEFAULT_SPOOL_DIR = '/var/spool/asterisk/outgoing'

    def __init__(self, call, action, archive=None, filename=None, tempdir=None,
                 user=None, spool_dir=None):
        """Create a new `CallFile` obeject.

        :param obj call: A `pycall.Call` instance.
        :param obj action: Either a `pycall.actions.Application` instance
            or a `pycall.actions.Context` instance.
        :param bool archive: Should Asterisk archive the call file?
        :param str filename: Filename of the call file.
        :param str tempdir: Temporary directory to store the call file before
            spooling.
        :param str user: Username to spool the call file as.
        :param str spool_dir: Directory to spool the call file to.
        :rtype: `CallFile` object.
        """
        self.call = call
        self.action = action
        self.archive = archive
        self.user = user
        self.spool_dir = spool_dir or self.DEFAULT_SPOOL_DIR

        if filename and tempdir:
            self.filename = Path(filename)
            self.tempdir = Path(tempdir)
        else:
            tup = mkstemp(suffix='.call')
            f = Path(tup[1])
            self.filename = f.name
            self.tempdir = f.parent
            os.close(tup[0])

    def __str__(self):
        """Render this call file object for developers.

        :returns: String representation of this object.
        :rtype: String.
        """
        return 'CallFile-> archive: %s, user: %s, spool_dir: %s' % (
            self.archive, self.user, self.spool_dir)

    def is_valid(self):
        """Check to see if all attributes are valid.

        :returns: True if all attributes are valid, False otherwise.
        :rtype: Boolean.
        """
        if not isinstance(self.call, Call):
            return False

        if not (isinstance(self.action, Action) or
                isinstance(self.action, Context)):
            return False

        if self.spool_dir and not Path(self.spool_dir).abspath().isdir():
            return False

        if not self.call.is_valid():
            return False

        return True

    def buildfile(self):
        """Build a call file in memory.

        :raises: `ValidationError` if this call file can not be validated.
        :returns: A list of call file directives as they will be written to the
            disk.
        :rtype: List of strings.
        """
        if not self.is_valid():
            raise ValidationError

        cf = []
        cf += self.call.render()
        cf += self.action.render()

        if self.archive:
            cf.append('Archive: yes')

        return cf

    @property
    def contents(self):
        """Get the contents of this call file.

        :returns: Call file contents.
        :rtype: String.
        """
        return '\n'.join(self.buildfile())

    def writefile(self):
        """Write a temporary call file to disk."""
        with open(Path(self.tempdir) / Path(self.filename), 'w') as f:
            f.write(self.contents)

    def spool(self, time=None):
        """Spool the call file with Asterisk.

        This will move the call file to the Asterisk spooling directory. If
        the `time` attribute is specified, then the call file will be spooled
        at the specified time instead of immediately.

        :param datetime time: The date and time to spool this call file (eg:
            Asterisk will run this call file at the specified time).
        """
        self.writefile()

        if self.user:
            try:
                pwd = getpwnam(self.user)
                uid = pwd[2]
                gid = pwd[3]

                try:
                    chown(Path(self.tempdir) / Path(self.filename), uid, gid)
                except error:
                    raise NoUserPermissionError
            except KeyError:
                raise NoUserError

        if time:
            try:
                time = mktime(time.timetuple())
                utime(Path(self.tempdir) / Path(self.filename), (time, time))
            except (error, AttributeError, OverflowError, ValueError):
                raise InvalidTimeError

        try:
            move(Path(self.tempdir) / Path(self.filename),
                 Path(self.spool_dir) / Path(self.filename))
        except IOError:
            raise NoSpoolPermissionError

    def remote_spool(self, ipaddr, usr, uid, gid, passwd = None, pkeypath = None):
        self.writefile()

        if self.user:
            try:
                pwd = getpwnam(self.user)
                uid = pwd[2]
                gid = pwd[3]

                try:
                    chown(Path(self.tempdir) / Path(self.filename), uid, gid)
                except error:
                    raise NoUserPermissionError
            except KeyError:
                raise NoUserError
        if passwd:
            try:
                c = paramiko.SSHClient()
                c.load_system_host_keys()
                c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                t = paramiko.Transport(ipaddr, 22)
                t.connect(username=usr, password=passwd)
                sftp = paramiko.SFTPClient.from_transport(t)
                sftp.put(Path(self.tempdir) / Path(self.filename), Path(self.tempdir) / Path(self.filename))
                sftp.chown(Path(self.tempdir) / Path(self.filename), uid, gid)
                sftp.rename(Path(self.tempdir) / Path(self.filename), Path(self.spool_dir) / Path(self.filename))
                sftp.close()
                t.close()
                c.close()
            except paramiko.SSHException:
                raise ParamikoError
        if pkeypath:
            try:
                pkey = paramiko.RSAKey.from_private_key_file(filename=pkeypath)
                c = paramiko.SSHClient()
                c.load_system_host_keys()
                t = paramiko.Transport(ipaddr, 22)
                t.connect(username=usr, pkey=pkey)
                sftp = paramiko.SFTPClient.from_transport(t)
                sftp.put(Path(self.tempdir) / Path(self.filename), Path(self.tempdir) / Path(self.filename))
                sftp.chown(Path(self.tempdir) / Path(self.filename), uid, gid)
                sftp.rename(Path(self.tempdir) / Path(self.filename), Path(self.spool_dir) / Path(self.filename))
                sftp.close()
                t.close()
                c.close()
            except (paramiko.SSHException, IOError) as e:
                raise ParamikoError
