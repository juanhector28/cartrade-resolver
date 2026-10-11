"""One-shot public-browser EasyCar loading diagnosis, no scraping or persistence."""
from __future__ import annotations
import asyncio
import json
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
import httpx
from playwright.async_api import async_playwright

URL="https://easycar.com.sv/car/109"
AGENT="CarTrade-Link-Diagnostic/0.1"

async def main():
    async with httpx.AsyncClient(timeout=12, follow_redirects=False,
        headers={"User-Agent":AGENT}) as cli:
        r=await cli.get("https://easycar.com.sv/robots.txt")
    status={"source":"easycar","robots_status":r.status_code,"test_url":URL}
    if r.status_code != 200:
        status["result"]="robots_not_confirmed"
        print(json.dumps(status),flush=True);return
    robots=RobotFileParser();robots.parse(r.text.splitlines())
    if not robots.can_fetch(AGENT,URL):
        status["result"]="robots_disallow"
        print(json.dumps(status),flush=True);return
    async with async_playwright() as api:
        browser=await api.chromium.launch(headless=True,args=["--no-sandbox"])
        page=await browser.new_page(viewport={"width":1200,"height":750})
        reqs=[]
        def observed(response):
            p=urlparse(response.url)
            if response.request.resource_type not in {"fetch","xhr"}:return
            if p.hostname and len(reqs)<20:
                reqs.append({"host":p.hostname,"path":p.path[:130],
                    "status":response.status,"content_type":response.headers.get("content-type","")[:75]})
        page.on("response",observed)
        try:
            response=await page.goto(URL,wait_until="domcontentloaded",timeout=40000)
            status["page_status"]=response.status if response else None
            await page.wait_for_timeout(7000)
            title=await page.title()
            main=await page.locator("body").inner_text(timeout=9000)
            status["rendered_title"]=title[:130]
            status["has_vehicle_title"]="Hyundai Accent" in main
            status["has_reference_price"]="11,600" in main or "11600" in main
            status["body_length"]=len(main)
            status["requests"]=reqs
        except Exception as exc:
            status["error_type"]=type(exc).__name__
        await browser.close()
    print(json.dumps(status,ensure_ascii=False),flush=True)

if __name__=="__main__":
    asyncio.run(main())
