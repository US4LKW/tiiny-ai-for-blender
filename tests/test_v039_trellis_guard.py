"""Exercise the resolution opt-in at the real worker/transport boundary.

The fake server advertises the captured device schema and returns valid GLB
artifacts. These checks prove request gating and preservation of explicit
settings; they do not prove that 1024 generation is reliable on a Tiiny device.
"""
import unittest
from unittest import mock

import test_v030_profiles as contract


class TrellisResolutionGuardContracts(unittest.TestCase):
    def run_with_guard_spy(self, configuration):
        """Observe the real guard, retaining its validation and exceptions."""
        with mock.patch.object(contract.addon, "_check_trellis_resolution",
                               wraps=contract.addon._check_trellis_resolution) as guard:
            result = contract.run_job(configuration)
        self.assertEqual(guard.call_count, 1,
                         "The generation worker must invoke the real resolution guard")
        self.assertEqual(result["server"].capability_reads, 1)
        return result, guard.call_args.args[2]

    def assert_blocked_before_post(self, result):
        self.assertEqual(result["job"]["state"], "failed", result["job"])
        self.assertEqual(result["server"].posts, [],
                         "An unapproved resolution must not start a remote task")
        self.assertIsNone(result["output"])
        self.assertIn("1024", result["job"]["error"])
        self.assertIn("experimental", result["job"]["error"].lower())
        self.assertIsNotNone(result["report"],
                             "A blocked job should retain its diagnostic report")
        self.assertEqual(result["report"]["status"], "failed")

    def test_maximum_is_blocked_when_opt_in_is_false(self):
        result, parameters = self.run_with_guard_spy({
            "quality": "MAXIMUM", "allow_trellis_1024": False,
        })
        self.assert_blocked_before_post(result)
        self.assertEqual(parameters["shape"]["output_precision"], "high",
                         "Maximum must be blocked, not silently reduced to 512")
        self.assertEqual(result["report"]["params_by_stage"], parameters)

    def test_missing_opt_in_setting_defaults_to_blocking_in_worker(self):
        # The shared harness opts into high resolution for older positive
        # contract tests. Remove that helper default to exercise a real caller
        # that predates the new setting.
        original_settings = contract.settings

        def without_opt_in(**changes):
            configuration = original_settings(**changes)
            configuration.pop("allow_trellis_1024", None)
            return configuration

        with mock.patch.object(contract, "settings", side_effect=without_opt_in):
            result, parameters = self.run_with_guard_spy({"quality": "MAXIMUM"})
        self.assertNotIn("allow_trellis_1024", result["configuration"])
        self.assert_blocked_before_post(result)
        self.assertEqual(parameters["shape"]["output_precision"], "high")

    def test_opt_in_preserves_exact_maximum_stage_requests(self):
        result, parameters = self.run_with_guard_spy({
            "quality": "MAXIMUM", "allow_trellis_1024": True,
        })
        self.assertEqual(result["job"]["state"], "importing", result["job"])
        expected = {
            "shape": {"output_precision": "high", "inference_quality": "quality", "seed": 42},
            "texture": {"inference_quality": "quality", "seed": 42},
            "export": {"asset_quality": "quality"},
        }
        requests = {post["stage"]: post["params"] for post in result["server"].posts}
        self.assertEqual(requests, expected)
        self.assertEqual(parameters, expected)
        self.assertEqual(result["report"]["params_by_stage"], expected)
        self.assertTrue(result["report"]["allow_trellis_1024"])
        self.assertEqual(result["output"], contract.FINAL_GLB)

    def test_custom_inheriting_maximum_cannot_bypass_opt_in(self):
        result, parameters = self.run_with_guard_spy({
            "quality": "CUSTOM", "custom_base": "MAXIMUM", "allow_trellis_1024": False,
        })
        self.assert_blocked_before_post(result)
        self.assertEqual(parameters["shape"]["output_precision"], "high")

    def test_explicit_1024_pipeline_cannot_bypass_opt_in(self):
        result, parameters = self.run_with_guard_spy({
            "quality": "DRAFT", "allow_trellis_1024": False, "manual_overrides": True,
            "custom": [contract.override("shape", "pipeline_type", "1024")],
        })
        self.assert_blocked_before_post(result)
        self.assertEqual(parameters["shape"], {
            "pipeline_type": "1024", "inference_quality": "fast", "seed": 42,
        })

    def test_manual_high_precision_cannot_bypass_opt_in(self):
        result, parameters = self.run_with_guard_spy({
            "quality": "DRAFT", "allow_trellis_1024": False, "manual_overrides": True,
            "custom": [contract.override("quality", "output_precision", "high")],
        })
        self.assert_blocked_before_post(result)
        self.assertEqual(parameters["shape"], {
            "output_precision": "high", "inference_quality": "fast", "seed": 42,
        })

    def test_explicit_512_pipeline_overrides_maximum_and_is_allowed(self):
        result, parameters = self.run_with_guard_spy({
            "quality": "MAXIMUM", "allow_trellis_1024": False, "manual_overrides": True,
            "custom": [contract.override("shape", "pipeline_type", "512")],
        })
        self.assertEqual(result["job"]["state"], "importing", result["job"])
        expected_shape = {"pipeline_type": "512", "inference_quality": "quality", "seed": 42}
        self.assertEqual(parameters["shape"], expected_shape)
        self.assertEqual(result["server"].posts[0]["params"], expected_shape)
        self.assertEqual(contract.addon._resolved_trellis_resolution(contract.TRELLIS_CAPS, parameters), 512)
        self.assertEqual(result["output"], contract.FINAL_GLB)

    def test_hunyuan_maximum_is_unaffected_by_trellis_opt_in(self):
        result, parameters = self.run_with_guard_spy({
            "model": contract.HUNYUAN, "quality": "MAXIMUM", "allow_trellis_1024": False,
        })
        self.assertEqual(result["job"]["state"], "importing", result["job"])
        expected = {"output_precision": "high", "inference_quality": "quality",
                    "asset_quality": "quality", "seed": 42}
        self.assertEqual(parameters, {stage: expected for stage in ("shape", "texture", "export")})
        self.assertEqual([post["stage"] for post in result["server"].posts],
                         ["shape", "texture", "export"])
        self.assertTrue(all(post["params"] == expected and post["model"] == contract.HUNYUAN
                            for post in result["server"].posts))

    def test_native_server_default_resolution_stays_unknown(self):
        result, parameters = self.run_with_guard_spy({
            "quality": "CUSTOM", "custom_base": "NATIVE", "allow_trellis_1024": False,
        })
        self.assertEqual(result["job"]["state"], "importing", result["job"])
        self.assertEqual(parameters["shape"], {"seed": 42})
        self.assertIsNone(contract.addon._resolved_trellis_resolution(contract.TRELLIS_CAPS, parameters),
                          "An omitted device default must not be described as verified 512")
        self.assertEqual(result["server"].posts[0]["params"], {"seed": 42})
        self.assertEqual(result["report"]["params_by_stage"]["shape"], {"seed": 42})


if __name__ == "__main__":
    unittest.main(verbosity=2)
