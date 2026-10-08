import base64
import json
import os
from publish import Github, STORE

def initialize(github):
    if github.optional(f'/repos/{STORE}/contents/catalog.json?ref=catalog'):
        return
    if github.optional(f'/repos/{STORE}/git/ref/heads/catalog') is None:
        head = github.request(f'/repos/{STORE}/git/ref/heads/main')['object']['sha']
        github.request(f'/repos/{STORE}/git/refs', 'POST', {'ref':'refs/heads/catalog', 'sha':head})
    catalog = {'schemaVersion':1, 'updatedAt':'1970-01-01T00:00:00Z', 'apps':[]}
    github.request(f'/repos/{STORE}/contents/catalog.json', 'PUT', {'message':'Initialize public Android release catalog', 'branch':'catalog', 'content':base64.b64encode((json.dumps(catalog,indent=2)+'\n').encode()).decode()})

if __name__ == '__main__':
    initialize(Github('', os.environ['STORE_TOKEN']))
