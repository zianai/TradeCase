"""One public URL, no login/browser/cookies/proxy/paid API. Captures failures too."""
import json
from pathlib import Path

from tradecase.providers import ContentReader, ReadPolicy

reader = ContentReader(ReadPolicy(max_pages=1, max_requests=6, max_bytes=65536, timeout_seconds=18))
result = reader.read('https://quotes.toscrape.com/js/')
output = result.to_dict()
output['test_mode'] = 'tested_live: actual bounded public HTTP attempt; status must be inspected'
output['command'] = '.venv/bin/python docs/evidence/P3/run_live_smoke.py'
path = Path(__file__).parent / 'public-http-live.json'
path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({key: output[key] for key in ['requested_url', 'final_url', 'captured_at', 'status', 'http_status', 'sha256', 'byte_count', 'blockers', 'warnings', 'robots', 'budget']}, indent=2))
raise SystemExit(0 if result.status == 'fetched' else 2)
