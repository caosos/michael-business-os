# Design-artifact check (NOT production code): validates contracts/*.schema.json + vendor/agent-03 schemas,
# validates examples/, and asserts the invariants (no receipt w/o provenance; irreversible => tier 0;
# flip/service category + economics discriminator). Usage: python -I validate_contracts.py docs/research/contracts
# Requires: pip install jsonschema (>=4.18, uses `referencing`).
import json, sys, pathlib
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
root = pathlib.Path(sys.argv[1])
schemas = {}
for p in list(root.glob("*.schema.json")) + list(root.glob("vendor/agent-03/*.schema.json")):
    s = json.loads(p.read_text()); Draft202012Validator.check_schema(s); schemas[p.name] = s
reg = Registry().with_resources([(s["$id"], Resource.from_contents(s)) for s in schemas.values()])
pairs = {"item-": "item", "action-request-": "action-request", "approval-": "approval", "receipt-": "receipt", "provenance-": "provenance", "outcome-": "outcome"}
fail = 0
for ex in sorted(root.glob("examples/*.json")):
    key = next(v for k, v in pairs.items() if ex.name.startswith(k))
    v = Draft202012Validator(schemas[f"{key}.schema.json"], registry=reg)
    errs = list(v.iter_errors(json.loads(ex.read_text())))
    print(("PASS " if not errs else "FAIL ") + ex.name)
    for e in errs: print("   ", list(e.absolute_path), e.message[:200]); fail += 1
# negative tests: invariants must reject
neg = json.loads((root/"examples/action-request-email-held.example.json").read_text()); neg["tier"] = 1
assert list(Draft202012Validator(schemas["action-request.schema.json"], registry=reg).iter_errors(neg)), "irreversible+tier1 should fail"
neg = json.loads((root/"examples/receipt-approval-decided.example.json").read_text()); neg["provenance_ids"] = []
assert list(Draft202012Validator(schemas["receipt.schema.json"], registry=reg).iter_errors(neg)), "receipt w/o provenance should fail"
neg = json.loads((root/"examples/item-flip-trailer.example.json").read_text()); neg["category"] = "drywall_repair"
assert list(Draft202012Validator(schemas["item.schema.json"], registry=reg).iter_errors(neg)), "flip with service category should fail"
neg = json.loads((root/"examples/item-service-drywall.example.json").read_text()); neg["economics"] = json.loads((root/"examples/item-flip-trailer.example.json").read_text())["economics"]
assert list(Draft202012Validator(schemas["item.schema.json"], registry=reg).iter_errors(neg)), "service with flip economics should fail"
print("negative invariant tests: PASS" if not fail else "")
print("schemas checked:", len(schemas)); sys.exit(1 if fail else 0)
