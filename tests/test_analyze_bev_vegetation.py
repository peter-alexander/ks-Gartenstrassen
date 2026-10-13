import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image
from pyproj import CRS

from scripts.analyze_bev_vegetation import (
	check_core_consistency, index_and_masks, overlay_rgb, parse_thresholds, run,
	validate_manifest,
)
from scripts.probe_bev_wms import (
	LAYERS, WMS_CRS, compare_channels, worldfile_parameters,
)


def sample_images(size=(20, 16), *, irgb_color_shift=False):
	w, h = size
	images = {name: Image.new("RGBA", size) for name in LAYERS}
	for y in range(h):
		for x in range(w):
			if x < 6:
				r, g, b, nir = 40, 75, 40, 160
			elif x < 12:
				r, g, b, nir = 120, 105, 85, 80
			elif x < 15:
				r, g, b, nir = 2, 4, 3, 3
			else:
				r, g, b, nir = 80, 100, 80, 120
			alpha = 0 if (x == 19 and y == 0) else 255
			images["rgb"].putpixel((x, y), (r, g, b, alpha))
			images["ir"].putpixel((x, y), (nir, nir, nir, alpha))
			images["rgir"].putpixel((x, y), (r, g, nir, alpha))
			images["rirb"].putpixel((x, y), (r, nir, b, alpha))
			images["irgb"].putpixel((x, y),
				(nir, min(255, r+20) if irgb_color_shift else r,
				 min(255, g+15) if irgb_color_shift else g, alpha))
	return images


def prepare_files(path, *, legacy=True, irgb_color_shift=True):
	path.mkdir(parents=True, exist_ok=True)
	images = sample_images(irgb_color_shift=irgb_color_shift)
	bbox = [1821276, 6143715, 1821296, 6143731]
	geometry = {
		"crs": "EPSG:3857",
		"width": 20, "height": 16, "bbox": bbox,
	}
	world = "\n".join(f"{x:.12f}" for x in worldfile_parameters(geometry)) + "\n"
	wkt = CRS.from_user_input(WMS_CRS).to_wkt() + "\n"
	image_records = {}
	for alias in ("rgb", "ir"):
		file = path / f"bev_{alias}_test.png"
		images[alias].save(file, format="PNG")
		(path / f"bev_{alias}_test.pgw").write_text(world, encoding="ascii")
		(path / f"bev_{alias}_test.prj").write_text(wkt, encoding="utf-8")
		image_records[alias] = {
			"layer": LAYERS[alias], "status": "getmap_png_valide",
			"png_sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
		}
	compare = compare_channels(images)
	if legacy:
		compare.pop("kernkanaele_intern_konsistent")
		compare.pop("kernkanalgruppen")
		compare.pop("abweichungen_alle_darstellungen")
	report = {
		"schema_version": 1,
		"wms": {
			"basis_url": "https://kataster.bev.gv.at/ortho/ows",
			"version": "1.3.0", "bilder": image_records,
		},
		"raster_ausrichtung": geometry,
		"vergleich": compare,
		"aufnahmejahr": "unbekannt",
	}
	(path / "bev_wms_diagnose.json").write_text(json.dumps(report), encoding="utf-8")
	return images, report


