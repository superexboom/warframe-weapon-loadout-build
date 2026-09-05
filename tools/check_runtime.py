"""Small offline smoke check for a generated runtime dataset."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


def main():
    assert app.CATALOG["buildLabel"] == app.WARFRAME_CATALOG["buildLabel"]
    weapon = next(row for row in app.CATALOG["weapons"] if row["nameEn"] == "Boltor" and row["buildAvailable"])
    result = app.simulate_manual_payload({"weapon": weapon["path"], "enemy": app.CATALOG["enemies"][0]["path"], "mods": []})
    assert result["moddedStats"]["totalDamage"] > 0
    frame = app.WARFRAME_CATALOG["warframes"][0]
    calculated = app.WARFRAME_ENGINE.calculate({"frameId": frame["id"], "normalMods": [None] * 8})
    assert calculated["validation"]["valid"]
    assert all(Path(module.__file__).is_relative_to(app.ROOT / "vendor")
               for name, module in sys.modules.items() if name == "wfarsenal" or name.startswith("wfarsenal."))
    print(f"Runtime OK: {app.CATALOG['buildLabel']}")


if __name__ == "__main__":
    main()
