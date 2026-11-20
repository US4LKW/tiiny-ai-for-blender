"""A stage's explicit quality enum must constrain the actual stage request.

This simulates a device that changes texture support while retaining its broader
model-level quality list. It does not exercise a physical Tiiny device.
"""
import copy
import unittest

import test_v030_profiles as contract


class StageSchemaContracts(unittest.TestCase):
    def narrowed_texture_caps(self):
        caps = copy.deepcopy(contract.TRELLIS_CAPS)
        caps["stage_specs"]["texture"]["params"]["inference_quality"]["anyOf"][0]["enum"] = ["balance", "quality"]
        return caps

    def test_narrowed_texture_enum_rejects_draft_before_any_post(self):
        result = contract.run_job({"quality": "DRAFT"}, capabilities=self.narrowed_texture_caps())
        self.assertEqual(result["job"]["state"], "failed", result["job"])
        self.assertEqual(result["server"].posts, [],
                         "All stages must validate before shape generation starts")
        self.assertIn("texture.inference_quality", result["job"]["error"])

    def test_valid_standard_and_maximum_tiers_still_route_to_each_stage(self):
        for mode, precision, inference, asset in (
            ("STANDARD", "standard", "balance", "balance"),
            ("MAXIMUM", "high", "quality", "quality"),
        ):
            with self.subTest(mode=mode):
                result = contract.run_job({"quality": mode}, capabilities=self.narrowed_texture_caps())
                self.assertEqual(result["job"]["state"], "importing", result["job"])
                requests = {post["stage"]: post["params"] for post in result["server"].posts}
                self.assertEqual(requests["shape"], {"output_precision": precision,
                                                    "inference_quality": inference, "seed": 42})
                self.assertEqual(requests["texture"], {"inference_quality": inference, "seed": 42})
                self.assertEqual(requests["export"], {"asset_quality": asset})

    def test_names_only_stage_entry_retains_global_validation(self):
        caps = copy.deepcopy(contract.TRELLIS_CAPS)
        caps["stage_specs"]["texture"]["params"]["inference_quality"] = {}
        contract.addon._validate_stage_params(caps, "texture", {"inference_quality": "fast"})
        with self.assertRaises(ValueError):
            contract.addon._validate_stage_params(caps, "texture", {"inference_quality": "unadvertised"})

    def test_hunyuan_without_stage_specs_keeps_existing_parameter_contract(self):
        for mode, expected in (
            ("STANDARD", {"seed": 42}),
            ("DRAFT", {"output_precision": "draft", "inference_quality": "fast",
                       "asset_quality": "fast", "seed": 42}),
            ("MAXIMUM", {"output_precision": "high", "inference_quality": "quality",
                         "asset_quality": "quality", "seed": 42}),
        ):
            with self.subTest(mode=mode):
                cfg = contract.settings(model=contract.HUNYUAN, quality=mode)
                stages, parameters = contract.addon._execution_plan(contract.HUNYUAN_CAPS, cfg, mode)
                self.assertEqual(stages, ["shape", "texture", "export"])
                self.assertEqual(parameters, {stage: expected for stage in stages})


if __name__ == "__main__":
    unittest.main(verbosity=2)
