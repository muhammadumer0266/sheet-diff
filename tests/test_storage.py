import os

import pytest

from sheetdiff import config, storage


def test_local_path_passthrough(tmp_path):
    f = tmp_path / "a.csv"
    f.write_text("id,val\n1,a\n")
    assert storage.resolve(str(f), str(tmp_path)) == str(f)


def test_missing_local_file_raises(tmp_path):
    with pytest.raises(storage.StorageError):
        storage.resolve(str(tmp_path / "does-not-exist.csv"), str(tmp_path))


def test_windows_drive_letter_is_not_a_scheme(tmp_path):
    # A bare "C:" must never be confused with "c://..." — only "scheme://" counts.
    assert storage._split_scheme(r"C:\Users\x\file.xlsx") is None
    assert not storage.is_remote_ref(r"C:\Users\x\file.xlsx")


@pytest.mark.parametrize("scheme", ["s3", "minio", "r2", "garage", "az", "azure"])
def test_known_schemes_recognized(scheme):
    assert storage.is_remote_ref(f"{scheme}://bucket/key.xlsx")


def test_disallowed_scheme_rejected(tmp_path):
    with pytest.raises(storage.SchemeNotAllowedError):
        storage.resolve("http://example.com/file.xlsx", str(tmp_path))
    with pytest.raises(storage.SchemeNotAllowedError):
        storage.resolve("ftp://example.com/file.xlsx", str(tmp_path))


def test_allowed_schemes_configurable(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ALLOWED_REMOTE_SCHEMES", {"s3"})
    assert storage.is_remote_ref("s3://bucket/key.xlsx")
    assert not storage.is_remote_ref("az://container/blob.xlsx")
    with pytest.raises(storage.SchemeNotAllowedError):
        storage.resolve("az://container/blob.xlsx", str(tmp_path))


def test_resolve_many_cleans_up_on_partial_failure(tmp_path, monkeypatch):
    good = tmp_path / "good.csv"
    good.write_text("id,val\n1,a\n")

    downloaded_paths = []

    def fake_fetch(ref, dest_dir, max_bytes=None):
        path = os.path.join(dest_dir, "downloaded.csv")
        with open(path, "wb") as fh:
            fh.write(b"id,val\n1,a\n")
        downloaded_paths.append(path)
        return path

    monkeypatch.setattr(storage, "fetch_to_local", fake_fetch)

    with pytest.raises(storage.StorageError):
        storage.resolve_many(
            [str(good), "s3://bucket/ok.csv", str(tmp_path / "missing.csv")],
            str(tmp_path),
        )

    # The file fetch_to_local "downloaded" must have been cleaned up.
    assert downloaded_paths, "fake fetch was never called"
    assert not os.path.exists(downloaded_paths[0])


def test_missing_remote_extra_gives_actionable_error(tmp_path, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "fsspec":
            raise ImportError("no fsspec")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(storage.MissingDependencyError):
        storage.resolve("s3://bucket/key.xlsx", str(tmp_path))


class _FakeRemoteFile:
    def __init__(self, data: bytes):
        self._data = data
        self._pos = 0

    def read(self, n):
        chunk = self._data[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeFs:
    def __init__(self, data: bytes, reported_size):
        self._data = data
        self._reported_size = reported_size

    def info(self, path):
        return {"size": self._reported_size}

    def open(self, path, mode):
        return _FakeRemoteFile(self._data)


def test_fetch_to_local_rejects_oversized_reported_size(tmp_path, monkeypatch):
    fake_fs = _FakeFs(data=b"x" * 100, reported_size=10_000_000)
    monkeypatch.setattr(storage, "_get_filesystem", lambda scheme: fake_fs)
    with pytest.raises(storage.RemoteFileTooLargeError):
        storage.fetch_to_local("s3://bucket/big.xlsx", str(tmp_path), max_bytes=1024)
    # nothing left behind
    assert list(tmp_path.iterdir()) == []


def test_fetch_to_local_rejects_when_stream_exceeds_lied_about_size(tmp_path, monkeypatch):
    # Reported size looks fine, but the actual bytes are bigger — must still be caught.
    fake_fs = _FakeFs(data=b"x" * 5000, reported_size=10)
    monkeypatch.setattr(storage, "_get_filesystem", lambda scheme: fake_fs)
    with pytest.raises(storage.RemoteFileTooLargeError):
        storage.fetch_to_local("s3://bucket/lied.xlsx", str(tmp_path), max_bytes=100)
    assert list(tmp_path.iterdir()) == []


def test_fetch_to_local_downloads_within_limit(tmp_path, monkeypatch):
    fake_fs = _FakeFs(data=b"id,val\n1,a\n", reported_size=11)
    monkeypatch.setattr(storage, "_get_filesystem", lambda scheme: fake_fs)
    path = storage.fetch_to_local("s3://bucket/small.csv", str(tmp_path), max_bytes=1024)
    assert os.path.exists(path)
    with open(path, "rb") as fh:
        assert fh.read() == b"id,val\n1,a\n"


def test_env_int_validation(monkeypatch):
    monkeypatch.setenv("SHEETDIFF_MAX_UPLOAD_MB", "not-a-number")
    with pytest.raises(ValueError):
        config._env_int("SHEETDIFF_MAX_UPLOAD_MB", 100)

    monkeypatch.setenv("SHEETDIFF_MAX_UPLOAD_MB", "-5")
    with pytest.raises(ValueError):
        config._env_int("SHEETDIFF_MAX_UPLOAD_MB", 100)

    monkeypatch.setenv("SHEETDIFF_MAX_UPLOAD_MB", "250")
    assert config._env_int("SHEETDIFF_MAX_UPLOAD_MB", 100) == 250
