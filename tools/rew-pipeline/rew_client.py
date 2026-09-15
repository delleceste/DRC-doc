"""Thin client for the REW REST API (https://www.roomeqwizard.com/help/help/html/api.html).

Only what the inversion pipeline needs: measurement listing/lookup, IR window
settings, minimum-phase generation, arithmetic/averaging process commands,
trim-to-window, and impulse-response retrieval as float arrays. No external
dependencies beyond numpy.
"""
from __future__ import annotations

import base64
import json
import math
import time
import urllib.request
from urllib.error import HTTPError, URLError

import numpy as np


class RewError(RuntimeError):
    pass


class RewClient:
    def __init__(self, url='http://127.0.0.1:4735', timeout=30):
        self.url = url.rstrip('/')
        self.timeout = timeout

    # -- transport --------------------------------------------------------
    def _request(self, method, path, body=None):
        data = json.dumps(body).encode('utf-8') if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method)
        if data is not None:
            req.add_header('Content-Type', 'application/json')
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else None
        except HTTPError as e:
            detail = e.read().decode('utf-8', 'replace')
            raise RewError(f'{method} {path} -> HTTP {e.code}: {detail}') from None
        except URLError as e:
            raise RewError(
                f'Cannot reach REW API at {self.url} ({e.reason}). '
                'Start REW with the API enabled (API preferences, or -api argument).'
            ) from None

    def get(self, path):
        return self._request('GET', path)

    def post(self, path, body=None):
        return self._request('POST', path, body if body is not None else {})

    def put(self, path, body):
        return self._request('PUT', path, body)

    def delete(self, path):
        return self._request('DELETE', path)

    def ping(self):
        self.get('/application/blocking')

    def set_blocking(self, enabled=True):
        self.post('/application/blocking', enabled)

    # -- measurements -------------------------------------------------------
    def measurements(self):
        """{index_str: summary} for every currently loaded measurement."""
        return self.get('/measurements') or {}

    def measurement(self, index):
        """Return the full summary for a measurement UUID or index."""
        return self.get(f'/measurements/{index}')

    def titles(self):
        return {v['title']: k for k, v in self.measurements().items()}

    def find(self, title):
        """Return the UUID of the measurement with this exact title.

        Returns the measurement's UUID, not its index: indices shift whenever
        anything is added to or removed from the loaded set, which happens
        throughout this pipeline, so a value handed back from one step and
        used several steps later must stay valid across those insertions and
        deletions. UUIDs do not change.

        Raises if zero or more than one match, since a stale duplicate title
        from a previous run would otherwise silently pick the wrong trace.
        """
        hits = [v['uuid'] for v in self.measurements().values() if v['title'] == title]
        if not hits:
            raise RewError(f'No measurement named {title!r}')
        if len(hits) > 1:
            raise RewError(f'{len(hits)} measurements named {title!r}, expected 1: {hits}')
        return hits[0]

    def rename(self, index, title):
        self.put(f'/measurements/{index}', {'title': title})

    def set_notes(self, index, notes):
        self.put(f'/measurements/{index}', {'notes': notes})

    def delete_measurement(self, index):
        self.delete(f'/measurements/{index}')

    def delete_all_measurements(self):
        self.delete('/measurements')

    def load(self, *mdat_paths):
        self.post('/measurements/command', {
            'command': 'Load',
            'parameters': [str(p) for p in mdat_paths],
        })

    def save_all(self, path, note=None):
        """Write every loaded measurement to one .mdat.

        The API has no WAV export -- `Save` refuses any extension but
        .mdat -- so this is the handoff for anyone who needs REW's own
        exporter: save the session, open it in the GUI, export the
        impulse responses from there. Those bytes cannot be reproduced
        over the API (see RewClient.impulse_response).
        """
        params = [str(path)] + ([note] if note else [])
        self.post('/measurements/command', {'command': 'Save all', 'parameters': params})

    # -- commands that create a new measurement ------------------------------
    # Every method here returns the new measurement's UUID (see `find`'s
    # docstring for why index numbers are not used across calls).
    def _new_uuid_since(self, before_uuids):
        after = self.measurements()
        new = [v['uuid'] for v in after.values() if v['uuid'] not in before_uuids]
        if len(new) != 1:
            raise RewError(f'Expected exactly one new measurement, got {new}')
        return new[0]

    def command(self, uuid, command, parameters=None, rename_to=None):
        """POST an individual-measurement command; returns new UUID if one appears."""
        before = {v['uuid'] for v in self.measurements().values()}
        body = {'command': command}
        if parameters is not None:
            body['parameters'] = parameters
        self.post(f'/measurements/{uuid}/command', body)
        after = {v['uuid'] for v in self.measurements().values()}
        new = list(after - before)
        if not new:
            return None
        if len(new) > 1:
            raise RewError(f'Expected at most one new measurement from {command!r}, got {new}')
        result = new[0]
        if rename_to is not None:
            self.rename(result, rename_to)
        return result

    def process(self, process_name, uuids, parameters=None, rename_to=None):
        """POST /measurements/process-measurements; returns new UUID."""
        before = {v['uuid'] for v in self.measurements().values()}
        body = {'processName': process_name, 'measurementUUIDs': list(uuids)}
        if parameters is not None:
            body['parameters'] = parameters
        self.post('/measurements/process-measurements', body)
        result = self._new_uuid_since(before)
        if rename_to is not None:
            self.rename(result, rename_to)
        return result

    def minimum_phase_version(self, index, include_cal, lf_tail=None, hf_tail=None,
                               frequency_warping=False, replicate_data=False, rename_to=None):
        """lf_tail/hf_tail: (start_hz, slope_db_per_oct) or None to disable."""
        params = {'include cal': bool(include_cal)}
        params['append lf tail'] = lf_tail is not None
        if lf_tail is not None:
            params['lf tail start'] = lf_tail[0]
            params['lf tail slope'] = lf_tail[1]
        params['append hf tail'] = hf_tail is not None
        if hf_tail is not None:
            params['hf tail start'] = hf_tail[0]
            params['hf tail slope'] = hf_tail[1]
            params['frequency warping'] = bool(frequency_warping)
        if lf_tail is None or hf_tail is None:
            params['replicate data'] = bool(replicate_data)
        return self.command(index, 'Minimum phase version', params, rename_to=rename_to)

    def arithmetic(self, function, index_a, index_b, max_gain=None, lower_limit=None,
                   upper_limit=None, rename_to=None):
        params = {'function': function}
        if max_gain is not None:
            params['maxGain'] = max_gain
        if lower_limit is not None:
            params['lowerLimit'] = lower_limit
        if upper_limit is not None:
            params['upperLimit'] = upper_limit
        return self.process('Arithmetic', [index_a, index_b], params, rename_to=rename_to)

    def vector_average(self, indices, rename_to=None):
        return self.process('Vector average', indices, rename_to=rename_to)

    def rms_average(self, indices, rename_to=None):
        return self.process('RMS average', indices, rename_to=rename_to)

    def trim_to_windows(self, index, rename_to=None):
        return self.command(index, 'Trim IR to windows', rename_to=rename_to)

    def response_copy(self, index, rename_to=None):
        """Freeze a snapshot of a measurement's current response as a new,
        independent measurement -- used here to keep a no-FDW copy of a raw
        capture around after FDW is enabled in place on the original.
        """
        return self.command(index, 'Response copy', rename_to=rename_to)

    def add_spl_offset(self, index, offset_db):
        """Modifies the measurement in place (no new measurement)."""
        self.command(index, 'Add SPL offset', {'offset': offset_db})

    def import_impulse_response(self, path, channels='All', rename_to=None, timeout=30, poll=0.3):
        """POST /import/impulse-response and wait for the resulting new
        measurement (import is queued/async, not a `command`, so it is not
        covered by blocking mode -- poll the measurement list instead).
        """
        before = {v['uuid'] for v in self.measurements().values()}
        self.post('/import/impulse-response', {'path': str(path), 'channels': channels})
        deadline = time.time() + timeout
        while time.time() < deadline:
            after = {v['uuid'] for v in self.measurements().values()}
            new = list(after - before)
            if new:
                if len(new) > 1:
                    raise RewError(f'Import of {path} produced more than one measurement: {new}')
                if rename_to is not None:
                    self.rename(new[0], rename_to)
                return new[0]
            time.sleep(poll)
        raise RewError(f'Timed out waiting for import of {path}')

    # -- target / EQ ----------------------------------------------------------
    def target_settings(self, index):
        return self.get(f'/measurements/{index}/target-settings')

    def target_level(self, index):
        return float(self.get(f'/measurements/{index}/target-level'))

    def set_target_settings(self, index, **fields):
        # PUT is the API's partial-update operation. POST replaces the full
        # settings object and can reset fields which this pipeline deliberately
        # leaves alone.
        self.put(f'/measurements/{index}/target-settings', fields)
        actual = self.target_settings(index)
        mismatches = {key: (value, actual.get(key)) for key, value in fields.items()
                      if actual.get(key) != value}
        if mismatches:
            raise RewError(f'REW did not retain requested target settings: {mismatches}')

    def eq_command(self, index, command):
        """POST to /measurements/:id/eq/command -- 'Calculate target level',
        'Generate target measurement', etc. None of these commands take
        parameters. 'Generate target measurement' creates a new measurement.
        """
        before = {v['uuid'] for v in self.measurements().values()}
        self.post(f'/measurements/{index}/eq/command', {'command': command})
        after = {v['uuid'] for v in self.measurements().values()}
        new = list(after - before)
        if len(new) > 1:
            raise RewError(f'Expected at most one new measurement from {command!r}, got {new}')
        return new[0] if new else None

    def filters(self, index):
        return self.get(f'/measurements/{index}/filters')

    def set_filters(self, index, filters):
        """Replace the enabled EQ rows on a measurement.

        ``filters`` is a sequence of REW FilterSetting dictionaries. Rows not
        supplied are reset to ``None`` so a source session's manual EQ cannot
        leak into an automated build.
        """
        capacity = len(self.filters(index))
        if len(filters) > capacity:
            raise RewError(f'Equaliser offers {capacity} rows, got {len(filters)} filters')
        rows = []
        for i in range(1, capacity + 1):
            if i <= len(filters):
                rows.append({'index': i, 'enabled': True, 'isAuto': False,
                             **filters[i - 1]})
            else:
                rows.append({'index': i, 'type': 'None', 'enabled': True, 'isAuto': True})
        self.post(f'/measurements/{index}/filters', {'filters': rows})
        actual = self.filters(index)
        for expected, got in zip(rows[:len(filters)], actual[:len(filters)]):
            for key, value in expected.items():
                if got.get(key) != value:
                    raise RewError(f'REW did not retain filter setting {expected}: got {got}')

    def generate_filters_measurement(self, index, filters, rename_to=None):
        """Install explicit EQ rows and generate their standalone response."""
        self.set_filters(index, filters)
        result = self.eq_command(index, 'Generate filters measurement')
        if result is None:
            raise RewError('Generate filters measurement produced no measurement')
        if rename_to is not None:
            self.rename(result, rename_to)
        return result

    def house_curve(self, path, log_interpolation=True):
        """Set (or, with an empty string, clear) the house curve file path.

        The log-interpolation flag must be set before the path, per the API
        docs, and there is no way to read back whatever it was left at by a
        previous session -- so this always sets it explicitly rather than
        leaving it at an unknown prior value.
        """
        self.post('/eq/house-curve-log-interpolation', bool(log_interpolation))
        self.post('/eq/house-curve', str(path))

    # -- IR window / FDW -----------------------------------------------------
    def ir_windows(self, index):
        return self.get(f'/measurements/{index}/ir-windows')

    def set_fdw(self, index, cycles):
        """Enable FDW without changing widths, shapes, or reference time."""
        # The OpenAPI description distinguishes POST (change settings) from
        # PUT (change *some* settings). The guide requires the other window
        # fields, especially each measurement's ref time, to be preserved.
        before = self.ir_windows(index)
        self.put(f'/measurements/{index}/ir-windows', {
            'addFDW': True,
            'fdwWidthCycles': float(cycles),
        })
        after = self.ir_windows(index)
        preserved = ('leftWindowType', 'rightWindowType', 'leftWindowWidthms',
                     'rightWindowWidthms', 'refTimems')
        changed = {key: (before.get(key), after.get(key)) for key in preserved
                   if before.get(key) != after.get(key)}
        if changed:
            raise RewError(f'REW changed non-FDW window fields while setting FDW: {changed}')
        if not after.get('addFDW') or not math.isclose(
                float(after.get('fdwWidthCycles', float('nan'))), float(cycles),
                rel_tol=0.0, abs_tol=1e-6):
            raise RewError(f'REW did not retain requested FDW {cycles:g} cycles: {after}')

    def disable_fdw(self, index):
        self.put(f'/measurements/{index}/ir-windows', {'addFDW': False})

    # -- data retrieval -------------------------------------------------------
    @staticmethod
    def _decode_floats(b64):
        return np.frombuffer(base64.b64decode(b64), dtype='>f4').astype(np.float32)

    def impulse_response(self, index, windowed=False, normalised=False, unit='percent'):
        """Returns (sample_rate, float32 ndarray of amplitude, start_time_s).

        `windowed=False` by default, and that matters: on a measurement that
        has already been through `Trim IR to windows`, asking for the
        windowed data makes REW apply the window a *second* time. Measured
        against REW's own GUI WAV export of the same measurement, that
        costs a 1.0000007 scale error, up to 2.6e-5 of absolute deviation,
        and zeroes the first and last sample outright (the window's end
        taps); `windowed=False` returns the same span to within 9.3e-9.

        The remaining deviation is the transport itself and cannot be
        removed: `percent` is the only linear unit the endpoint offers, so
        values arrive as float32(x*100) and dividing by 100 is not exactly
        invertible -- 27% of samples have several float32 values that all
        encode to the same transmitted number. Bit-identical retrieval of
        what REW's own exporter writes is therefore impossible via the API,
        independent of how correct the processing chain is.
        """
        path = (f'/measurements/{index}/impulse-response'
                f'?windowed={"true" if windowed else "false"}'
                f'&normalised={"true" if normalised else "false"}'
                f'&unit={unit}')
        resp = self.get(path)
        data = self._decode_floats(resp['data'])
        if unit == 'percent':
            data = data / 100.0
        return resp['sampleRate'], data, resp.get('startTime', 0.0)

    def frequency_response(self, index, unit='SPL', ppo=96, smoothing=None):
        path = f'/measurements/{index}/frequency-response?unit={unit}&ppo={ppo}'
        if smoothing is not None:
            path += f'&smoothing={smoothing}'
        resp = self.get(path)
        mag = self._decode_floats(resp['magnitude'])
        return resp['startFreq'], resp['ppo'], mag
