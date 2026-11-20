"""Request-contract regressions for presets, geometry profiles, and reports.

These tests simulate the Tiiny transport. They do not run an AI model or prove
that a geometry profile improves real-device output.
"""
import base64
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parent
with contextlib.redirect_stdout(io.StringIO()):
    spec = importlib.util.spec_from_file_location("test_offline_v030", ROOT / "test_offline.py")
    baseline = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = baseline
    spec.loader.exec_module(baseline)
addon = sys.modules["addon"]
TRELLIS = "microsoft/TRELLIS.2-4B"
HUNYUAN = "Tencent/Hunyuan3d-2.1"
TRELLIS_CAPS = json.loads((ROOT / "fixtures" / "tiiny_capabilities_trellis2.json").read_text())
HUNYUAN_CAPS = json.loads((ROOT / "fixtures" / "tiiny_capabilities_hunyuan3d.json").read_text())


def triangle_glb(label):
    """A valid single-triangle GLB; labels distinguish artifact provenance."""
    positions = struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0)
    indices = struct.pack("<3H", 0, 1, 2)
    binary = positions + indices + b"\0\0"
    document = {
        "asset": {"version": "2.0"}, "extras": {"test_label": label},
        "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(positions)},
                        {"buffer": 0, "byteOffset": len(positions), "byteLength": len(indices)}],
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3",
                       "min": [0, 0, 0], "max": [1, 1, 0]},
                      {"bufferView": 1, "componentType": 5123, "count": 3, "type": "SCALAR"}],
    }
    raw = json.dumps(document).encode()
    raw += b" " * (-len(raw) % 4)
    return (struct.pack("<4sII", b"glTF", 2, 28 + len(raw) + len(binary))
            + struct.pack("<II", len(raw), 0x4E4F534A) + raw
            + struct.pack("<II", len(binary), 0x004E4942) + binary)


SHAPE_GLB = triangle_glb("shape")
GEOMETRY_GLB = triangle_glb("geometry")
FINAL_GLB = triangle_glb("final")


def override(stage, parameter, value):
    return {"stage": stage, "param": parameter, "value": value, "enabled": True}


def settings(**changes):
    value = {"base": "http://device.example.test", "key": "private-test-key",
             "model": TRELLIS, "texture": True, "faces": 0, "seed": 42,
             "quality": "STANDARD", "custom_base": "NATIVE", "manual_overrides": False,
             "custom": [], "trellis_postprocess": "OFF", "auto_prepare": False,
             "save_stage_previews": False, "allow_trellis_1024": True}
    value.update(changes)
    return value


class FakeTiiny:
    def __init__(self, capabilities, outputs=None, failed_downloads=()):
        self.capabilities = copy.deepcopy(capabilities)
        self.capability_reads = 0
        self.posts = []
        self.downloads = []
        self.failed_downloads = set(failed_downloads)
        self.artifacts = {"shape-preview": SHAPE_GLB, "geometry-preview": GEOMETRY_GLB,
                          "shape-mesh": SHAPE_GLB, "final-glb": FINAL_GLB}
        self.outputs = {
            "shape": {"artifacts": [{"artifact_type": "shape", "artifact_id": "shape-ref"},
                                     {"artifact_type": "shape_preview", "artifact_id": "shape-preview"}]},
            "simplify": {"artifacts": [{"artifact_type": "geometry", "artifact_id": "geometry-ref"},
                                        {"artifact_type": "geometry_preview", "artifact_id": "geometry-preview"}]},
            "texture": {"artifacts": [{"artifact_type": "material", "artifact_id": "material-ref"}]},
            "export": {"artifacts": [{"artifact_type": "mesh_glb", "artifact_id": "final-glb"}]},
        }
        if not self.capabilities.get("input_refs"):
            self.outputs["shape"] = {"artifact_type": "mesh_glb", "glb": base64.b64encode(SHAPE_GLB).decode()}
            self.outputs["simplify"] = {"artifact_type": "mesh_glb", "glb": base64.b64encode(GEOMETRY_GLB).decode()}
            self.outputs["texture"] = {"artifact_type": "material_artifact",
                                       "artifact": base64.b64encode(b"test-material").decode()}
        self.outputs.update(copy.deepcopy(outputs or {}))

    def __call__(self, method, base, key, path, model="", fields=None, files=None, timeout=40, raw=False):
        if path == "/v1/3d/capabilities":
            self.capability_reads += 1
            return copy.deepcopy(self.capabilities)
        if method == "POST" and path == "/v1/3d/tasks":
            self.posts.append({"stage": fields["stage"], "params": json.loads(fields["params"]),
                               "input_refs": json.loads(fields.get("input_refs", "{}")),
                               "files": copy.deepcopy(files or {}), "model": model})
            return {"task_id": "task-" + str(len(self.posts))}
        if raw and "/artifacts/" in path:
            artifact_id = path.rsplit("/", 1)[-1]
            self.downloads.append(artifact_id)
            if artifact_id in self.failed_downloads:
                raise RuntimeError("HTTP 404: optional preview unavailable")
            return self.artifacts[artifact_id]
        if method == "GET" and path.startswith("/v1/3d/tasks/task-"):
            index = int(path.rsplit("-", 1)[-1]) - 1
            stage = self.posts[index]["stage"]
            return {"status": "completed", "progress": 100,
                    "metadata": {"seed": 42, "api_key": key, "private_url": base},
                    "result": {"output": copy.deepcopy(self.outputs[stage])}}
        raise AssertionError((method, path))


