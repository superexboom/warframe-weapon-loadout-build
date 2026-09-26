param([int]$Limit=0,[int]$Shard=0,[int]$Shards=1,[switch]$IncludeCompanions,[string]$Output="docs/evidence/nonmelee-catalog-20260926")
$env:WF_ANALYZER_SERIAL="1"
$argsList=@("tools/audit_nonmelee_catalog.py","--output",$Output,"--profile","fast","--shard",$Shard,"--shards",$Shards)
if($Limit -gt 0){$argsList += @("--limit",$Limit)}
if($IncludeCompanions){$argsList += "--include-companions"}
python @argsList
