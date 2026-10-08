#!/usr/bin/env python3
"""Verify completed Android CI runs and publish durable APK releases. No source code is executed."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile

STORE = 'Incridea-NMAMIT/incridea-store'
SOURCES = {
    'Incridea-NMAMIT/incridea-dashboard': {'in.incridea.dashboard': 'dashboard'},
    'Incridea-NMAMIT/incridea-operations': {'in.incridea.operations': 'operations', 'in.incridea.pronite': 'pronite'},
    'Incridea-NMAMIT/incridea-deploy': {'in.incridea.deploy': 'deploy'},
}
MAX_ARCHIVE = 512 * 1024 * 1024

class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlparse(newurl)
        if target.scheme != 'https' or not (target.hostname == 'github.com' or target.hostname.endswith('.blob.core.windows.net') or target.hostname.endswith('.actions.githubusercontent.com') or target.hostname.endswith('.githubusercontent.com')):
            raise ValueError('Untrusted artifact redirect')
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            redirected.remove_header('Authorization')
        return redirected

class Github:
    def __init__(self, source_token, store_token):
        self.source_token, self.store_token = source_token, store_token
        self.opener = urllib.request.build_opener(SafeRedirect())

    def request(self, path, method='GET', data=None, source=False, binary=False):
        if not path.startswith('/repos/' + STORE + '/') and not (source and any(path.startswith('/repos/' + repo + '/') for repo in SOURCES)):
            raise ValueError('Repository is not allowlisted')
        url = 'https://api.github.com' + path
        token = self.source_token if source else self.store_token
        payload = None if data is None else json.dumps(data).encode()
        headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/octet-stream' if binary else 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'incridea-store', 'Content-Type': 'application/json'}
        with self.opener.open(urllib.request.Request(url, data=payload, method=method, headers=headers), timeout=120) as response:
            body = response.read(MAX_ARCHIVE + 1)
            if len(body) > MAX_ARCHIVE:
                raise ValueError('Response exceeds size limit')
            return body if binary else json.loads(body) if body else {}

    def optional(self, path, source=False):
        try:
            return self.request(path, source=source)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            raise

    def pages(self, path, key=None, source=False):
        result = []
        for page in range(1, 101):
            body = self.request(path + ('&' if '?' in path else '?') + f'per_page=100&page={page}', source=source)
            items = body[key] if key else body
            result.extend(items)
            if len(items) < 100:
                return result
        raise ValueError('Pagination limit exceeded')

    def upload(self, release_id, name, content):
        url = f'https://uploads.github.com/repos/{STORE}/releases/{release_id}/assets?name=' + urllib.parse.quote(name)
        request = urllib.request.Request(url, data=content, method='POST', headers={'Authorization': 'Bearer ' + self.store_token, 'Content-Type': 'application/vnd.android.package-archive', 'Accept': 'application/vnd.github+json', 'User-Agent': 'incridea-store'})
        with self.opener.open(request, timeout=120) as response:
            return json.load(response)


def validate_run(repository, run_id, run, jobs):
    if repository not in SOURCES or not re.fullmatch(r'[0-9]+', str(run_id)):
        raise ValueError('Unknown repository or invalid run ID')
    if str(run.get('id')) != str(run_id) or run.get('repository', {}).get('full_name') != repository or run.get('event') != 'push' or run.get('head_branch') != 'main' or run.get('status') != 'completed' or run.get('conclusion') != 'success' or run.get('path') != '.github/workflows/deploy-ci.yml':
        raise ValueError('Only successful completed main push workflows are accepted')
    if not re.fullmatch(r'[a-f0-9]{40}', run.get('head_sha', '')) or not 1 <= int(run.get('run_number', 0)) <= 2_099_999_000:
        raise ValueError('Invalid source version')
    for label in ['build', 'Android validation', 'Signed Android release']:
        selected = [j for j in jobs if j['name'] == label or j['name'].endswith(' / ' + label) or (' / ' + label + ' (') in j['name'] or j['name'].startswith(label + ' (')]
        if not selected or any(j.get('conclusion') != 'success' for j in selected):
            raise ValueError('Required successful job missing: ' + label)


def fingerprint(value):
    value = value.replace(':', '').lower()
    if not re.fullmatch(r'[a-f0-9]{64}', value):
        raise ValueError('Signing certificate SHA-256 is not configured')
    return value


def inspect_apk(path, package_id, expected_fingerprint, run_number):
    signed = subprocess.run([os.environ['APKSIGNER'], 'verify', '--verbose', '--print-certs', str(path)], check=True, capture_output=True, text=True).stdout
    fingerprints = re.findall(r'^Signer #\d+ certificate SHA-256 digest: ([a-fA-F0-9]+)$', signed, re.MULTILINE)
    if len(fingerprints) != 1 or fingerprint(fingerprints[0]) != fingerprint(expected_fingerprint):
        raise ValueError('APK signing certificate mismatch')
    badging = subprocess.run([os.environ['AAPT'], 'dump', 'badging', str(path)], check=True, capture_output=True, text=True).stdout
    package = re.search(r"^package: name='([^']+)' versionCode='(\d+)' versionName='([^']+)'", badging, re.MULTILINE)
    sdk = re.search(r"^sdkVersion:'(\d+)'", badging, re.MULTILINE)
    if not package or not sdk or package[1] != package_id:
        raise ValueError('APK package or SDK metadata mismatch')
    if int(package[2]) != 1000 + run_number or not package[3].endswith('+ci.' + str(run_number)):
        raise ValueError('APK CI version mismatch')
    content = path.read_bytes()
    return {'versionCode': int(package[2]), 'versionName': package[3], 'minimumSdk': int(sdk[1]), 'size': len(content), 'sha256': hashlib.sha256(content).hexdigest(), 'signingSha256': fingerprint(fingerprints[0])}


def apk_from_archive(content, digest):
    if 'sha256:' + hashlib.sha256(content).hexdigest() != digest:
        raise ValueError('Artifact archive digest mismatch')
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        apks = [i for i in archive.infolist() if i.filename.endswith('.apk')]
        if len(apks) != 1 or apks[0].file_size > MAX_ARCHIVE or apks[0].file_size <= 0 or apks[0].flag_bits & 1:
            raise ValueError('Expected exactly one unencrypted release APK')
        if apks[0].compress_size == 0 or apks[0].file_size / apks[0].compress_size > 200:
            raise ValueError('Archive compression exceeds limit')
        return archive.read(apks[0])


def merge_release(catalog, package_id, release):
    if catalog.get('schemaVersion') != 1 or not isinstance(catalog.get('apps'), list):
        raise ValueError('Unsupported catalog')
    if len({a['packageId'] for a in catalog['apps']}) != len(catalog['apps']):
        raise ValueError('Duplicate catalog apps')
    app = next((a for a in catalog['apps'] if a['packageId'] == package_id), None)
    if app is None:
        app = {'packageId': package_id, 'releases': []}
        catalog['apps'].append(app)
    existing = next((r for r in app['releases'] if r['versionCode'] == release['versionCode']), None)
    if existing:
        if existing != release:
            raise ValueError('Conflicting metadata for an existing version code')
        return False
    if app['releases'] and app['releases'][0]['signingSha256'] != release['signingSha256']:
        raise ValueError('Signing key changes require a deliberate migration')
    app['releases'].append(release)
    app['releases'].sort(key=lambda r: r['versionCode'], reverse=True)
    catalog['updatedAt'] = max(catalog['updatedAt'], release['publishedAt'])
    return True


def publish_asset(github, tag, name, metadata, apk):
    release = github.optional(f'/repos/{STORE}/releases/tags/{tag}')
    if release is None:
        release = github.request(f'/repos/{STORE}/releases', 'POST', {'tag_name': tag, 'target_commitish': 'main', 'name': name, 'body': metadata['changelog'], 'draft': True, 'prerelease': False})
    assets = github.pages(f'/repos/{STORE}/releases/{release["id"]}/assets')
    existing = next((a for a in assets if a['name'] == name), None)
    if existing is None:
        existing = github.upload(release['id'], name, apk)
    # API digest is available on newly uploaded assets; verify old assets by their bytes too.
    if existing.get('size') != len(apk):
        raise ValueError('Existing release asset size conflict')
    actual_digest = existing.get('digest')
    if actual_digest is None:
        content = github.request(f'/repos/{STORE}/releases/assets/{existing["id"]}', binary=True)
        actual_digest = 'sha256:' + hashlib.sha256(content).hexdigest()
    if actual_digest != 'sha256:' + metadata['sha256']:
        raise ValueError('Existing release asset checksum conflict')
    if release['draft']:
        release = github.request(f'/repos/{STORE}/releases/{release["id"]}', 'PATCH', {'draft': False, 'make_latest': 'false'})
    return {**metadata, 'tag': tag, 'publishedAt': release['published_at'], 'downloadUrl': existing['browser_download_url']}


def main():
    repository = os.environ['SOURCE_REPOSITORY']
    run_id = os.environ['SOURCE_RUN_ID']
    if repository not in SOURCES or not re.fullmatch(r'[0-9]+', run_id):
        raise ValueError('Invalid dispatch')
    github = Github(os.environ['SOURCE_TOKEN'], os.environ['STORE_TOKEN'])
    run = github.request(f'/repos/{repository}/actions/runs/{run_id}', source=True)
    jobs = github.pages(f'/repos/{repository}/actions/runs/{run_id}/attempts/{run["run_attempt"]}/jobs', 'jobs', source=True)
    validate_run(repository, run_id, run, jobs)
    certificates = json.loads(os.environ['SIGNING_FINGERPRINTS'])
    artifacts = github.pages(f'/repos/{repository}/actions/runs/{run_id}/artifacts', 'artifacts', source=True)
    catalog_file = github.optional(f'/repos/{STORE}/contents/catalog.json?ref=catalog')
    catalog = json.loads(base64.b64decode(catalog_file['content'])) if catalog_file else {'schemaVersion': 1, 'updatedAt': '1970-01-01T00:00:00Z', 'apps': []}
    prepared = []
    # Validate every APK before publishing any release from a matrix run.
    for package_id, slug in SOURCES[repository].items():
        expected_name = f'signed-{package_id}-{run["head_sha"]}'
        found = [a for a in artifacts if a['name'] == expected_name]
        if len(found) != 1 or found[0].get('expired') or found[0].get('workflow_run', {}).get('id') != int(run_id) or found[0].get('workflow_run', {}).get('head_sha') != run['head_sha']:
            raise ValueError('Signed artifact missing, ambiguous, expired or from another run')
        archive = github.request(f'/repos/{repository}/actions/artifacts/{found[0]["id"]}/zip', source=True, binary=True)
        apk = apk_from_archive(archive, found[0].get('digest'))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'release.apk'
            path.write_bytes(apk)
            metadata = inspect_apk(path, package_id, certificates.get(package_id, ''), int(run['run_number']))
        metadata.update({'sourceSha': run['head_sha'], 'runId': run_id, 'changelog': f'Signed Android release {metadata["versionName"]}. Built from commit {run["head_sha"][:12]}.'})
        old = next((r for a in catalog['apps'] if a['packageId'] == package_id for r in a['releases'] if r['versionCode'] == metadata['versionCode']), None)
        if old and any(old[key] != value for key, value in metadata.items()):
            raise ValueError('Conflicting release metadata')
        prepared.append((package_id, slug, metadata, apk))
    changed = False
    for package_id, slug, metadata, apk in prepared:
        tag = f'{slug}-{metadata["versionCode"]}-{run["head_sha"][:12]}'
        name = f'{slug}-{metadata["versionCode"]}.apk'
        published = publish_asset(github, tag, name, metadata, apk)
        changed = merge_release(catalog, package_id, published) or changed
    if not changed:
        print('Verified releases already published; catalog unchanged.')
        return
    if github.optional(f'/repos/{STORE}/git/ref/heads/catalog') is None:
        head = github.request(f'/repos/{STORE}/git/ref/heads/main')['object']['sha']
        github.request(f'/repos/{STORE}/git/refs', 'POST', {'ref': 'refs/heads/catalog', 'sha': head})
    data = {'message': f'Publish verified Android releases from run {run_id}', 'branch': 'catalog', 'content': base64.b64encode((json.dumps(catalog, indent=2) + '\n').encode()).decode()}
    if catalog_file:
        data['sha'] = catalog_file['sha']
    github.request(f'/repos/{STORE}/contents/catalog.json', 'PUT', data)
    print('Published verified APKs and updated public catalog.')

if __name__ == '__main__':
    main()