def run_job(configuration=None, capabilities=None, outputs=None, failed_downloads=()):
    """Run the complete worker, then copy results out of its temporary folder."""
    cfg = settings(**(configuration or {}))
    caps = capabilities or (HUNYUAN_CAPS if cfg["model"] == HUNYUAN else TRELLIS_CAPS)
    server = FakeTiiny(caps, outputs, failed_downloads)
    with tempfile.TemporaryDirectory(prefix="tiiny-contract-") as temporary:
        directory = Path(temporary)
        source = directory / "private-user" / "reference.png"
        source.parent.mkdir()
        source.write_bytes(b"image transport test; auto preparation disabled")
        cfg.update(image=str(source), output_dir=str(directory / "results"))
        # An old cached schema must not defeat validation against the fresh response.
        identity = addon._identity(cfg["base"], cfg["key"])
        addon._CAPABILITIES[(identity, cfg["model"])] = {"caps": copy.deepcopy(TRELLIS_CAPS)}
        jid = "v030-contract"
        addon._JOBS[jid] = {"state": "queued", "progress": 0}
        progress = []
        original_job_set = addon._job_set

        def track_progress(job_id, **values):
            if "progress" in values:
                progress.append(values["progress"])
            original_job_set(job_id, **values)

        with mock.patch.object(addon, "_request", server), mock.patch.object(addon.time, "sleep", lambda _: None), \
                mock.patch.object(addon, "_job_set", track_progress):
            addon._generate_worker(jid, cfg)
        job = dict(addon._JOBS[jid])
        reports = list((directory / "results").glob("*.json")) if (directory / "results").exists() else []
        report_text = reports[0].read_text() if reports else ""
        return {"job": job, "server": server, "report": json.loads(report_text) if reports else None,
                "report_text": report_text, "configuration": cfg, "temporary": temporary,
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "progress": progress,
                "output": Path(job["filename"]).read_bytes() if job.get("filename") else None,
                "saved_previews": [p.name for p in (directory / "results" / "diagnostics").rglob("*.glb")]}


