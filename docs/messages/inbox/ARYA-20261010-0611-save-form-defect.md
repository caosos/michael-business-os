# Addendum to 0610: confirmed rendered Save-form defect

Handle within the same existing serial acceptance work, not another worker or feature lane.

F54 dec45871451737577073e79ebd8da5784e4892e5 operator_ui/market_view.py _save(), lines191-200, omits cat, row1-row4 and condition from hidden fields. save_form serialization now accepts them, but a real Save click does not submit them. A17 evidence showing focus:none after cat=trailers is consistent with this loss. Unit tests injecting fields directly do not verify the actual rendered form.

Reproduce through the real page, minimally fix propagation of already-supported categories, row order and condition, and assert real Save/reopen/restart retention without relaxing strict filters. Continue 0610 clean real-cache visual acceptance in isolated staging before any live reload. For navigation/result checks, compare visible known-section IDs, excluding hidden unknown cards; equal counts of all .mk-g elements cannot prove filter changes. Downgrade any matrix case missing required substeps rather than claim PASS.

No live reload, new credentials, installs, extra paid usage or duplicate dispatch. Existing owner scope only.
