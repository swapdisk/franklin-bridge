"""The execution layer: the single place that performs state-changing actions.

Every mutation (running a command, creating a directory, writing or copying a
file) goes through an Executor. With ``dry_run=True`` mutations are logged but not
performed, which is what lets the later destructive phases be previewed safely.
Read-only helpers (``exists``, ``islink``) always reflect the real system.
"""
import os
import shutil
import subprocess


class Executor(object):
    def __init__(self, dry_run=False, log=None):
        self.dry_run = dry_run
        self._log = log if log is not None else _default_log

    def log(self, msg):
        self._log(msg)

    def run(self, argv, mutates=True, check=True, capture_to=None):
        """Run a command.

        mutates:     if True and dry_run, the command is skipped (just logged).
        capture_to:  if set, write the command's stdout to this file path.
        """
        argv = list(argv)
        desc = " ".join(argv)
        if self.dry_run and mutates:
            self.log("[dry-run] would run: %s" % desc)
            return 0
        self.log("+ %s" % desc)
        if capture_to is not None:
            out = subprocess.check_output(argv, stderr=subprocess.STDOUT)
            with open(capture_to, "wb") as fh:
                fh.write(out)
            return 0
        if check:
            subprocess.check_call(argv)
            return 0
        return subprocess.call(argv)

    def makedirs(self, path):
        if self.dry_run:
            self.log("[dry-run] would create directory: %s" % path)
            return
        self.log("+ mkdir -p %s" % path)
        os.makedirs(path, exist_ok=True)

    def write_text(self, path, text):
        if self.dry_run:
            self.log("[dry-run] would write file: %s (%d bytes)" % (path, len(text)))
            return
        self.log("+ write %s" % path)
        with open(path, "w") as fh:
            fh.write(text)

    def copy(self, src, dst):
        """Copy a file's contents (following symlinks) preserving metadata."""
        if self.dry_run:
            self.log("[dry-run] would copy: %s -> %s" % (src, dst))
            return
        self.log("+ cp %s %s" % (src, dst))
        shutil.copy2(src, dst)

    def capture(self, argv, check=True, default=""):
        """Run a read-only command and return its stdout (always executes).

        With check=False, a missing binary or nonzero exit returns `default`
        instead of raising (e.g. blkid exits nonzero on a device with no fs).
        """
        argv = list(argv)
        self.log("+ %s" % " ".join(argv))
        try:
            out = subprocess.check_output(argv, stderr=subprocess.STDOUT)
        except (subprocess.CalledProcessError, OSError):
            if check:
                raise
            return default
        return out.decode("utf-8", "replace")

    def append_text(self, path, text):
        if self.dry_run:
            self.log("[dry-run] would append to %s: %r" % (path, text))
            return
        self.log("+ append %s" % path)
        with open(path, "a") as fh:
            fh.write(text)

    @staticmethod
    def read_text(path):
        try:
            with open(path, "r") as fh:
                return fh.read()
        except OSError:
            return ""

    @staticmethod
    def exists(path):
        return os.path.exists(path)

    @staticmethod
    def islink(path):
        return os.path.islink(path)

    @staticmethod
    def ismount(path):
        return os.path.ismount(path)

    @staticmethod
    def listdir(path):
        try:
            return os.listdir(path)
        except OSError:
            return []


def _default_log(msg):
    print(msg)
