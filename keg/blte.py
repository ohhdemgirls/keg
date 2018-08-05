import hashlib
import struct
import zlib
from binascii import hexlify
from io import BytesIO


# 00000000: 424c 5445 0000 00b4 0f00 0007 0000 0017  BLTE............
#           ^ 4-byte BLTE magic
#                     ^ 4-byte big-endian header size
#                               ^ 1-byte version
#                                 ^ 3-byte (big-endian) number of blocks
#                                         ^ first block encoded size
# 00000010: 0000 0016 6f65 6f53 d85a d828 108e 8444  ....oeoS.Z.(...D
#           ^ first block decoded size
#                     ^ first block encoded md5 hash
# 00000020: 8535 b202 0000 003b 0000 0036 f490 b704  .5.....;...6....
#                     ^ second block encoded size ...
# 00000030: 25e9 4f52 047f 7583 2f64 3b40 0000 0101  %.OR..u./d;@....
# 00000040: 0000 0100 35e0 1068 8ac0 e7d9 4a67 6e89  ....5..h....Jgn.
# 00000050: 72ed 60c2 0000 8001 0000 8000 7d54 b708  r.`.........}T..
# 00000060: 1246 2e1a 377b d2ba 578e 6d35 0000 00a1  .F..7{..W.m5....
# 00000070: 0000 00a0 4678 ee15 76ba 8650 5c6a 29fa  ....Fx..v..P\j).
# 00000080: 009c a687 0000 5001 0000 5000 2632 c86f  ......P...P.&2.o
# 00000090: 7bc2 cbfc 89f4 e93a f8ef c120 0000 002f  {......:... .../
# 000000a0: 0000 002d 0f44 12c6 9a86 82cf 1bfe 63d5  ...-.D........c.
# 000000b0: 8564 1952 4e45 4e01 1010 0004 0004 0000  .d.RNEN.........
#                     ^ first block data
# 000000c0: 0008 0000 0005 0000 0000 365a 78da 4bb2  ..........6Zx.K.
#                                      ^ second block data


def decode_block(data):
	type = data[0]

	if type == b"N"[0]:
		return data[1:]
	elif type == b"Z"[0]:
		return zlib.decompress(data[1:], wbits=0)

	raise ValueError(f"Unknown block type {type}")


class BLTEDecoder:
	def __init__(self, fp, hash, verify=False):
		self.fp = fp
		self.block_table = []
		self._blocks = []
		self._block_index = 0
		self.hash = hash
		self.verify = verify
		self.parse_header()

	def parse_header(self):
		blte_header_data = self.fp.read(8)
		blte_header = BytesIO(blte_header_data)
		assert blte_header.read(4) == b"BLTE"
		header_size, = struct.unpack(">i", blte_header.read(4))
		# TODO: handle header_size == 0
		assert self.fp.read(1) == b"\x0f"
		block_info_data = self.fp.read(header_size - 9)
		if self.verify:
			assert self.hash == hashlib.md5(blte_header_data + b"\x0f" + block_info_data).hexdigest()

		block_info = BytesIO(block_info_data)
		self.parse_block_info(block_info)

	def parse_block_info(self, fp):
		num_blocks, = struct.unpack(">i", b"\x00" + fp.read(3))
		for i in range(num_blocks):
			encoded_size, decoded_size, md5 = struct.unpack(
				">ii16s", fp.read(4 + 4 + 16)
			)
			self.block_table.append(
				(encoded_size, decoded_size, hexlify(md5).decode())
			)

	@property
	def blocks(self):
		for encoded_block in self.encoded_blocks:
			yield decode_block(encoded_block)

	@property
	def encoded_blocks(self):
		if self._block_index:
			raise RuntimeError(
				"BLTE.blocks has already been iterated over. "
				"You should have stored it. "
				"Now you can't get it back."
			)

		for encoded_size, decoded_size, md5 in self.block_table:
			data = self.fp.read(encoded_size)
			if self.verify:
				assert md5 == hashlib.md5(data).hexdigest()
			self._block_index += 1
			yield data