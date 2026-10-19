"""Prüft den dauerhaften Wiener Rastercache ohne GIP-/Abschnittslogik."""
import argparse
import json
from pathlib import Path

from scripts.wienwide_grid import read_manifest


def verify(cache, *, tile_m=1000):
	cache=Path(cache)
	if cache.is_symlink():
		raise ValueError("Wien-Cache darf kein Symlink sein")
	manifest_file=cache/"raster.json"
	manifest,_aoi=read_manifest(manifest_file)
	if manifest["tile_size_m"]!=tile_m or manifest["halo_m"]!=75:
		raise ValueError("Gespeichertes Wien-Raster hat andere Kachelgröße/Halo")
	return {
		"stage":"grid",
		"tiles":len(manifest["tiles"]),
		"tile_size_m":manifest["tile_size_m"],
		"halo_m":manifest["halo_m"],
	}


def main():
	parser=argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--cache",type=Path,required=True)
	parser.add_argument("--tile-m",type=int,default=1000)
	args=parser.parse_args()
	print(json.dumps(verify(args.cache,tile_m=args.tile_m),ensure_ascii=False))


if __name__=="__main__":
	main()
