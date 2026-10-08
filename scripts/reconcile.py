"""Recover completed builds whose notification or publication was interrupted."""
import base64
import json
import os
from publish import Github, SOURCES, STORE, main

def reconcile():
    github = Github(os.environ['SOURCE_TOKEN'], os.environ['STORE_TOKEN'])
    content = github.optional(f'/repos/{STORE}/contents/catalog.json?ref=catalog')
    catalog = json.loads(base64.b64decode(content['content'])) if content else {'apps': []}
    failures = 0
    for repository, packages in SOURCES.items():
        runs = github.request(f'/repos/{repository}/actions/workflows/deploy-ci.yml/runs?event=push&branch=main&status=success&per_page=20', source=True)['workflow_runs']
        for run in reversed(runs):
            if all(any(a['packageId'] == package and any(r['runId'] == str(run['id']) for r in a['releases']) for a in catalog['apps']) for package in packages):
                continue
            jobs = github.pages(f'/repos/{repository}/actions/runs/{run["id"]}/attempts/{run["run_attempt"]}/jobs', 'jobs', source=True)
            if not any('Signed Android release' in j['name'] and j.get('conclusion') == 'success' for j in jobs):
                continue
            os.environ['SOURCE_REPOSITORY'], os.environ['SOURCE_RUN_ID'] = repository, str(run['id'])
            try:
                main()
            except Exception as error:
                failures += 1
                print(f'Publication needs attention for {repository} run {run["id"]}: {type(error).__name__}: {error}')
    if failures:
        raise SystemExit(f'{failures} publication(s) require replay or configuration repair')

if __name__ == '__main__':
    reconcile()