class BEVVegetationAnalysisTests(unittest.TestCase):
	def test_threshold_validation_strict_and_non_mutating(self):
		self.assertEqual(parse_thresholds("0.30,0.10,0.20"), (0.1, 0.2, 0.3))
		for item in ("0.10,0.10", "-0.1", "0.85", "0.105",
			"not_a_number", "", "0.1,NaN"):
			with self.subTest(item=item), self.assertRaises(ValueError):
				parse_thresholds(item)

	def test_nir_minus_red_over_sum_and_exclusion(self):
		images = sample_images()
		index, masks, stats = index_and_masks(
			images["rgb"], images["ir"],
			thresholds=(0.1, 0.2, 0.4), min_signal=20)
		self.assertEqual(index.mode, "LA")
		self.assertEqual(stats["pixel_gesamt"], 320)
		self.assertEqual(stats["pixel_zu_dunkel_oder_summe_null"], 48)
		self.assertEqual(stats["pixel_teiltransparent_oder_transparent"], 1)
		self.assertEqual(stats["pixel_verwertbar"], 271)
		# R=40, NIR=160 => 0.6
		self.assertEqual(index.getpixel((0, 0)), (204, 255))
		self.assertEqual(masks[0.4].getpixel((0, 0)), 255)
		# R=120, NIR=80 => -0.2
		self.assertEqual(masks[0.1].getpixel((8, 3)), 0)
		# R=2, NIR=3 => no signal
		self.assertEqual(index.getpixel((13, 0))[1], 0)
		self.assertEqual(masks[0.1].getpixel((13, 0)), 0)
		# R=80, NIR=120 => exactly 0.2
		self.assertEqual(masks[0.2].getpixel((16, 0)), 255)
		self.assertEqual(masks[0.4].getpixel((16, 0)), 0)
		self.assertEqual(stats["schwellen"][0]["pixel_positiv"], 175)
		self.assertEqual(stats["schwellen"][1]["pixel_positiv"], 175)
		self.assertEqual(stats["schwellen"][2]["pixel_positiv"], 96)

	def test_overlay_is_exact_pixel_and_not_vector_canopy(self):
		images = sample_images()
		_, masks, _ = index_and_masks(images["rgb"], images["ir"])
		overlay = overlay_rgb(images["rgb"], masks[0.1])
		self.assertEqual(overlay.size, images["rgb"].size)
		self.assertNotEqual(overlay.getpixel((1, 1)),
			images["rgb"].getpixel((1, 1)))
		self.assertEqual(overlay.getpixel((7, 1)),
			images["rgb"].getpixel((7, 1)))

	def test_legacy_report_with_irgb_discrepancy_has_valid_core(self):
		with tempfile.TemporaryDirectory() as tmp:
			_, report = prepare_files(Path(tmp), legacy=True, irgb_color_shift=True)
			self.assertFalse(report["vergleich"]["alle_kanalreplikate_intern_konsistent"])
			geometry, evidence = validate_manifest(report)
			self.assertEqual(geometry["width"], 20)
			self.assertEqual(evidence, "aus_einzelvergleich_abgeleitet")
			self.assertEqual(check_core_consistency(report),
				"aus_einzelvergleich_abgeleitet")

	def test_real_core_mismatch_is_not_accepted_even_with_legacy_report(self):
		with tempfile.TemporaryDirectory() as tmp:
			_, report = prepare_files(Path(tmp))
			for item in report["vergleich"]["kanalgruppen"]["rot"]:
				if item["vergleich"] == "rgir:RGBA[0]":
					item["intern_konsistent"] = False
			with self.assertRaisesRegex(ValueError, "Nicht belegte Kernkanalkonsistenz"):
				validate_manifest(report)

	def test_invalid_new_core_flag_rejected(self):
		with tempfile.TemporaryDirectory() as tmp:
			_, report = prepare_files(Path(tmp), legacy=False)
			report["vergleich"]["kernkanaele_intern_konsistent"] = False
			with self.assertRaisesRegex(ValueError, "nicht bestanden"):
				validate_manifest(report)

	def test_offline_end_to_end_outputs_are_georeferenced(self):
		with tempfile.TemporaryDirectory() as tmp:
			inp, out = Path(tmp) / "bev_wms", Path(tmp) / "veg"
			images, _ = prepare_files(inp)
			result = run(input_dir=inp, output=out)
			self.assertEqual(result["statistik"]["pixel_verwertbar"], 271)
			self.assertTrue((out / "bev_vegetation_vergleich.png").is_file())
			self.assertTrue((out / "bev_vegetation_bericht.json").is_file())
			self.assertEqual(result["quelle"]["kernkanalpruefung"],
				"aus_einzelvergleich_abgeleitet")
			for key in ("010", "020", "030", "040"):
				for name in (f"bev_veg_maske_{key}", f"bev_veg_overlay_{key}"):
					for extension in ("png", "pgw", "prj"):
						self.assertTrue((out / f"{name}.{extension}").is_file())
			with Image.open(out / "bev_veg_maske_020.png") as mask:
				self.assertEqual(mask.getpixel((0, 0)), 255)
				self.assertEqual(mask.getpixel((7, 0)), 0)
			with Image.open(out / "bev_vegetation_index.png") as index:
				self.assertEqual(index.mode, "LA")
				self.assertEqual(index.size, (20, 16))
			self.assertFalse(any(out.glob("*.geojson")))
			with self.assertRaises(FileExistsError):
				run(input_dir=inp, output=out)
			# Weder Rohbilder noch Diagnose dürfen verändert worden sein.
			with Image.open(inp / "bev_rgb_test.png") as rgb:
				self.assertEqual(rgb.getpixel((0, 0)), images["rgb"].getpixel((0, 0)))

	def test_image_modified_after_probe_is_not_silently_accepted(self):
		with tempfile.TemporaryDirectory() as tmp:
			inp, out = Path(tmp) / "bev_wms", Path(tmp) / "veg"
			prepare_files(inp)
			with Image.open(inp / "bev_ir_test.png") as im:
				changed = im.copy()
			changed.putpixel((0, 0), (0, 0, 0, 255))
			changed.save(inp / "bev_ir_test.png")
			with self.assertRaisesRegex(ValueError, "SHA-256"):
				run(input_dir=inp, output=out)
			self.assertFalse(out.exists())

	def test_georeferencing_mismatch_is_rejected(self):
		with tempfile.TemporaryDirectory() as tmp:
			inp, out = Path(tmp) / "bev_wms", Path(tmp) / "veg"
			prepare_files(inp)
			(inp / "bev_ir_test.pgw").write_text(
				"1\n0\n0\n-1\n9999\n9999\n", encoding="ascii")
			with self.assertRaisesRegex(ValueError, "andere Projektion/Pixelgeometrie"):
				run(input_dir=inp, output=out)
			self.assertFalse(out.exists())

	def test_invalid_optional_thresholds_cannot_be_rounded_away(self):
		with tempfile.TemporaryDirectory() as tmp:
			inp, out = Path(tmp) / "bev_wms", Path(tmp) / "veg"
			prepare_files(inp)
			with self.assertRaisesRegex(ValueError, "0,01-Schritten"):
				run(input_dir=inp, output=out, thresholds=(0.105, 0.30))
			self.assertFalse(out.exists())


if __name__ == "__main__":
	unittest.main()
