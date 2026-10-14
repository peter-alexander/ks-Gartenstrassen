import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image
from pyproj import CRS

from scripts.probe_bev_wms import LAYERS, WMS_CRS, compare_channels, worldfile_parameters
from scripts.segment_bev_vegetation import (
	component_regions,
	render_class_mask,
	render_classification,
	run,
)


SIZE = (30, 18)


def scene():
	"""Texturierte Vegetation, glatte Vegetation, schwache Vegetation, Kleinstfläche."""
	w, h = SIZE
	raw = {name: Image.new("RGBA", SIZE) for name in LAYERS}
	for y in range(h):
		for x in range(w):
			red, green, blue, nir = 105, 100, 100, 70  # urbaner Hintergrund
			if 1 <= x <= 7 and 1 <= y <= 7:
				# Strukturiertes Kandidatenobjekt, Index (NIR-R)/(NIR+R)=1/3
				red = 45 if (x+y) % 2 else 90
				green = red
				blue = red
				nir = 2*red
			elif 13 <= x <= 21 and 2 <= y <= 10:
				red, green, blue, nir = 50, 75, 45, 105
			elif 24 <= x <= 28 and 1 <= y <= 8:
				red, green, blue, nir = 100, 90, 70, 130  # nur Low 0.10
			elif 2 <= x <= 3 and 12 <= y <= 13:
				red, green, blue, nir = 45, 60, 40, 110  # zu klein
			alpha = 255
			raw["rgb"].putpixel((x,y), (red,green,blue,alpha))
			raw["ir"].putpixel((x,y), (nir,nir,nir,alpha))
			raw["rgir"].putpixel((x,y), (red,green,nir,alpha))
			raw["rirb"].putpixel((x,y), (red,nir,blue,alpha))
			raw["irgb"].putpixel((x,y), (nir,red,green,alpha))
	return raw


def masks_for_scene():
	from scripts.analyze_bev_vegetation import index_and_masks
	images = scene()
	_, masks, stats = index_and_masks(images["rgb"], images["ir"],
		thresholds=(0.10,0.20))
	return images, masks, stats


def write_source(tmp):
	root = Path(tmp)
	root.mkdir(parents=True, exist_ok=True)
	images = scene()
	geometry = {"crs":WMS_CRS,
		"width":SIZE[0],"height":SIZE[1],
		"bbox":[1821276,6143715,1821306,6143733]}
	world = "\n".join(f"{x:.12f}" for x in worldfile_parameters(geometry)) + "\n"
	prj = CRS.from_user_input(WMS_CRS).to_wkt() + "\n"
	recs = {}
	for key in ("rgb", "ir"):
		filename = root / f"bev_{key}_test.png"
		images[key].save(filename, format="PNG")
		(root / f"bev_{key}_test.pgw").write_text(world, encoding="ascii")
		(root / f"bev_{key}_test.prj").write_text(prj, encoding="utf-8")
		recs[key] = {
			"layer": LAYERS[key],
			"status": "getmap_png_valide",
			"png_sha256": hashlib.sha256(filename.read_bytes()).hexdigest(),
		}
	compare = compare_channels(images)
	report = {
		"schema_version": 1,
		"wms": {"basis_url":"https://kataster.bev.gv.at/ortho/ows",
			"version":"1.3.0", "bilder": recs},
		"raster_ausrichtung": geometry,
		"vergleich": compare,
		"aufnahmejahr": "unbekannt",
	}
	(root / "bev_wms_diagnose.json").write_text(json.dumps(report), encoding="utf-8")
	return images, report


