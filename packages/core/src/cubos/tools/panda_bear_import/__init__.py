"""PANDA-BEAR -> CubOS production configuration importer (internal package).

PANDA table names and raw SQL are confined to :mod:`db_reader`. Every other
module in this package operates on plain dataclasses/dicts so the rest of
CubOS never has to know about PANDA-BEAR's schema.
"""
