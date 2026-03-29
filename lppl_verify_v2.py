#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import src.cli.lppl_verify_v2 as _impl

analyze_peak = _impl.analyze_peak
analyze_peak_ensemble = _impl.analyze_peak_ensemble
find_local_highs = _impl.find_local_highs
generate_verification_artifacts = _impl.generate_verification_artifacts
main = _impl.main
SYMBOLS = _impl.SYMBOLS


def run_verification(*args, **kwargs):
    _impl.find_local_highs = find_local_highs
    _impl.analyze_peak = analyze_peak
    _impl.analyze_peak_ensemble = analyze_peak_ensemble
    return _impl.run_verification(*args, **kwargs)


def __getattr__(name):
    return getattr(_impl, name)


if __name__ == "__main__":
    main()
