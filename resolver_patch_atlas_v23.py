from pathlib import Path

runner = Path('/app/app/atlas_manifest_runner.py')
s = runner.read_text(encoding='utf-8')
marker = '# ATLAS_BROWSER_RUNTIME_GUARD_V23'

if marker not in s:
    init_old = '''        self.timeout = float(os.getenv("ATLAS_RUNNER_TIMEOUT", "25"))
        self.concurrency = max(1, min(int(os.getenv("ATLAS_RUNNER_CONCURRENCY", "4")), 8))
'''
    init_new = '''        self.timeout = float(os.getenv("ATLAS_RUNNER_TIMEOUT", "25"))
        self.concurrency = max(1, min(int(os.getenv("ATLAS_RUNNER_CONCURRENCY", "4")), 8))
        self.browser_run_concurrency = max(1, min(int(os.getenv("ATLAS_BROWSER_RUN_CONCURRENCY", "2")), 2))
        self.browser_page_concurrency = max(1, min(int(os.getenv("ATLAS_BROWSER_PAGE_CONCURRENCY", "1")), 3))
        self._browser_run_semaphore = asyncio.Semaphore(self.browser_run_concurrency)
'''
    if init_old not in s:
        raise RuntimeError('v23 runner init anchor missing')
    s = s.replace(init_old, init_new, 1)

    sem_old = '''        headers = {"User-Agent": USER_AGENT, "Accept-Language": "es,en;q=0.8"}
        sem = asyncio.Semaphore(self.concurrency)
'''
    sem_new = '''        headers = {"User-Agent": USER_AGENT, "Accept-Language": "es,en;q=0.8"}
        effective_concurrency = self.browser_page_concurrency if rendering == "browser" else self.concurrency
        sem = asyncio.Semaphore(effective_concurrency)
'''
    if sem_old not in s:
        raise RuntimeError('v23 execution semaphore anchor missing')
    s = s.replace(sem_old, sem_new, 1)

    browser_old = '            async with async_playwright() as pw:\n'
    browser_new = '            async with self._atlas_guarded_playwright(async_playwright()) as pw:\n'
    if browser_old not in s:
        raise RuntimeError('v23 browser manager anchor missing')
    s = s.replace(browser_old, browser_new, 1)

    s += r'''

# ATLAS_BROWSER_RUNTIME_GUARD_V23
from contextlib import asynccontextmanager as _atlas_asynccontextmanager


@_atlas_asynccontextmanager
async def _atlas_guarded_playwright(self, manager):
    # Browser manifests are the expensive lane. Keep HTTP manifests fully
    # concurrent, but bound Chromium processes globally per Resolver worker.
    async with self._browser_run_semaphore:
        async with manager as pw:
            yield pw


AtlasManifestRunner._atlas_guarded_playwright = _atlas_guarded_playwright
'''
runner.write_text(s, encoding='utf-8')

main = Path('/app/app/main.py')
ms = main.read_text(encoding='utf-8')
if '"browser_runtime_guard_v23": True' not in ms:
    anchor = '        "shadow_collision_protection": True,\n'
    replacement = '''        "shadow_collision_protection": True,
        "browser_runtime_guard_v23": True,
        "browser_run_concurrency": _atlas_manifest_runner.browser_run_concurrency,
        "browser_page_concurrency": _atlas_manifest_runner.browser_page_concurrency,
'''
    if anchor not in ms:
        raise RuntimeError('v23 runner status anchor missing')
    ms = ms.replace(anchor, replacement, 1)
main.write_text(ms, encoding='utf-8')

print('Applied Atlas runner v23 browser runtime guard')
