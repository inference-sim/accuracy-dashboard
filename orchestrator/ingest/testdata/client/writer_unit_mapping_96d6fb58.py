import math


def apply_unit_mapping(benchmark, data):
    for key, value in benchmark.items():
        if key.endswith("ms") and math.isfinite(float(value)):
            data[key.replace("_ms", "")] = float(value) / 1000.0
        if "tpot" in key and math.isfinite(float(value)) and float(value) > 0:
            data[key.replace("_ms", "").replace("tpot", "intvty")] = 1000.0 / float(value)
    return data
