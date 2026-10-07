"""Subprocess probe: run ONE lane's own hashing code on ADR-0010 vectors.json and print a JSON result.

Usage: python _probe.py <lane-src-root> <vectors.json> <spec-json>
spec = {"payload": "pkg.mod:fn" | "pkg.mod:fn|canon_then_ref:fn2", "row": "pkg.mod:fn" | null, "row_style": "doc"|"split"}
Runs in its own process so each lane's modules load with their own package context and never clash.
"""
import importlib
import json
import sys


def _get(dotted):
    mod, fn = dotted.split(":")
    return getattr(importlib.import_module(mod), fn)


def main():
    root, vec_path, spec = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
    sys.path.insert(0, root)
    vec = json.loads(open(vec_path, encoding="utf-8").read())
    out = {"cjson": [], "reject": [], "chain": None, "load_error": None}
    try:
        if "|" in spec["payload"]:  # canonical_json + separate sha256 wrapper (02 style)
            a, b = spec["payload"].split("|")
            canon, ref = _get(a), _get(b)
            payload = lambda o: ref(canon(o))  # noqa: E731
        else:
            payload = _get(spec["payload"])
        row = _get(spec["row"]) if spec.get("row") else None
    except Exception as e:  # noqa: BLE001
        out["load_error"] = f"{type(e).__name__}: {e}"
        print(json.dumps(out))
        return
    for case in vec["cjson"]:
        try:
            got = payload(json.loads(case["input"]))
            out["cjson"].append({"name": case["name"], "ok": got == case["sha256"], "got": got})
        except Exception as e:  # noqa: BLE001
            out["cjson"].append({"name": case["name"], "ok": False, "got": f"RAISED {type(e).__name__}"})
    for case in vec["reject"]:
        try:
            payload(json.loads(case["input"]))
            out["reject"].append({"name": case["name"], "ok": False, "got": "accepted"})
        except Exception as e:  # noqa: BLE001
            out["reject"].append({"name": case["name"], "ok": True, "got": type(e).__name__})
    if row:
        ok, why = True, f"{len(vec['receipt_chain'])} receipts verified"
        for r in vec["receipt_chain"]:
            try:
                if spec.get("row_style") == "split":
                    got = row({k: v for k, v in r.items() if k != "row_hash"}, r.get("prev_hash"))
                else:
                    got = row(r)
            except Exception as e:  # noqa: BLE001
                ok, why = False, f"seq {r['seq']}: RAISED {type(e).__name__}: {e}"
                break
            if got != r["row_hash"]:
                ok, why = False, f"seq {r['seq']}: row_hash {got[:19]}… ≠ {r['row_hash'][:19]}…"
                break
        out["chain"] = {"ok": ok, "detail": why}
    print(json.dumps(out))


if __name__ == "__main__":
    main()
