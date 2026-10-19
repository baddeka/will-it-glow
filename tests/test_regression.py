"""Regression check: did pulling the constants out of the code change any number?

tests/baseline_km83_pre_refactor.txt was captured from the single-case version
before any of this refactor existed, with Km at the alternative-buffer value of
83 uM that the old DEFAULTS carried as a literal.

This test re-runs the same seventeen scripts against the refactored model with
Km pinned back to that same alternative-buffer row of sensors.csv, and demands
byte-identical output. Agreement means the refactor moved constants without
touching physics. The pinned Km is read out of sensors.csv, not written here,
so this file contains no enzyme constant either.

Two chassis constants are pinned alongside it, for a different reason. The
baseline is a historical artefact: it records what the physics did under the
constants the project held in 2026-10. Two of those have since been replaced by
published measurements - the cell volume per OD600 and the sfGFP maturation
half-life, both roughly a factor off what the file used to carry. Repinning them
here keeps this test doing its one job, which is to prove the refactor did not
touch the physics, and stops it doubling as a freeze on the data files. A change
to data/platform.csv should be free to move the model's answers; a change to
das_model.py should not.

    python tests/test_regression.py            all scripts, a few minutes
    python tests/test_regression.py --quick    skips the slow parameter sweeps

Exit status is 0 when every script matches.
"""
import contextlib
import io
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BASELINE = os.path.join(HERE, "baseline_km83_pre_refactor.txt")
SLOW = {"ceiling.py", "fixed_plasmid.py", "robustness.py"}

sys.path.insert(0, ROOT)
os.chdir(ROOT)

import das_model  # noqa: E402  (after the path fix)
from sensorlab import data  # noqa: E402


def baseline_sections(path):
    """Split the frozen baseline into {script name: its stdout}."""
    sections, name, buf = {}, None, []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("######## "):
                if name:
                    sections[name] = "".join(buf)
                name, buf = line.strip().strip("# ").strip(), []
            elif name:
                buf.append(line)
    if name:
        sections[name] = "".join(buf)
    return sections


def alt_buffer_km():
    """The Km the pre-refactor DEFAULTS used, taken from its row in sensors.csv."""
    sc = data.load_scenarios()["das_reference"]
    rows = [s for s in data.load_sensors()
            if s.biomarker == sc["sensor_biomarker"]
            and s.protein_name.startswith(sc["sensor_protein"])
            and s.protein_name != sc["sensor_protein"]]
    if len(rows) != 1:
        raise SystemExit("expected exactly one alternative row for %s; found %d"
                         % (sc["sensor_protein"], len(rows)))
    return rows[0].km_uM, rows[0].protein_name


# The chassis values the baseline was captured under. They are written here
# rather than read from a file on purpose: the point of a baseline is that it
# does not move when the data files do.
PRE_REFACTOR = {
    "phi_per_OD": 8e-4,                   # now 3.6e-3, Volkmer & Heinemann 2011
    "gfp_maturation_halflife_s": 360.0,   # now 2166 s, wild-type GFP
    "v_healthy": 150.0,                   # now 100, Hiramatsu et al. 2014, male
    "v_cutoff": 250.0,                    # now 210, Nakayama et al. 2012, male
}


def pin_chassis():
    """Restore the constants the baseline was recorded under, and say which."""
    import math
    moved = []
    for name, old in sorted(PRE_REFACTOR.items()):
        now = das_model.DEFAULTS.get(name)
        if now is not None and abs(now - old) > 1e-12 * max(abs(old), 1.0):
            moved.append("%s %g -> %g" % (name, old, now))
        das_model.DEFAULTS[name] = old
    # the two that are derived from a half-life have to follow it back
    das_model.DEFAULTS["k_mat"] = (
        math.log(2.0) / PRE_REFACTOR["gfp_maturation_halflife_s"])
    return moved


def run_script(name):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        runpy.run_path(os.path.join(ROOT, name), run_name="__main__")
    return out.getvalue()


def main():
    quick = "--quick" in sys.argv
    km, protein = alt_buffer_km()
    das_model.DEFAULTS["Km"] = km
    print("pinning Km to %.1f uM from the %r row of sensors.csv" % (km, protein))
    for line in pin_chassis():
        print("pinning back to the value the baseline was recorded under: %s"
              % line)
    print("comparing against %s\n" % os.path.basename(BASELINE))

    sections = baseline_sections(BASELINE)
    failed, skipped = [], []

    for name in sections:
        if quick and name in SLOW:
            skipped.append(name)
            continue
        try:
            got = run_script(name)
        except Exception as exc:                      # noqa: BLE001
            print("  FAIL  %-20s raised %s: %s" % (name, type(exc).__name__, exc))
            failed.append(name)
            continue

        want = sections[name]
        if got.strip() == want.strip():
            print("  ok    %-20s %d lines" % (name, len(want.splitlines())))
        else:
            failed.append(name)
            print("  FAIL  %-20s output differs" % name)
            g, w = got.strip().splitlines(), want.strip().splitlines()
            for i, (a, b) in enumerate(zip(w, g)):
                if a != b:
                    print("          first difference at line %d" % (i + 1))
                    print("          baseline: %s" % a)
                    print("          now     : %s" % b)
                    break
            if len(g) != len(w):
                print("          line count %d -> %d" % (len(w), len(g)))

    print()
    if skipped:
        print("skipped (--quick): %s" % ", ".join(skipped))
    if failed:
        print("REGRESSION: %d of %d scripts differ: %s"
              % (len(failed), len(sections) - len(skipped), ", ".join(failed)))
        return 1
    print("all %d scripts reproduce the pre-refactor baseline exactly"
          % (len(sections) - len(skipped)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