class VegetationSegmentationTests(unittest.TestCase):
	def test_two_thresholds_and_texture_classification(self):
		images, masks, _ = masks_for_scene()
		classified, regions, stats = component_regions(
			masks[0.10], masks[0.20], images["rgb"])
		self.assertEqual(stats["regionen_010"], 4)
		self.assertEqual(classified.getpixel((1,1)), 4)
		self.assertEqual(classified.getpixel((13,2)), 5)
		self.assertEqual(classified.getpixel((24,1)), 1)
		self.assertEqual(classified.getpixel((2,12)), 2)
		self.assertEqual(classified.getpixel((10,0)), 0)
		self.assertEqual(stats["klassen_pixel"]["strukturreicher_kronenkandidat"], 49)
		self.assertEqual(stats["klassen_pixel"]["strukturarm_nicht_als_baum_ausgeschlossen"], 81)
		self.assertEqual(stats["klassen_pixel"]["schwache_vegetation_ohne_kern"], 40)
		self.assertEqual(stats["klassen_pixel"]["klein_unklar"], 4)
		self.assertEqual(stats["hysterese_pixel"], 134)
		self.assertEqual(len(regions), 4)
		self.assertTrue(all("starker_kern_anteil" in item for item in regions))
		self.assertTrue(all("raster_kompaktheit_indikativ" in item for item in regions))

	def test_separate_weak_signal_is_not_hysteresis(self):
		images, masks, _ = masks_for_scene()
		classes, _, _ = component_regions(masks[0.10], masks[0.20], images["rgb"])
		hysteresis = render_class_mask(classes, {2,3,4,5})
		crown = render_class_mask(classes, {4})
		self.assertEqual(hysteresis.getpixel((24,1)), 0)
		self.assertEqual(hysteresis.getpixel((13,3)), 255)
		self.assertEqual(crown.getpixel((13,3)), 0)
		self.assertEqual(crown.getpixel((1,1)), 255)
		overlay = render_classification(images["rgb"], classes)
		self.assertEqual(overlay.size, SIZE)
		self.assertNotEqual(overlay.getpixel((1,1)),
			images["rgb"].getpixel((1,1)))

	def test_parameter_validation(self):
		images, masks, _ = masks_for_scene()
		for opts in ({"crown_texture_dn": 0.0},
			{"flat_texture_dn": 12.0},
			{"flat_texture_dn": -1.0},
			{"min_region_pixels": 0},
			{"min_region_pixels": 10001},
			{"crown_texture_dn": float("nan")}):
			with self.subTest(opts=opts), self.assertRaises(ValueError):
				component_regions(masks[0.10], masks[0.20],
					images["rgb"], **opts)

	def test_end_to_end_offline_outputs_and_no_crown_geodata(self):
		with tempfile.TemporaryDirectory() as folder:
			root = Path(folder)
			input_dir, out = root / "bev_wms", root / "seg"
			write_source(input_dir)
			old_png = (input_dir / "bev_rgb_test.png").read_bytes()
			summary = run(input_dir=input_dir, output=out)
			self.assertEqual(summary["schwellen"]["low_vegetation"], 0.1)
			self.assertEqual(summary["schwellen"]["strong_signal"], 0.2)
			self.assertEqual(summary["segmentierung"]["regionen_010"], 4)
			self.assertEqual(summary["segmentierung"]["kronenkandidaten_pixel"], 49)
			self.assertTrue((out / "bev_segmentation_objekte.json").exists())
			for stem in ("bev_segmentation_kandidaten", "bev_segmentation_klassen",
				"bev_segmentation_kronenkandidaten", "bev_segmentation_hysterese"):
				for ext in (".png", ".pgw", ".prj"):
					self.assertTrue((out / f"{stem}{ext}").is_file())
			with Image.open(out / "bev_segmentation_klassen.png") as layer:
				self.assertEqual(layer.size, SIZE)
			with Image.open(out / "bev_segmentation_hysterese.png") as layer:
				self.assertEqual(layer.getpixel((24,1)), 0)
			self.assertFalse(any(out.glob("*.geojson")))
			self.assertEqual((input_dir / "bev_rgb_test.png").read_bytes(), old_png)
			with self.assertRaises(FileExistsError):
				run(input_dir=input_dir, output=out)

	def test_changed_wms_source_rejected_before_outputs(self):
		with tempfile.TemporaryDirectory() as folder:
			root = Path(folder)
			input_dir, out = root / "bev_wms", root / "seg"
			write_source(input_dir)
			with Image.open(input_dir / "bev_ir_test.png") as orig:
				changed = orig.copy()
			changed.putpixel((0,0), (10,10,10,255))
			changed.save(input_dir / "bev_ir_test.png")
			with self.assertRaisesRegex(ValueError, "SHA-256"):
				run(input_dir=input_dir, output=out)
			self.assertFalse(out.exists())


if __name__ == "__main__":
	unittest.main()
