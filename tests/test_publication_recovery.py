import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile

spec=importlib.util.spec_from_file_location('publisher',Path(__file__).parents[1]/'scripts/publish.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
REPO='Incridea-NMAMIT/incridea-dashboard';PACKAGE='in.incridea.dashboard';SHA='b'*40

class GithubFixture:
    def __init__(self):
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:z.writestr('release/app.apk',b'fixture apk')
        self.archive=out.getvalue();self.releases={};self.assets={};self.catalog=None;self.fail_write=True;self.uploads=0
    def optional(self,path,source=False):
        if '/contents/catalog.json?' in path:
            return None if self.catalog is None else {'content':base64.b64encode(json.dumps(self.catalog).encode()).decode(),'sha':'revision'}
        if '/releases/tags/' in path:return self.releases.get(path.rsplit('/',1)[-1])
        if '/git/ref/heads/' in path:return {'object':{'sha':'c'*40}}
        raise AssertionError(path)
    def pages(self,path,key=None,source=False):
        if path.endswith('/jobs'):return [{'name':name,'conclusion':'success'} for name in ['build','Android validation (android)','Signed Android release (android)']]
        if path.endswith('/artifacts'):return [{'id':20,'name':f'signed-{PACKAGE}-{SHA}','expired':False,'workflow_run':{'id':123,'head_sha':SHA},'digest':'sha256:'+hashlib.sha256(self.archive).hexdigest()}]
        if path.endswith('/assets'):return self.assets.get(10,[])
        raise AssertionError(path)
    def request(self,path,method='GET',data=None,source=False,binary=False):
        if path.endswith('/actions/runs/123'):return {'id':123,'repository':{'full_name':REPO},'event':'push','head_branch':'main','status':'completed','conclusion':'success','path':'.github/workflows/deploy-ci.yml','head_sha':SHA,'run_number':1,'run_attempt':1}
        if path.endswith('/zip'):return self.archive
        if path.endswith('/releases') and method=='POST':
            release={**data,'id':10,'published_at':None};self.releases[data['tag_name']]=release;return release
        if path.endswith('/releases/10') and method=='PATCH':
            release=next(iter(self.releases.values()));release.update({'draft':False,'published_at':'2026-10-08T06:00:00Z'});return release
        if path.endswith('/contents/catalog.json') and method=='PUT':
            if self.fail_write:
                self.fail_write=False
                raise RuntimeError('Simulated catalog compare-and-swap failure')
            self.catalog=json.loads(base64.b64decode(data['content']));return {}
        raise AssertionError(path)
    def upload(self,release_id,name,content):
        self.uploads+=1
        tag=next(iter(self.releases))
        asset={'id':21,'name':name,'size':len(content),'digest':'sha256:'+hashlib.sha256(content).hexdigest(),'browser_download_url':f'https://github.com/{p.STORE}/releases/download/{tag}/{name}'}
        self.assets[release_id]=[asset];return asset

class RecoveryTests(unittest.TestCase):
    def test_matrix_rejects_unapproved_later_draft_before_any_publication(self):
        repository='Incridea-NMAMIT/incridea-operations'
        packages={'in.incridea.operations':'operations','in.incridea.pronite':'pronite'}
        class MatrixFixture(GithubFixture):
            def optional(self,path,source=False):
                if '/releases/tags/pronite-' in path:return {'id':99,'draft':True}
                return super().optional(path,source)
            def pages(self,path,key=None,source=False):
                if path.endswith('/artifacts'):return [{'id':20+index,'name':f'signed-{package}-{SHA}','expired':False,'workflow_run':{'id':123,'head_sha':SHA},'digest':'sha256:'+hashlib.sha256(self.archive).hexdigest()} for index,package in enumerate(packages)]
                if path.endswith('/releases/99/assets'):return [{'id':90,'name':'private-source.zip'}]
                return super().pages(path,key,source)
            def request(self,path,method='GET',data=None,source=False,binary=False):
                value=super().request(path,method,data,source,binary)
                if path.endswith('/actions/runs/123'):value['repository']['full_name']=repository
                return value
        github=MatrixFixture();github.fail_write=False
        metadata={'versionCode':1001,'versionName':'1.0.0+ci.1','minimumSdk':26,'size':11,'sha256':hashlib.sha256(b'fixture apk').hexdigest(),'signingSha256':'a'*64}
        env={'SOURCE_REPOSITORY':repository,'SOURCE_RUN_ID':'123','SOURCE_TOKEN':'fixture','STORE_TOKEN':'fixture','SIGNING_FINGERPRINTS':json.dumps({package:'a'*64 for package in packages})}
        with patch.dict(os.environ,env),patch.object(p,'Github',return_value=github),patch.object(p,'inspect_apk',return_value=metadata):
            with self.assertRaisesRegex(ValueError,'unapproved'):p.main()
        self.assertEqual(github.uploads,0);self.assertEqual(github.releases,{})
    def test_signing_key_change_is_rejected_before_publication(self):
        github=GithubFixture();github.fail_write=False
        github.catalog={'schemaVersion':1,'updatedAt':'2026-10-08T00:00:00Z','apps':[{'packageId':PACKAGE,'releases':[{'versionCode':1000,'signingSha256':'c'*64}]}]}
        metadata={'versionCode':1001,'versionName':'1.0.0+ci.1','minimumSdk':26,'size':11,'sha256':hashlib.sha256(b'fixture apk').hexdigest(),'signingSha256':'a'*64}
        env={'SOURCE_REPOSITORY':REPO,'SOURCE_RUN_ID':'123','SOURCE_TOKEN':'fixture','STORE_TOKEN':'fixture','SIGNING_FINGERPRINTS':json.dumps({PACKAGE:'a'*64})}
        with patch.dict(os.environ,env),patch.object(p,'Github',return_value=github),patch.object(p,'inspect_apk',return_value=metadata):
            with self.assertRaisesRegex(ValueError,'Signing key'):p.main()
        self.assertEqual(github.uploads,0);self.assertEqual(github.releases,{})
    def test_partial_publication_replay_recovers_catalog_without_duplicate_assets(self):
        github=GithubFixture()
        metadata={'versionCode':1001,'versionName':'1.0.0+ci.1','minimumSdk':26,'size':11,'sha256':hashlib.sha256(b'fixture apk').hexdigest(),'signingSha256':'a'*64}
        env={'SOURCE_REPOSITORY':REPO,'SOURCE_RUN_ID':'123','SOURCE_TOKEN':'fixture','STORE_TOKEN':'fixture','SIGNING_FINGERPRINTS':json.dumps({PACKAGE:'a'*64})}
        with patch.dict(os.environ,env),patch.object(p,'Github',return_value=github),patch.object(p,'inspect_apk',return_value=metadata):
            with self.assertRaisesRegex(RuntimeError,'compare-and-swap'):p.main()
            self.assertIsNone(github.catalog);self.assertEqual(github.uploads,1)
            p.main();self.assertEqual(github.uploads,1)
            self.assertEqual(github.catalog['apps'][0]['releases'][0]['versionCode'],1001)
            snapshot=json.dumps(github.catalog)
            p.main();self.assertEqual(json.dumps(github.catalog),snapshot);self.assertEqual(github.uploads,1)
    def test_publication_rejects_unknown_repository_before_network_access(self):
        with patch.dict(os.environ,{'SOURCE_REPOSITORY':'attacker/repo','SOURCE_RUN_ID':'123'}),patch.object(p,'Github') as github:
            with self.assertRaises(ValueError):p.main()
            github.assert_not_called()

if __name__=='__main__':unittest.main()
