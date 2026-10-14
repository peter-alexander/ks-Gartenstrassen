import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from pyproj import CRS, Transformer
from shapely.geometry import Polygon, box, mapping
from shapely.ops import transform

from scripts.compare_bev_variants import (
	D2_THRESHOLDS, D3_CLASSES, SELECTED_IOU,
	check_d3_report, measure_variants, nonempty_measure,
	raster_extent_in_metric, reference_comparison, runs_to_metric_union, run,
)
from scripts.probe_bev_wms import WMS_CRS, LAYERS, compare_channels, worldfile_parameters


TO_METRIC = Transformer.from_crs("EPSG:3857", "EPSG:31256", always_xy=True).transform
TO_LONLAT = Transformer.from_crs("EPSG:31256", "EPSG:4326", always_xy=True).transform


def grid(width=30, height=18):
	x, y = Transformer.from_crs("EPSG:4326", "EPSG:3857",
		always_xy=True).transform(16.363, 48.223)
	return {"crs": WMS_CRS, "bbox": [x, y, x+width, y+height],
		"width": width, "height": height}


def binary(rows):
	return Image.frombytes("L", (len(rows[0]), len(rows)),
		bytes(255 if character == "1" else 0
			for row in rows for character in row))


def fake_sources(path):
	geometry = grid()
	width, height = geometry["width"], geometry["height"]
	palette = {
		"rgb": (50, 90, 45, 255),
		"ir": (100, 100, 100, 255),
		"irgb": (100, 50, 90, 255),
		"rgir": (50, 90, 100, 255),
		"rirb": (50, 100, 45, 255),
	}
	references = {}
	world = "\n".join(f"{n:.12f}" for n in worldfile_parameters(geometry)) + "\n"
	prj = CRS.from_user_input(WMS_CRS).to_wkt() + "\n"
	for k in ("rgb", "ir"):
		img = Image.new("RGBA", (width, height), palette[k])
		if k == "rgb":
			# Stelle mit negativem Vegetationsindex, damit D2-Varianten
			# unterschiedliche Flächen liefern.
			for y in range(6, 12):
				for x in range(10, 18):
					img.putpixel((x, y), (160, 90, 45, 255))
		file = path / f"bev_{k}_test.png"
		img.save(file)
		references[k] = {
			"layer": LAYERS[k], "status": "getmap_png_valide",
			"png_sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
		}
		(path / f"bev_{k}_test.pgw").write_text(world, encoding="ascii")
		(path / f"bev_{k}_test.prj").write_text(prj, encoding="utf-8")
	images = {name: Image.new("RGBA", (width, height), palette[name]) for name in LAYERS}
	# Für Kernbelege alle Zusatzdarstellungen auf RGB der variablen Testszene
	# ausrichten.
	with Image.open(path/"bev_rgb_test.png") as im:
		rgb = im.copy()
	for y in range(height):
		for x in range(width):
			red, green, blue, alpha = rgb.getpixel((x,y))
			images["rgb"].putpixel((x,y), (red,green,blue,alpha))
			images["rgir"].putpixel((x,y), (red,green,100,alpha))
			images["rirb"].putpixel((x,y), (red,100,blue,alpha))
			images["irgb"].putpixel((x,y), (100,red,green,alpha))
	matches = compare_channels(images)
	assert matches["kernkanaele_intern_konsistent"]
	doc = {
		"schema_version":1,
		"wms":{"basis_url":"https://kataster.bev.gv.at/ortho/ows",
			"version":"1.3.0", "bilder":references},
		"raster_ausrichtung":geometry,
		"vergleich":matches,
	}
	(path/"bev_wms_diagnose.json").write_text(json.dumps(doc), encoding="utf-8")
	return geometry