class ProfileContracts(unittest.TestCase):
    def test_preset_baselines_and_manual_override_inheritance(self):
        for mode, precision, inference in (("DRAFT", "draft", "fast"),
                                          ("STANDARD", "standard", "balance"),
                                          ("MAXIMUM", "high", "quality")):
            with self.subTest(mode=mode):
                result = run_job({"quality": mode, "manual_overrides": True,
                                  "custom": [override("export", "texture_size", 1024)]})
                self.assertEqual(result["job"]["state"], "importing", result["job"])
                requests = {p["stage"]: p["params"] for p in result["server"].posts}
                self.assertEqual(requests["shape"], {"output_precision": precision,
                                                    "inference_quality": inference, "seed": 42})
                self.assertEqual(requests["export"]["texture_size"], 1024)
                inherited = run_job({"quality": "CUSTOM", "custom_base": mode,
                                     "custom": [override("export", "texture_size", 1024)]})
                self.assertEqual([p["params"] for p in inherited["server"].posts],
                                 [p["params"] for p in result["server"].posts])

    def test_disabled_overrides_do_not_affect_a_preset(self):
        result = run_job({"custom": [override("export", "texture_size", 1024)]})
        self.assertEqual(result["job"]["state"], "importing")
        self.assertNotIn("texture_size", result["server"].posts[-1]["params"])

    def test_hunyuan_keeps_native_standard_and_never_gets_trellis_geometry(self):
        result = run_job({"model": HUNYUAN, "seed": -1, "trellis_postprocess": "PRESERVE512",
                          "manual_overrides": True, "custom": [override("shape", "step", 8)]})
        self.assertEqual(result["job"]["state"], "importing", result["job"])
        self.assertEqual([p["stage"] for p in result["server"].posts], ["shape", "texture", "export"])
        self.assertEqual(result["server"].posts[0]["params"], {"step": 8})
        self.assertEqual(result["server"].posts[1]["params"], {})
        self.assertEqual(result["server"].posts[2]["params"], {})
        self.assertTrue(all(p["model"] == HUNYUAN for p in result["server"].posts))

    def test_preserve_profile_disables_decimation_unless_budget_selected(self):
        for budget in (0, 4, 2000000):
            with self.subTest(budget=budget):
                result = run_job({"faces": budget, "trellis_postprocess": "PRESERVE512"})
                self.assertEqual(result["job"]["state"], "importing", result["job"])
                params = next(p["params"] for p in result["server"].posts if p["stage"] == "simplify")
                self.assertEqual(params["remesh_resolution"], 512)
                self.assertEqual(params["remesh_closing_iterations"], 1)
                self.assertIs(params["project_geometry"], False)
                self.assertIs(params["simplify"], bool(budget))
                self.assertEqual(params.get("target_faces", 0), budget)
        for budget in (1, 3, 2000001):
            result = run_job({"faces": budget, "trellis_postprocess": "PRESERVE512"})
            self.assertEqual(result["job"]["state"], "failed")
            self.assertEqual(result["server"].posts, [])

    def test_manual_decimation_conflict_is_rejected_before_generation(self):
        result = run_job({"faces": 10000, "manual_overrides": True,
                          "custom": [override("simplify", "simplify", False)]})
        self.assertEqual(result["job"]["state"], "failed")
        self.assertEqual(result["server"].posts, [])

    def test_fresh_late_stage_bounds_and_enum_reject_before_any_task(self):
        cases = []
        caps = copy.deepcopy(TRELLIS_CAPS)
        caps["stage_specs"]["export"]["params"]["texture_size"]["anyOf"][0]["maximum"] = 1024
        cases.append((caps, override("export", "texture_size", 4096)))
        caps = copy.deepcopy(TRELLIS_CAPS)
        caps["stage_specs"]["export"]["params"]["bake_projection"]["anyOf"][0]["enum"] = ["vertex_fallback"]
        cases.append((caps, override("export", "bake_projection", "texel")))
        cases.append((TRELLIS_CAPS, override("export", "texture_size", 512.5)))
        for caps, custom in cases:
            with self.subTest(parameter=custom):
                result = run_job({"manual_overrides": True, "custom": [custom]}, capabilities=caps)
                self.assertEqual(result["server"].capability_reads, 1)
                self.assertEqual(result["server"].posts, [])
                self.assertEqual(result["job"]["state"], "failed")

    def test_removed_explicit_fields_reject_before_any_task(self):
        cases = (
            ("simplify", "target_faces", {"faces": 10000}),
            ("export", "texture_size", {"manual_overrides": True,
                                         "custom": [override("export", "texture_size", 1024)]}),
            ("simplify", "project_geometry", {"manual_overrides": True,
                                               "custom": [override("simplify", "project_geometry", False)]}),
        )
        for stage, parameter, configuration in cases:
            with self.subTest(stage=stage, parameter=parameter):
                caps = copy.deepcopy(TRELLIS_CAPS)
                caps["params"][stage].remove(parameter)
                del caps["stage_specs"][stage]["params"][parameter]
                result = run_job(configuration, capabilities=caps)
                self.assertEqual(result["server"].capability_reads, 1)
                self.assertEqual(result["job"]["state"], "failed", result["job"])
                self.assertEqual(result["server"].posts, [],
                                 "A removed explicit control must not trigger work with server defaults")

    def test_removed_but_disabled_overrides_do_not_block_a_job(self):
        caps = copy.deepcopy(TRELLIS_CAPS)
        caps["params"]["export"].remove("texture_size")
        del caps["stage_specs"]["export"]["params"]["texture_size"]
        result = run_job({"manual_overrides": False,
                          "custom": [override("export", "texture_size", 1024)]}, capabilities=caps)
        self.assertEqual(result["job"]["state"], "importing", result["job"])
        self.assertNotIn("texture_size", result["server"].posts[-1]["params"])

    def test_explicit_pipeline_wins_over_preset_alias_but_conflicts_are_errors(self):
        result = run_job({"quality": "DRAFT", "manual_overrides": True,
                          "custom": [override("shape", "pipeline_type", "1024")]})
        self.assertEqual(result["job"]["state"], "importing", result["job"])
        shape = result["server"].posts[0]["params"]
        self.assertEqual(shape["pipeline_type"], "1024")
        self.assertNotIn("output_precision", shape)
        self.assertEqual(shape["inference_quality"], "fast")
        conflict = run_job({"manual_overrides": True,
                            "custom": [override("shape", "pipeline_type", "1024"),
                                       override("quality", "output_precision", "draft")]})
        self.assertEqual(conflict["job"]["state"], "failed")
        self.assertEqual(conflict["server"].posts, [])

    def test_failed_final_output_never_substitutes_a_prior_mesh(self):
        output = {"shape": {"artifacts": [{"artifact_type": "shape", "artifact_id": "shape-ref"},
                                            {"artifact_type": "mesh_glb", "artifact_id": "shape-mesh"}]},
                  "export": {"artifacts": []}}
        result = run_job(outputs=output)
        self.assertIn("shape-mesh", result["server"].downloads)
        self.assertEqual(result["job"]["state"], "failed")
        self.assertIsNone(result["output"])
        self.assertEqual(result["report"]["status"], "failed")
        self.assertNotIn("selected_output", result["report"])

    def test_untextured_final_preview_is_selected_from_the_correct_stage(self):
        for profile, stage, expected in (("OFF", "shape", SHAPE_GLB),
                                          ("PRESERVE512", "simplify", GEOMETRY_GLB)):
            with self.subTest(profile=profile):
                result = run_job({"texture": False, "trellis_postprocess": profile})
                self.assertEqual(result["job"]["state"], "importing", result["job"])
                self.assertEqual(result["output"], expected)
                self.assertEqual(result["report"]["selected_output"]["stage"], stage)
                self.assertTrue(result["report"]["selected_output"]["artifact_type"].endswith("_preview"))
                self.assertNotIn("texture", [p["stage"] for p in result["server"].posts])

    def test_optional_preview_failure_does_not_discard_a_valid_final_glb(self):
        result = run_job({"trellis_postprocess": "PRESERVE512", "save_stage_previews": True},
                         failed_downloads={"shape-preview"})
        self.assertEqual(result["job"]["state"], "importing", result["job"])
        self.assertEqual(result["output"], FINAL_GLB)
        shape = result["report"]["stage_diagnostics"][0]
        self.assertEqual(shape["saved_previews"][0]["status"], "unavailable")
        self.assertTrue(result["saved_previews"])

    def test_reports_capture_exact_requests_references_hashes_and_no_connection_secrets(self):
        result = run_job({"trellis_postprocess": "PRESERVE512", "save_stage_previews": True})
        self.assertEqual(result["job"]["state"], "importing", result["job"])
        report = result["report"]
        self.assertEqual(report["status"], "saved")
        for request, trace in zip(result["server"].posts, report["stage_diagnostics"]):
            self.assertEqual(request["params"], trace["sent_params"])
            self.assertEqual(request["input_refs"], trace["input_refs"])
            self.assertEqual(report["params_by_stage"][request["stage"]], trace["sent_params"])
        exported = result["server"].posts[-1]["input_refs"]
        self.assertEqual(exported["geometry_artifact"], {"task_id": "task-2", "artifact_id": "geometry-ref"})
        self.assertEqual(exported["shape_artifact"], {"task_id": "task-1", "artifact_id": "shape-ref"})
        self.assertEqual(exported["material_artifact"], {"task_id": "task-3", "artifact_id": "material-ref"})
        self.assertEqual(report["source_sha256"], result["source_sha256"])
        self.assertEqual(report["input_image_sha256"], result["source_sha256"])
        self.assertEqual(report["output_sha256"], hashlib.sha256(FINAL_GLB).hexdigest())
        self.assertEqual(report["geometry_counts"], {"triangles": 1, "vertices_with_seams": 3})
        self.assertEqual(report["selected_output"], {"stage": "export", "task_id": "task-4",
                                                    "artifact_id": "final-glb", "artifact_type": "mesh_glb"})
        self.assertEqual(report["stage_diagnostics"][0]["server_reported_controls"], {"task.metadata": {"seed": 42}})
        self.assertEqual(result["progress"], sorted(result["progress"]))
        self.assertEqual(result["progress"][-1], 99)
        for forbidden in (result["configuration"]["key"], result["configuration"]["base"], result["temporary"]):
            self.assertNotIn(forbidden, result["report_text"])

    def test_seed_minus_one_is_omitted_and_not_claimed_as_an_effective_seed(self):
        result = run_job({"seed": -1})
        self.assertEqual(result["job"]["state"], "importing", result["job"])
        self.assertTrue(all("seed" not in p["params"] for p in result["server"].posts))
        self.assertIsNone(result["report"]["seed_sent"])
        self.assertEqual(result["report"]["seed"], -1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
