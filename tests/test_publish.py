import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import zipfile

spec=importlib.util.spec_from_file_location('publish',Path(__file__).parents[1]/'scripts/publish.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
REPO='Incridea-NMAMIT/incridea-dashboard'
CERT='a'*64
APK=b'signed fixture apk'

def release(version=1001):
    return {'versionCode':version,'versionName':f'1.0.0+ci.{version-1000}','minimumSdk':26,'size':len(APK),'sha256':hashlib.sha256(APK).hexdigest(),'signingSha256':CERT,'sourceSha':'b'*40,'runId':str(version),'changelog':'Signed build','tag':f'dashboard-{version}','publishedAt':'2026-10-08T00:00:00Z','downloadUrl':f'https://github.com/{p.STORE}/releases/download/dashboard-{version}/dashboard-{version}.apk'}

class PublicationTests(unittest.TestCase):
    def test_only_successful_expected_completed_main_workflows(self):
        run={'id':1,'repository':{'full_name':REPO},'event':'push','head_branch':'main','status':'completed','conclusion':'success','path':'.github/workflows/deploy-ci.yml','head_sha':'b'*40,'run_number':1}
        jobs=[{'name':'application / '+n,'conclusion':'success'} for n in ['build','Android validation (android)','Signed Android release (android)']]
        p.validate_run(REPO,'1',run,jobs)
        for field,value in [('event','pull_request'),('head_branch','staging'),('status','in_progress'),('conclusion','cancelled'),('path','other.yml'),('head_sha','bad')]:
            with self.subTest(field=field),self.assertRaises(ValueError):p.validate_run(REPO,'1',{**run,field:value},jobs)
        with self.assertRaises(ValueError):p.validate_run(REPO,'1',run,jobs[:-1])
        with self.assertRaises(ValueError):p.validate_run(REPO,'1',run,[*jobs,{'name':'Signed Android release (other)','conclusion':'skipped'}])
    def test_archive_digest_and_exactly_one_apk(self):
        def archive(names):
            out=io.BytesIO()
            with zipfile.ZipFile(out,'w') as z:
                for name in names:z.writestr(name,APK)
            return out.getvalue()
        content=archive(['release/app.apk','release/app.aab'])
        self.assertEqual(p.apk_from_archive(content,'sha256:'+hashlib.sha256(content).hexdigest()),APK)
        with self.assertRaises(ValueError):p.apk_from_archive(content,'sha256:'+'0'*64)
        content=archive(['first.apk','second.apk'])
        with self.assertRaises(ValueError):p.apk_from_archive(content,'sha256:'+hashlib.sha256(content).hexdigest())
    def test_signature_package_and_version_are_verified(self):
        signed=f'Signer #1 certificate SHA-256 digest: {CERT}\n'
        badging="package: name='in.incridea.dashboard' versionCode='1001' versionName='1.0.0+ci.1'\nsdkVersion:'26'\n"
        with patch.dict(os.environ,{'APKSIGNER':'apksigner','AAPT':'aapt'}),patch.object(p.subprocess,'run') as run:
            with patch.object(Path,'read_bytes',return_value=APK):
                for actual_signed,actual_badging,valid in [(signed,badging,True),(signed.replace(CERT,'c'*64),badging,False),(signed,badging.replace('dashboard','deploy'),False),(signed,badging.replace("versionCode='1001'","versionCode='1'"),False),(signed+signed,badging,False)]:
                    run.side_effect=[subprocess.CompletedProcess([],0,actual_signed),subprocess.CompletedProcess([],0,actual_badging)]
                    if valid:self.assertEqual(p.inspect_apk(Path('fixture.apk'),'in.incridea.dashboard',CERT,1)['versionCode'],1001)
                    else:
                        with self.assertRaises(ValueError):p.inspect_apk(Path('fixture.apk'),'in.incridea.dashboard',CERT,1)
    def test_retries_ordering_and_conflicting_metadata(self):
        catalog={'schemaVersion':1,'updatedAt':'1970-01-01T00:00:00Z','apps':[]}
        self.assertTrue(p.merge_release(catalog,'in.incridea.dashboard',release(1002)))
        self.assertTrue(p.merge_release(catalog,'in.incridea.dashboard',release(1001)))
        self.assertEqual([r['versionCode'] for r in catalog['apps'][0]['releases']],[1002,1001])
        self.assertFalse(p.merge_release(catalog,'in.incridea.dashboard',release(1001)))
        with self.assertRaises(ValueError):p.merge_release(catalog,'in.incridea.dashboard',{**release(1001),'sha256':'d'*64})
        with self.assertRaises(ValueError):p.merge_release(catalog,'in.incridea.dashboard',{**release(1003),'signingSha256':'d'*64})
    def test_resume_draft_upload_then_publish_and_reuse_matching_asset(self):
        from unittest.mock import Mock
        github=Mock();github.optional.return_value={'id':10,'draft':True}
        asset={'id':20,'name':'dashboard-1001.apk','size':len(APK),'digest':'sha256:'+hashlib.sha256(APK).hexdigest(),'browser_download_url':release()['downloadUrl']}
        github.pages.return_value=[];github.upload.return_value=asset
        github.request.return_value={'published_at':release()['publishedAt']}
        published=p.publish_asset(github,'tag',asset['name'],release(),APK)
        self.assertEqual(published['downloadUrl'],asset['browser_download_url']);github.upload.assert_called_once()
        github.reset_mock();github.optional.return_value={'id':10,'draft':False,'published_at':release()['publishedAt']};github.pages.return_value=[asset]
        p.publish_asset(github,'tag',asset['name'],release(),APK);github.upload.assert_not_called();github.request.assert_not_called()
        github.pages.return_value=[{**asset,'digest':'sha256:'+'c'*64}]
        with self.assertRaises(ValueError):p.publish_asset(github,'tag',asset['name'],release(),APK)
    def test_redirects_strip_credentials_and_reject_untrusted_hosts(self):
        from urllib.request import Request
        redirect=p.SafeRedirect();req=Request('https://api.github.com/repos/x',headers={'Authorization':'Bearer fixture'})
        moved=redirect.redirect_request(req,None,302,'',{},'https://production.blob.core.windows.net/file')
        self.assertFalse(moved.has_header('Authorization'))
        with self.assertRaises(ValueError):redirect.redirect_request(req,None,302,'',{},'https://attacker.test/file')
    def test_shared_catalog_concurrency_and_compare_and_swap(self):
        workflow=(Path(__file__).parents[1]/'.github/workflows/publish-android.yml').read_text()
        init=(Path(__file__).parents[1]/'.github/workflows/initialize-catalog.yml').read_text()
        for text in (workflow,init):self.assertIn('group: public-android-catalog',text);self.assertIn('cancel-in-progress: false',text)
        source=(Path(__file__).parents[1]/'scripts/publish.py').read_text()
        self.assertIn("data['sha'] = catalog_file['sha']",source)

if __name__=='__main__':unittest.main()
