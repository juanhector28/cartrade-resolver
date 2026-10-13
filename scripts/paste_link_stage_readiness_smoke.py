"""Read-only smoke of deployed staging release ledger, no third-party access."""
import asyncio
import json
import httpx

BASE="https://cartrade-paste-link-staging.onrender.com"

async def main():
    async with httpx.AsyncClient(timeout=40,follow_redirects=False) as cli:
        h=await cli.get(BASE+"/health")
        r=await cli.get(BASE+"/api/coverage")
        s=await cli.get(BASE+"/api/sources")
        ui=await cli.get(BASE)
        health=h.json() if h.status_code==200 else {}
        ledger=r.json() if r.status_code==200 else {}
        sources=s.json().get("sources",[]) if s.status_code==200 else []
        verified=[x for x in sources if x.get("stage")=="browser_sample_verified" and x.get("enabled")]
        checks={
          "health_200":h.status_code==200 and health.get("ok") is True,
          "staging_only":health.get("environment")=="staging" and health.get("production") is False and health.get("storage") is False,
          "source_count":health.get("sources_enabled")==14,
          "coverage_200":r.status_code==200,
          "pilot_candidates":ledger.get("pilot_candidates")==11,
          "qa_listing_samples":ledger.get("core_field_samples_verified")==33,
          "release_gate_closed":ledger.get("production_deploy_permitted") is False and not ledger.get("production_approved_domains"),
          "source_chips":len(verified)==11,
          "front_end_200":ui.status_code==200 and 'id="coverage"' in ui.text,
        }
        print(json.dumps({"base":BASE,"checks":checks,"actual":{
          "enabled":health.get("sources_enabled"),
          "pilot_candidates":ledger.get("pilot_candidates"),
          "field_samples":ledger.get("core_field_samples_verified"),
          "source_chips":len(verified),
          "deploy_allowed":ledger.get("production_deploy_permitted")
        }},ensure_ascii=False),flush=True)
        assert all(checks.values()), "staging readiness contract failed"

if __name__=="__main__":
    asyncio.run(main())
