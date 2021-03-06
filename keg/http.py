import json
import os
from datetime import datetime
from hashlib import md5
from io import StringIO
from typing import Any, List, Tuple

import requests

from . import psv
from .exceptions import NetworkError
from .utils import atomic_write, partition_hash


class PSVResponse:
	def __init__(self, row: psv.PSVRow) -> None:
		self._row = row

	def __repr__(self):
		return f"<{self.__class__.__name__}: {self._row}>"


class Blobs(PSVResponse):
	def __init__(self, row: psv.PSVRow) -> None:
		super().__init__(row)
		self.region = row.Region
		self.install_blob_md5 = row.InstallBlobMD5.lower()
		self.game_blob_md5 = row.GameBlobMD5.lower()


class CDNs(PSVResponse):
	def __init__(self, row: psv.PSVRow) -> None:
		super().__init__(row)
		self.name = row.Name
		self.path = row.Path
		self.config_path = row.ConfigPath

	def __repr__(self):
		return f"<{self.__class__.__name__}: {self._values}>"

	@property
	def all_servers(self) -> List[str]:
		return self.servers + [f"http://{host}" for host in self.hosts]

	@property
	def hosts(self) -> List[str]:
		return self._row.Hosts.split()

	@property
	def servers(self) -> List[str]:
		return self._row.Servers.split()


class Versions(PSVResponse):
	def __init__(self, row: psv.PSVRow) -> None:
		super().__init__(row)
		self.build_config = row.BuildConfig.lower()
		self.build_id = row.BuildId
		self.cdn_config = row.CDNConfig.lower()
		self.keyring = getattr(row, "KeyRing", "")
		self.product_config = getattr(row, "ProductConfig", "").lower()
		self.region = row.Region
		self.versions_name = row.VersionsName


class BGDL(Versions):
	pass


class StateCache:
	def __init__(self, cache_dir: str) -> None:
		self.cache_dir = cache_dir

	def _ensure_dir_exists(self, path: str):
		dirname = os.path.dirname(path)
		if not os.path.exists(dirname):
			os.makedirs(dirname)

	def exists(self, name: str, key: str) -> bool:
		return os.path.exists(self.get_full_path(name, key))

	def get_full_path(self, name: str, key: str) -> str:
		return os.path.join(self.cache_dir, name.strip("/"), partition_hash(key))

	def read(self, name: str, key: str) -> str:
		with open(self.get_full_path(name, key), "r") as f:
			return f.read()

	def read_psv(self, name: str, key: str) -> psv.PSVFile:
		data = self.read(name, key)
		return psv.loads(data)

	def write(self, name: str, key: str, content: bytes) -> int:
		path = self.get_full_path(name, key)
		self._ensure_dir_exists(path)
		return atomic_write(path, content)


class StatefulResponse:
	def __init__(self, name: str, response: requests.Response) -> None:
		self.name = name
		self.content = response.content
		self.timestamp = int(datetime.now().timestamp())
		self.digest = md5(self.content).hexdigest()
		self.cache_path = os.path.join(
			self.name.strip("/"),
			partition_hash(self.digest)
		)

		if response.status_code != 200:
			raise NetworkError(f"Got status code {response.status_code} for {repr(name)}")

	def write_to_cache(self, base_cache_dir: str) -> int:
		return StateCache(base_cache_dir).write(self.name, self.digest, self.content)


class HttpBackend:
	def __init__(self, remote: str) -> None:
		self.remote = remote

	def get_response(self, path: str) -> StatefulResponse:
		url = self.remote + path
		return StatefulResponse(path, requests.get(url))

	def get_blobs(self) -> List[Blobs]:
		psvfile, _ = self.get_psv("/blobs")
		return [Blobs(row) for row in psvfile]

	def get_cdns(self) -> List[CDNs]:
		psvfile, _ = self.get_psv("/cdns")
		return [CDNs(row) for row in psvfile]

	def get_versions(self) -> List[Versions]:
		psvfile, _ = self.get_psv("/versions")
		return [Versions(row) for row in psvfile]

	def get_blob(self, name: str) -> Tuple[Any, StatefulResponse]:
		resp = self.get_response(f"/blob/{name}")
		return json.loads(resp.content.decode()), resp

	def get_bgdl(self) -> List[BGDL]:
		psvfile, _ = self.get_psv("/bgdl")
		return [BGDL(row) for row in psvfile]

	def get_psv(self, path: str) -> Tuple[psv.PSVFile, StatefulResponse]:
		resp = self.get_response(path)
		return psv.load(StringIO(resp.content.decode())), resp
