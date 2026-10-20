"""Aktive Vorbereitungspipeline enthält weder GIP noch Kreuzungsausschnitte."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class PreparationPipelineTests(unittest.TestCase):
	def test_help_lists_only_preparation_stages(self):
		result=subprocess.run(
			["bash","scripts/run-sis-steps.sh","--help"],
			check=True,capture_output=True,text=True)
		self.assertIn("aoi grid street grm-fetch grm-build",result.stdout)
		for obsolete in ("gip-index","gip-merge","partition","trim","qa",
				"measure","pmtiles","junction","kreuzung"):
			self.assertNotIn(obsolete,result.stdout.lower().split("optionale umgebung:")[0])

	def test_grid_to_grm_has_no_gip_or_partition_command(self):
		with tempfile.TemporaryDirectory() as folder:
			root=Path(folder)
			cache=root/"cache"/"wien"
			cache.mkdir(parents=True)
			(cache/"aoi.geojson").write_text("placeholder")
			(cache/"raster.json").write_text("placeholder")
			fake=root/"python"
			fake.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n")
			fake.chmod(0o755)
			env=os.environ | {
				"PYTHON":str(fake),
				"SIS_V2_CACHE_WIEN":str(cache),
				"SIS_V2_INDEX":str(root/"cache"/"sis-wien.sqlite"),
				"SIS_V2_GRM_RAW_ROOT":str(root/"raw"/"grm2023"),
			}
			result=subprocess.run(
				["bash","scripts/run-sis-steps.sh",
					"--from","street","--until","grm-build"],
				check=True,capture_output=True,text=True,env=env)
			self.assertIn("scripts.sis_v2_street",result.stdout)
			self.assertIn("scripts.wienwide_grm2023",result.stdout)
			for forbidden in ("gip","partition","trim","cross_section","pmtiles"):
				self.assertNotIn(forbidden,result.stdout.lower())


if __name__=="__main__":
	unittest.main()
