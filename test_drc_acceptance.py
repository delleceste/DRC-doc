"""Regression tests for acceptance estimator v2; run with unittest."""
import unittest
from unittest.mock import patch

import numpy as np

import drc_acceptance as d


class AcceptanceTests(unittest.TestCase):
    def test_rebound_is_not_settled(self):
        env = np.zeros(1000)
        env[:10] = 1
        env[500:600] = .02
        self.assertEqual(d._settling_ms(env, .01, 1000, 50), 600)
        self.assertTrue(np.isnan(d._settling_ms(env[:620], .01, 1000, 50)))

    def test_censoring_is_preserved(self):
        med, iqr, count = d._tail_statistics([10, 20, 30, 40, 90] + [np.nan] * 4)
        self.assertEqual(med, 90)
        self.assertTrue(np.isinf(iqr))
        self.assertEqual(count, 4)
        self.assertTrue(np.isinf(d._tail_statistics([1] * 4 + [np.nan] * 5)[0]))

    def test_explicit_gate_phase_coverage(self):
        with patch.object(d, '_gated_tail_once', return_value=10) as once:
            d.gated_tail(np.array([1.]), 8000, 100)
        phases = [call.kwargs['phase'] for call in once.call_args_list]
        self.assertEqual(len(phases), 9)
        np.testing.assert_allclose(np.diff(phases), 2 * np.pi / 9)

    def test_delayed_echo_cannot_pass(self):
        h = np.zeros(8192)
        h[0], h[4000] = 1, .015
        tail = d.gated_tail(h, 8000, 100)
        self.assertGreater(tail, 450)
        with patch.object(d, 'read_wav', return_value=(h, 8000)):
            ok, result = d.check('synthetic', verbose=False)
        self.assertFalse(ok)
        np.testing.assert_array_equal(result['h'], h)

    def test_echo_beyond_two_seconds_is_observed(self):
        h = np.zeros(21001)
        h[0], h[20000] = 1, .03
        self.assertGreater(d.gated_tail(h, 8000, 100), 2400)

    def test_late_echo_not_wrapped_to_prering(self):
        h = np.zeros(8192)
        h[0], h[7000] = 1, .02
        self.assertGreater(d.gated_tail(h, 8000, 100), 800)

    def test_limit_adds_the_control_and_never_scales_it(self):
        # The control is the noisiest quantity in the test -- at 79 Hz its nine
        # gate phases spanned 2-54 ms while the filter's spanned 105-125.  A
        # limit proportional to it tracked that noise into the verdict, so
        # equal steps in the control must produce equal steps in the limit.
        steps = [d.tail_limit(79.0, c) for c in (0.0, 30.0, 60.0, 90.0)]
        np.testing.assert_allclose(np.diff(steps), 30.0)
        # An at-the-floor filter passes at every tone, however large the floor.
        for tone in d.TONES:
            for control in (0.0, 5.0, 35.0, 132.0):
                self.assertGreater(d.tail_limit(tone, control), control)

    def test_four_period_floor_binds_only_where_control_is_small(self):
        self.assertEqual(d.tail_limit(28.7, 0.0), 4000.0 / 28.7)
        self.assertEqual(d.tail_limit(28.7, 132.0), d.MAX_EXCESS_MS + 132.0)
        self.assertEqual(d.tail_limit(180.0, 5.7), d.MAX_EXCESS_MS + 5.7)

    def test_pure_delay_control_and_zero_padding_invariant(self):
        h = np.zeros(8192)
        h[0], h[4000] = 1, .015
        padded = np.pad(h, (20000, 60000))
        self.assertEqual(d.gated_tail(h, 8000, 100), d.gated_tail(padded, 8000, 100))
        self.assertEqual(d.group_delay_excursion(h, 8000),
                         d.group_delay_excursion(padded, 8000))
        delta = np.array([1., 0.])
        with patch.object(d, 'read_wav', return_value=(delta, 8000)):
            self.assertTrue(d.check('delta', verbose=False)[0])


if __name__ == '__main__':
    unittest.main()
