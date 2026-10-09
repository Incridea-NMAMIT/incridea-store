import base64
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

scripts=Path(__file__).parents[1]/'scripts'
spec=importlib.util.spec_from_file_location('publish',scripts/'publish.py');publish=importlib.util.module_from_spec(spec);spec.loader.exec_module(publish)
with patch.dict(sys.modules,{'publish':publish}):
    spec=importlib.util.spec_from_file_location('recovery',scripts/'reconcile.py');recovery=importlib.util.module_from_spec(spec);spec.loader.exec_module(recovery)
REPO='Incridea-NMAMIT/incridea-dashboard';PACKAGE='in.incridea.dashboard'

class ReconcileTests(unittest.TestCase):
    def test_recovery_processes_more_than_twenty_runs_and_skips_before_cutover(self):
        from unittest.mock import Mock
        github=Mock()
        catalog={'apps':[{'packageId':PACKAGE,'releases':[{'runId':'5'}]}]}
        github.optional.return_value={'content':base64.b64encode(json.dumps(catalog).encode()).decode()}
        runs=[{'id':i,'created_at':'2026-10-09T06:00:00Z','run_attempt':1} for i in range(1,25)]
        runs.append({'id':99,'created_at':'2026-10-08T06:00:00Z','run_attempt':1})
        def pages(path,*args,**kwargs):
            if '/workflows/' in path:
                self.assertIn('created=%3E%3D',path);return runs
            return [{'name':'Signed Android release (android)','conclusion':'success'}]
        github.pages.side_effect=pages
        processed=[]
        with patch.dict(os.environ,{'SOURCE_TOKEN':'fixture','STORE_TOKEN':'fixture','PUBLICATION_SINCE':'2026-10-09T00:00:00Z'}),patch.object(recovery,'Github',return_value=github),patch.object(recovery,'SOURCES',{REPO:{PACKAGE:'dashboard'}}),patch.object(recovery,'main',side_effect=lambda:processed.append(os.environ['SOURCE_RUN_ID'])):
            recovery.reconcile()
        self.assertEqual(set(processed),{str(i) for i in range(1,25)}-{'5'})
    def test_cutover_requires_timezone(self):
        from unittest.mock import Mock
        github=Mock();github.optional.return_value=None
        with patch.dict(os.environ,{'SOURCE_TOKEN':'fixture','STORE_TOKEN':'fixture','PUBLICATION_SINCE':'2026-10-09T00:00:00'}),patch.object(recovery,'Github',return_value=github):
            with self.assertRaisesRegex(ValueError,'timezone'):recovery.reconcile()
            github.pages.assert_not_called()

if __name__=='__main__':unittest.main()
