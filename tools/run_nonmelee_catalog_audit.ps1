param([int]$Limit=8,[string]$Output="docs/evidence/nonmelee-auto-20260926")
$env:WF_ANALYZER_SERIAL="1"
python tools/audit_nonmelee_catalog.py --output $Output --limit $Limit --profile fast