class BEVVariantsMeasurementTests(unittest.TestCase):
	def test_rle_polygonization_and_metric_area_are_exact_for_grid(self):
		geo = grid(width=6,height=4)
		x0,y0,x1,y1 = geo["bbox"]
		full = transform(TO_METRIC, box(x0,y0,x1,y1))
		half = transform(TO_METRIC, box(x0,y0,x0+3,y1))
		raster = binary(["111000"]*4)
		shape, debug = runs_to_metric_union(raster, geo)
		self.assertEqual(debug["pixel_in_bbox"], 12)
		self.assertEqual(debug["horizontal_runs"], 4)
		self.assertAlmostEqual(shape.area, half.area, delta=0.001)
		metric, clipped = nonempty_measure(full, shape)
		self.assertAlmostEqual(metric["bedeckung_pct"], 50, delta=0.001)
		self.assertAlmostEqual(metric["bedeckt_m2"], half.area, delta=0.001)
		self.assertTrue(clipped.is_valid)
		self.assertAlmostEqual(raster_extent_in_metric(geo).area,
			full.area, delta=0.01)

	def test_polygon_clip_respects_fractional_edge_cells(self):
		geo = grid(width=3, height=3)
		x0,y0,x1,y1 = geo["bbox"]
		street = transform(TO_METRIC, Polygon([
			(x0,y1), (x0+1,y1), (x0,y1-1),
		]))
		mask = binary(["100", "000", "000"])
		values, clipped = measure_variants(street, {"d": mask}, geo)
		self.assertGreater(values["d"]["maskenmetrik"]["bedeckt_m2"], 0)
		self.assertAlmostEqual(values["d"]["maskenmetrik"]["bedeckung_pct"],
			100, delta=0.01)
		self.assertAlmostEqual(clipped.get("d",None), None)
		# Das Dreieck überdeckt nur eine HALBE Bildzelle. Wenn nur
		# Pixelzentren getestet würden, wäre es fälschlich 0 oder 1 Zelle.
		self.assertAlmostEqual(
			values["d"]["maskenmetrik"]["bedeckt_m2"], street.area, delta=0.001)

	def test_empty_mask_and_outside_wms_are_handled(self):
		geo=grid(width=3,height=3)
		x0,y0,x1,y1=geo["bbox"]
		empty=binary(["000"]*3)
		self.assertEqual(runs_to_metric_union(empty,geo)[0],None)
		street=transform(TO_METRIC,box(x0,y0,x1,y1))
		measurement,_=measure_variants(street,{"empty":empty},geo)
		self.assertEqual(measurement["empty"]["maskenmetrik"]["bedeckt_m2"],0)
		outside=transform(TO_METRIC,box(x0+4,y0,x0+6,y0+2))
		with self.assertRaisesRegex(ValueError,"nicht vollständig"):
			measure_variants(outside,{"empty":empty},geo)
		with self.assertRaisesRegex(ValueError,"ausschließlich die Werte 0 und 255"):
			runs_to_metric_union(Image.new("L",(3,3),127),geo)

	def test_reference_sources_optional_and_overlap(self):
		geo=grid(width=4,height=4)
		x0,y0,x1,y1=geo["bbox"]
		clip=transform(TO_METRIC,box(x0,y0,x1,y1))
		small=transform(TO_METRIC,box(x0,y0,x0+2,y1))
		with tempfile.TemporaryDirectory() as temp:
			p=Path(temp)/"source.geojson"
			source=mapping(transform(TO_LONLAT,small))
			p.write_text(json.dumps({"type":"FeatureCollection","features":[{
				"type":"Feature","properties":{},"geometry":source
			}]}))
			recs,pairs=reference_comparison(clip,{"D2_schwelle_010":small},
				{"A":p,"B":Path(temp)/"absent.geojson"})
			self.assertEqual(recs["A"]["status"],"gemessen")
			self.assertEqual(recs["B"]["status"],"lokale_quelle_fehlt")
			self.assertEqual(len(pairs),1)
			self.assertAlmostEqual(pairs[0]["iou"],1,delta=0.005)

	def test_end_to_end_comparison_outputs_and_sources_unmodified(self):
		with tempfile.TemporaryDirectory() as temp:
			root=Path(temp)
			input_dir=root/"wms"
			input_dir.mkdir()
			geo=fake_sources(input_dir)
			x0,y0,x1,y1=geo["bbox"]
			street=transform(TO_METRIC,box(x0,y0,x1,y1))
			fmzk=root/"fmzk.gpkg"
			out=root/"result"
			original=(input_dir/"bev_rgb_test.png").read_bytes()
			with patch("scripts.compare_bev_variants.load_polygons",
				return_value=([],{"bbox_lon_lat":[16.36,48.22,16.37,48.23]},street,[])), patch(
				"scripts.compare_bev_variants.load_street_mask",
				return_value=(street,{"masken_sha256":"fake-checked"})):
				result=run(input_dir=input_dir,output=out,fmzk=fmzk,
					street=root/"street.geojson",
					d3_report=root/"absent_d3.json",references={})
			self.assertEqual(len(result["varianten"]),len(D2_THRESHOLDS)+len(D3_CLASSES))
			self.assertEqual(result["referenzen"],{})
			self.assertGreaterEqual(result["zeitmessung"]["gesamt_bis_bericht_s"], 0)
			self.assertGreaterEqual(result["zeitmessung"]["d_masken_vermessen_s"], 0)
			for variant in result["varianten"].values():
				self.assertGreaterEqual(variant["laufzeit_s"], 0)
			self.assertEqual(result["quelle"]["d3_bericht"]["status"],
				"nicht_vorhanden")
			self.assertGreater(result["varianten"]["D2_schwelle_010"]
				["maskenmetrik"]["bedeckung_pct"],0)
			self.assertAlmostEqual(result["varianten"]["D2_schwelle_010"]
				["maskenmetrik"]["bedeckung_pct"],
				result["varianten"]["D2_schwelle_015"]
				["maskenmetrik"]["bedeckung_pct"],delta=1e-5)
			self.assertGreater(
				result["varianten"]["D2_schwelle_010"]["maskenmetrik"]["bedeckt_m2"],
				result["varianten"]["D2_schwelle_040"]["maskenmetrik"]["bedeckt_m2"])
			# Ineinander liegende D2-Schwellen dürfen bei demselben Straßenraum
			# mit steigender Schwelle niemals mehr Fläche ergeben.
			d2_areas = [
				result["varianten"][f"D2_schwelle_{round(threshold*100):03d}"]
				["maskenmetrik"]["bedeckt_m2"]
				for threshold in D2_THRESHOLDS
			]
			self.assertTrue(all(first >= second - 0.001
				for first, second in zip(d2_areas, d2_areas[1:])))
			# Jede Vegetationszelle landet in genau einer D3-Klasse.
			def covered(name):
				return result["varianten"][name]["maskenmetrik"]["bedeckt_m2"]
			classes = (
				"D3_schwache_vegetation_ohne_kern",
				"D3_kleine_unklare_objekte",
				"D3_unklare_vegetation",
				"D3_strukturreiche_kronenkandidaten",
				"D3_strukturarme_vegetation",
			)
			self.assertAlmostEqual(sum(covered(name) for name in classes),
				covered("D2_schwelle_010"), delta=0.01)
			self.assertAlmostEqual(
				covered("D3_kronenkandidaten_plus_unklar"),
				covered("D3_unklare_vegetation")
				+ covered("D3_strukturreiche_kronenkandidaten"), delta=0.01)
			self.assertAlmostEqual(
				covered("D3_hysterese_010_mit_020_kern"),
				covered("D2_schwelle_010")
				- covered("D3_schwache_vegetation_ohne_kern"), delta=0.01)
			self.assertTrue((out/"bev_varianten_strassenraum_vergleich.json").exists())
			self.assertEqual((input_dir/"bev_rgb_test.png").read_bytes(),original)
			with self.assertRaises(FileExistsError):
				run(input_dir=input_dir,output=out,references={})


if __name__ == "__main__":
	unittest.main()
