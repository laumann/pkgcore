__all__ = ("tar_syncer",)

import atexit
from functools import partial
import os
import subprocess
import shutil
import tempfile
import uuid

from pkgcore.sync import base
from pkgcore.sync.http import http_syncer


class tar_syncer(http_syncer):

    supported_uris = (
        ('tar+http://', 5),
        ('tar+https://', 5),
    )

    # TODO: support more of the less used file extensions
    supported_protocols = ('http://', 'https://')
    supported_exts = ('.tar.gz', '.tar.bz2', '.tar.xz')

    @classmethod
    def parse_uri(cls, raw_uri):
        if raw_uri.startswith(("tar+http://", "tar+https://")):
            raw_uri = raw_uri[4:]
        if raw_uri.startswith(cls.supported_protocols) and raw_uri.endswith(cls.supported_exts):
            return raw_uri
        else:
            raise base.UriError(
                raw_uri, "unsupported compression format for tarball archive")
        raise base.UriError(raw_uri, "unsupported URI")

    def _sync(self, *args, **kwargs):
        ret = super()._sync(*args, **kwargs)
        # TODO: verify image checksum and gpg signature
        return ret

    def _pre_download(self):
        # create temp file for downloading
        temp = tempfile.NamedTemporaryFile()
        tarball = temp.name
        # make sure temp file is deleted on exit
        atexit.register(partial(temp.close))

        # determine names of tempdirs for staging
        basedir = self.basedir.rstrip(os.path.sep)
        repos_dir = os.path.dirname(basedir)
        repo_name = os.path.basename(basedir)
        self.tempdir = os.path.join(repos_dir, f'.{repo_name}.update.{uuid.uuid4().hex}')
        self.tempdir_old = os.path.join(repos_dir, f'.{repo_name}.old.{uuid.uuid4().hex}')
        # remove temp repo dir on exit
        atexit.register(partial(shutil.rmtree, self.tempdir, ignore_errors=True))
        return tarball

    def _post_download(self, path):
        # create tempdir for staging decompression
        try:
            os.makedirs(self.tempdir)
        except OSError as e:
            raise base.SyncError(
                f'failed creating repo update dir: {self.tempdir!r}: {e.strerror}') from e

        exts = {'gz': 'gzip', 'bz2': 'bzip2', 'xz': 'xz'}
        compression = exts[self.uri.rsplit('.', 1)[1]]
        # use tar instead of tarfile so we can easily strip leading path components
        # TODO: programmatically determine how man components to strip?
        cmd = [
            'tar', '--extract', f'--{compression}', '-f', path,
            '--strip-components=1', '-C', self.tempdir
        ]
        try:
            subprocess.check_call(cmd)
        except subprocess.CalledProcessError as e:
            raise base.SyncError('failed to unpack tarball') from e

        # move old repo out of the way and then move new, unpacked repo into place
        try:
            os.rename(self.basedir, self.tempdir_old)
            os.rename(self.tempdir, self.basedir)
        except OSError as e:
            raise base.SyncError(f'failed to update repo: {e.strerror}') from e

        # register old repo removal after it has been successfully replaced
        atexit.register(partial(shutil.rmtree, self.tempdir_old, ignore_errors=True))
