"""Prototype 5.6: write poc.metric/rule/edge/capability records into a World graph.json and validate.
Usage: proto_sync.py <path to .cosmos/graph.json of a throwaway World>
"""
import json, sys, os, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".vendor" / "cosmos"))
from tools.validate_ontology import validate_graph
from tools.reference_repository_projection import stable_cosmos_ref
gp = sys.argv[1]
g = json.load(open(gp))
actor = next(r for r in g if r.get("node_type")=="actor")["id"]
now = "2026-01-01T00:00:00Z"
prov = [{"relation":"created_by","source":actor}]
def node(key, **kw):
    d = {"record_type":"node","id":stable_cosmos_ref(key),"authority":{"class":"cosmos"},"provenance":prov,"temporal":{"created_at":now}}
    d.update(kw); return d
m = node("metric:net_revenue", node_type="entity", schema="cosmos.node/1", entity_type="poc.metric", display_name="net_revenue",
         description="Receita liquida", aliases=["Faturamento liquido"],
         extensions={"poc.metric":{"formula":"gross - refunds","version":"1.0.0"}})
k = node("rule:net_revenue", node_type="knowledge", schema="cosmos.knowledge/1", knowledge_class="rule", lifecycle_state="active",
         display_name="net_revenue rule", statement="net_revenue = sum(paid orders) - sum(effective refunds)", scope_refs=[m["id"]])
e = {"record_type":"edge","schema":"cosmos.edge/1","id":stable_cosmos_ref("edge:net_revenue"),"authority":{"class":"cosmos"},"provenance":prov,
     "temporal":{"created_at":now},"relation_type":"core.governed_by","source":m["id"],"target":k["id"]}
c = node("cap:query_metric", node_type="capability", schema="cosmos.capability/1", action="metric.query", decision="allow",
         grantee_refs=[actor], resources=[{"system":"duckdb","uri":"duckdb://analytics.duckdb"}], display_name="query_metric")
new = [r for r in g if r["id"] not in {m["id"],k["id"],e["id"],c["id"]}] + [m,k,e,c]
print("errors:", validate_graph(new))
json.dump(new, open(gp,"w"), indent=1)
